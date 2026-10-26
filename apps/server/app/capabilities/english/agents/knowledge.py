"""错误码知识卡：按 (user_id, code) 落库复用，DB 优先。

移植自 `.tmp/etutor-src/api/src/agents/knowledge.ts`：
- 先查库，命中直接返回（省一次模型调用）；
- 未命中则生成并落库；`llm.mock=True` 时用确定性兜底卡（离线演示整条链路可跑通，不发网络请求）。
"""
from __future__ import annotations

from pydantic import BaseModel, Field

from ..store import execute, json_dump, json_load, new_id, now_iso, one
from .taxonomy import TAXONOMY, code_label

SYSTEM = """你是英语语法知识卡编辑。针对给定的错误类型，写一张学习者能立刻看懂的小卡片。

要求：
1. title 不超过 20 字，点明这条规则的判断依据。
2. rule_md 用 Markdown，3–5 行：先给一句判断口诀，再给一个例外或易混点。
3. examples 给 2 条，wrong 是学生常写的错句，right 是改后的句子，note 一句话说明差别。
4. 不要罗列语法术语堆砌，要像老师在旁边说话。
只输出 JSON。"""


class CardExample(BaseModel):
    wrong: str
    right: str
    note: str = Field(max_length=60)


class CardSchema(BaseModel):
    """知识卡结构（模型输出）。"""

    title: str = Field(min_length=2, max_length=40)
    rule_md: str = Field(min_length=10, max_length=600)
    examples: list[CardExample] = Field(min_length=1, max_length=3)


async def get_or_create_card(user_id: int, code: str, llm) -> dict:
    """取知识卡：DB 优先，没有就生成并落库。返回 {code,label,title,rule_md,examples}。"""
    if code not in TAXONOMY:
        raise ValueError(f"未知错误码：{code}")

    hit = one(
        "SELECT title, rule_md, examples FROM english_knowledge_cards "
        "WHERE user_id = :user_id AND code = :code",
        user_id=user_id,
        code=code,
    )
    if hit:
        return {
            "code": code,
            "label": code_label(code),
            "title": hit["title"],
            "rule_md": hit["rule_md"],
            "examples": json_load(hit["examples"], []) or [],
        }

    card = fallback_card(code) if getattr(llm, "mock", False) else await generate_card(code, llm)

    execute(
        """INSERT OR IGNORE INTO english_knowledge_cards
               (id, user_id, code, title, rule_md, examples, created_at)
           VALUES (:id, :user_id, :code, :title, :rule_md, :examples, :created_at)""",
        id=new_id(),
        user_id=user_id,
        code=code,
        title=card.title,
        rule_md=card.rule_md,
        examples=json_dump([e.model_dump() for e in card.examples]),
        created_at=now_iso(),
    )
    return {
        "code": code,
        "label": code_label(code),
        "title": card.title,
        "rule_md": card.rule_md,
        "examples": [e.model_dump() for e in card.examples],
    }


async def generate_card(code: str, llm) -> CardSchema:
    """调用模型生成知识卡。"""
    card = await llm.json(
        system=SYSTEM,
        user=f"错误类型：{code}（{TAXONOMY[code]}）",
        schema=CardSchema,
        max_tokens=600,
    )
    return card if isinstance(card, CardSchema) else CardSchema.model_validate(card)


# ---------------------------------------------------------------- mock 兜底卡

# mock 模式下的确定性卡片：保证 M2 链路可验收，不是产品内容
HINTS: dict[str, CardSchema] = {
    "tense.present_perfect": CardSchema(
        title="have/has 后面只能接过去分词",
        rule_md=(
            '**口诀**：have/has + 过去分词，表示"到现在为止已经完成"。\n\n'
            "易混：`went` 是过去式，`gone` 才是过去分词。`has went` 是典型的中式迁移错误。"
        ),
        examples=[
            CardExample(
                wrong="She has went to Shanghai.",
                right="She has gone to Shanghai.",
                note="go 的三态：go – went – gone",
            ),
            CardExample(
                wrong="I have saw that film.",
                right="I have seen that film.",
                note="see 的三态：see – saw – seen",
            ),
        ],
    ),
    "agreement.subject_verb": CardSchema(
        title="第三人称单数，动词要变形",
        rule_md=(
            "**口诀**：he / she / it 或单数名词作主语，一般现在时动词加 -s（go→goes, have→has, do→does）。\n\n"
            "易混：只有一般现在时才变；过去时和情态动词后面不变。"
        ),
        examples=[
            CardExample(wrong="He go to work by bus.", right="He goes to work by bus.", note="go 加 -es"),
            CardExample(wrong="She have two brothers.", right="She has two brothers.", note="have 变 has"),
        ],
    ),
    "article.a_an_the": CardSchema(
        title="a / an 看的是发音，不是字母",
        rule_md=(
            "**口诀**：元音音素前用 an，辅音音素前用 a。\n\n"
            "易混：`an hour`（h 不发音）、`a university`（读 /juː/，辅音开头）。"
        ),
        examples=[
            CardExample(wrong="I ate a apple.", right="I ate an apple.", note="apple 以元音音素开头"),
            CardExample(wrong="It took a hour.", right="It took an hour.", note="hour 的 h 不发音，用 an"),
        ],
    ),
    "tense.present_continuous": CardSchema(
        title="状态动词不用进行时",
        rule_md=(
            "**口诀**：know / like / want / need / believe 这类表示状态而非动作的动词，一般不用 -ing。\n\n"
            "易混：表示\"正在体验\"时可以例外，如 `I'm loving it`，但正式写作里仍算不规范。"
        ),
        examples=[
            CardExample(wrong="I am know the answer.", right="I know the answer.", note="know 是状态动词"),
            CardExample(wrong="She is wanting a break.", right="She wants a break.", note="want 不用进行时"),
        ],
    ),
    "prep.time": CardSchema(
        title="时间介词：in 段、on 天、at 点",
        rule_md=(
            "**口诀**：in 用于年/月/季节/一天中的时段，on 用于具体某天，at 用于具体时刻。\n\n"
            "易混：`at night`、`in the morning` 是固定搭配。"
        ),
        examples=[
            CardExample(wrong="I will see you in Monday.", right="I will see you on Monday.", note="具体某天用 on"),
            CardExample(wrong="We met on 2020.", right="We met in 2020.", note="年份用 in"),
        ],
    ),
}


def fallback_card(code: str) -> CardSchema:
    """确定性兜底卡：HINTS 里没有的错误码用通用模板。"""
    hint = HINTS.get(code)
    if hint is not None:
        return hint
    label = TAXONOMY[code]
    return CardSchema(
        title=f"先看判断依据：{label}",
        rule_md=(
            f"**{label}** 的判断顺序：先看时间标志词，再看主语单复数，最后检查动词形式是否一致。\n\n"
            "易混点：中文没有形态变化，按中文语序直译时最容易在这一类出错。"
        ),
        examples=[
            CardExample(
                wrong="She go to work by bike every day.",
                right="She goes to work by bike every day.",
                note="第三人称单数要加 -s",
            ),
            CardExample(wrong="I am know the answer.", right="I know the answer.", note="状态动词不用进行时"),
        ],
    )

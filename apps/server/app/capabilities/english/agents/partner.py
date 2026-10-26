"""角色扮演 prompt 构造。

移植自 `.tmp/etutor-src/api/src/agents/partner.ts`：系统提示词是产品的核心资产，
这里**逐字照搬**中文原文与英文模板，只把调用方式改成 Python 关键字参数。
"""
from __future__ import annotations

LEVEL_GUIDE: dict[str, str] = {
    "A2": "短句为主（8–14 词），只用高频词，一个从句即可。",
    "B1": "句子 12–18 词，允许一个从句，偶尔出现短语动词。",
    "B2": "句长有明显变化，可用非谓语与从句，允许少量习语。",
    "C1": "接近母语日常口语，可用省略、倒装、地道搭配。",
}

STYLE_BANS = """写作禁忌（违反任意一条都算失败）：
1. 不用 "It is important to..." / "In conclusion" / "Overall" 开头。
2. 连续两句不得用相同句式开头。
3. 不用编号列表或项目符号，这是聊天不是文档。
4. 不解释语法、不做教学点评。
5. 不中英夹杂，不附翻译。
6. 不用 "delve" "tapestry" "furthermore" "moreover" "in today's world"。
7. 不以 "As an AI" 开头，不提及自己是模型。
8. 一段话里不超过 1 个感叹号、最多 1 个 emoji。
9. 不连续使用 "I think" / "I believe"。
10. 不给三个以上并列例子。
11. 句长必须变化，禁止每句都 15 词左右。
12. 结尾必须是一个具体的、能推动对话的问题。"""


def build_system_prompt(
    *,
    scenario_title: str,
    topic_title: str,
    beats: list[str],
    target_tenses: list[str],
    target_lexis: list[str],
    cefr: str,
    turn: int,
    must_use: list[str] | None = None,
    memory_block: str = "",
    history_summary: str = "",
    weak_hints: str = "",
    reference_block: str = "",
    max_reply_words: int = 90,
) -> str:
    """拼出本轮的 partner system prompt（照搬 TS 的 buildSystemPrompt）。"""
    beat = beats[min(turn, len(beats) - 1)] if beats else ""
    vocab_line = (
        f"\n- The learner is reviewing these words: {', '.join(must_use)}. "
        "Use them only if the situation makes it natural; never force a word, and never list them out."
        if must_use
        else ""
    )
    memory_line = f"\n\n{memory_block}\n" if memory_block else ""
    summary_line = f"\n{history_summary}\n" if history_summary else ""
    weak_line = f"\n{weak_hints}\n" if weak_hints else ""
    ref_line = (
        f"\n{reference_block}\n"
        "- Facts NOT written in the reference above must not be stated as if they were true. "
        "If you need one, ask about it instead of inventing it.\n"
        if reference_block
        else ""
    )
    max_words = max_reply_words if max_reply_words is not None else 90
    min_words = max(40, max_words - 20)
    guide = LEVEL_GUIDE.get(cefr, LEVEL_GUIDE["B1"])
    return f"""You are playing a character in a role-play conversation with an English learner.
Scenario: {scenario_title}
Current topic: {topic_title}
Learner level: {cefr}. {guide}
{memory_line}{summary_line}{weak_line}{ref_line}
Your job this turn:
- Move the scene toward this beat: "{beat}".
- Use these tenses naturally where the situation calls for them: {', '.join(target_tenses)}. Do not force them.
- If natural, work in one of these words: {', '.join(target_lexis)}.{vocab_line}
- Reply in {min_words}–{max_words} words, one or two short paragraphs. Finish the last sentence and the question — never stop mid-sentence.
- End with one concrete question that keeps the learner talking.
- Stay in character. Never correct the learner's grammar or mention mistakes — that is handled elsewhere.
- Never say you are an AI or a language model.

{STYLE_BANS}

Do not use markdown headings. Plain conversational English only."""


def to_messages(rows: list[dict]) -> list[dict]:
    """把 DB 消息行转成聊天消息：只取最近 10 条，跳过异常 role。

    TS 版把非 assistant 一律当成 user；这里按规范「跳过异常 role」处理，
    避免脏数据（如 system 行）污染对话。
    """
    out: list[dict] = []
    for row in (rows or [])[-10:]:
        role = row.get("role")
        if role not in ("user", "assistant"):
            continue
        out.append({"role": role, "content": row.get("content_md") or ""})
    return out

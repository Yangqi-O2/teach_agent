"""情景与话题规划（planner）。

移植自 `.tmp/etutor-src/api/src/agents/planner.ts`：模型生成 6–10 个话题，
落库到 `english_scenarios` / `english_topics`，返回前端需要的完整 plan。
`llm` 由调用方传入（路由按用户设置取 planner 模型），模块内不做全局取模型。
"""
from __future__ import annotations

import time
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from ..store import execute, json_dump, json_load, new_id, now_iso, one

CEFR_LEVELS: tuple[str, ...] = ("A2", "B1", "B2", "C1")


class TopicSchema(BaseModel):
    """一个话题（对应 TS 的 TopicSchema）。"""

    title: str = Field(min_length=4, max_length=120)
    beats: list[str] = Field(min_length=3, max_length=5)
    target_tenses: list[str] = Field(min_length=1, max_length=3)
    target_lexis: list[str] = Field(min_length=2, max_length=6)
    difficulty: Literal["A2", "B1", "B2", "C1"]

    @field_validator("beats")
    @classmethod
    def _check_beats(cls, value: list[str]) -> list[str]:
        # zod: z.array(z.string().min(3)).min(3).max(5)
        if any(not isinstance(beat, str) or len(beat) < 3 for beat in value):
            raise ValueError("每个 beat 至少 3 个字符")
        return value


class PlanSchema(BaseModel):
    """一次生成的完整情景计划（对应 TS 的 PlanSchema）。"""

    title_zh: str = Field(min_length=2, max_length=60)
    title_en: str = Field(min_length=2, max_length=80)
    slug: str = Field(min_length=2, max_length=40, pattern=r"^[a-z0-9-]+$")
    topics: list[TopicSchema] = Field(min_length=6, max_length=10)


SYSTEM = """你是英语情景对话课程的设计者。根据用户给出的领域，设计一个可长期展开的对话情景。

要求：
1. 情景要具体到"有角色、有冲突、有目标"，不要抽象主题。
2. 生成 6–10 个话题，彼此角度不同，避免换汤不换药。
3. 每个话题给出 3–5 个 beats（对话推进的节拍），用动词开头的短句，如 "open with a delayed shipment"。
4. target_tenses 由场景自然需要决定，不要堆砌：叙事型用 past simple / past perfect；计划型用 future / present continuous；现状型用 present simple / present perfect。
5. target_lexis 是 2–6 个该话题绕不开的词，不要生僻词。
6. difficulty 按话题复杂度给 A2/B1/B2/C1。

只输出 JSON，不要解释，不要 markdown 代码块。字段：
{"title_zh":"...","title_en":"...","slug":"kebab-case","topics":[{"title":"...","beats":["..."],"target_tenses":["..."],"target_lexis":["..."],"difficulty":"B1"}]}"""


async def plan_scenario(domain: str, cefr: str, llm) -> dict:
    """生成情景 + 话题并落库，返回 {id, slug, title_zh, title_en, topics, provider}。"""
    plan = await llm.json(
        system=SYSTEM,
        user=f"领域：{domain}\n学习者目标水平：{cefr}",
        schema=PlanSchema,
        max_tokens=1600,
    )
    if not isinstance(plan, PlanSchema):
        plan = PlanSchema.model_validate(plan)

    slug = _unique_slug(plan.slug)
    scenario_id = new_id()
    created_at = now_iso()
    execute(
        """INSERT INTO english_scenarios (id, slug, title_zh, title_en, domain, cefr, created_at)
           VALUES (:id, :slug, :title_zh, :title_en, :domain, :cefr, :created_at)""",
        id=scenario_id,
        slug=slug,
        title_zh=plan.title_zh,
        title_en=plan.title_en,
        domain=domain,
        cefr=cefr,
        created_at=created_at,
    )
    for topic in plan.topics:
        execute(
            """INSERT INTO english_topics
                   (id, scenario_id, title, beats, target_tenses, target_lexis, difficulty, created_at)
               VALUES (:id, :scenario_id, :title, :beats, :target_tenses, :target_lexis,
                       :difficulty, :created_at)""",
            id=new_id(),
            scenario_id=scenario_id,
            title=topic.title,
            beats=json_dump(list(topic.beats)),
            target_tenses=json_dump(list(topic.target_tenses)),
            target_lexis=json_dump(list(topic.target_lexis)),
            difficulty=topic.difficulty,
            created_at=created_at,
        )

    return {
        "id": scenario_id,
        "slug": slug,
        "title_zh": plan.title_zh,
        "title_en": plan.title_en,
        "topics": [topic.model_dump() for topic in plan.topics],
        "provider": str(getattr(llm, "name", "") or "unknown"),
    }


def pick_topic(scenario_id: str) -> dict | None:
    """取当前情景下使用次数最少的话题，保证同一情景不重复同一角度。"""
    row = one(
        """SELECT id, title, beats, target_tenses, target_lexis, difficulty
             FROM english_topics
            WHERE scenario_id = :scenario_id
            ORDER BY used_count ASC, last_used_at ASC NULLS FIRST
            LIMIT 1""",
        scenario_id=scenario_id,
    )
    if not row:
        return None
    row["beats"] = json_load(row.get("beats"), []) or []
    row["target_tenses"] = json_load(row.get("target_tenses"), []) or []
    row["target_lexis"] = json_load(row.get("target_lexis"), []) or []
    return row


# ---------------------------------------------------------------- 内部工具


def _unique_slug(base: str) -> str:
    """slug 冲突时依次追加 -2、-3……；20 次仍冲突则加毫秒级 base36 后缀（照搬 TS）。"""
    slug = base
    for index in range(20):
        hit = one("SELECT 1 AS hit FROM english_scenarios WHERE slug = :slug", slug=slug)
        if not hit:
            return slug
        slug = f"{base}-{index + 2}"
    return f"{base}-{_base36(int(time.time() * 1000))}"


def _base36(value: int) -> str:
    """等价 JS `Number.prototype.toString(36)`。"""
    digits = "0123456789abcdefghijklmnopqrstuvwxyz"
    if value == 0:
        return "0"
    out = ""
    while value > 0:
        value, remainder = divmod(value, 36)
        out = digits[remainder] + out
    return out

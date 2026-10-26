"""生词释义。

移植自 `.tmp/etutor-src/api/src/agents/gloss.ts`。词库里只有单词和上下文句，
学生复习时仍然不知道它什么意思——这是真实的体验缺口。用同一个模型批量生成，
失败就不阻塞存词（调用方拿到 None 时前端显示「—」）。
"""
from __future__ import annotations

import logging

from pydantic import BaseModel, Field

log = logging.getLogger(__name__)

SYSTEM = """你在为一个中国英语学习者写单词卡片。给出该词在给定句子中的含义。

要求：
1. gloss_zh：中文释义，20 字以内，先说词义，必要时括号补充语境义。
2. pos：词性缩写（n./v./adj./adv./prep./phr.）。
3. 不要音标、不要例句、不要解释词源。

只输出一个 JSON 对象，字段为 gloss_zh 与 pos。"""


class GlossSchema(BaseModel):
    """模型返回的结构化释义（字段名沿用 TS 版 JSON：gloss_zh / pos）。"""

    gloss_zh: str = Field(min_length=1, max_length=60)
    pos: str = Field(min_length=1, max_length=12)


async def gloss_word(word: str, context: str, llm) -> dict | None:
    """生成释义。离线 mock 或调用失败都返回 None（不编造释义，不阻塞存词）。"""
    if getattr(llm, "mock", False):
        # 无 Key 时不编造释义，返回 null，前端显示「—」
        return None
    try:
        out = await llm.json(
            system=SYSTEM,
            user=f"单词：{word}\n句子：{(context or '')[:200]}",
            schema=GlossSchema,
            max_tokens=200,
        )
        if not isinstance(out, GlossSchema):
            out = GlossSchema.model_validate(out)
        return {"glossZh": out.gloss_zh.strip(), "pos": out.pos.strip()}
    except Exception as exc:  # noqa: BLE001 - 释义失败不阻塞存词
        log.warning("gloss.failed word=%s: %s", word, exc)
        return None

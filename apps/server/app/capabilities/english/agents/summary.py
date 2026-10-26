"""L2 情节摘要。

目标不是「压缩文本」，而是**保住会丢的东西**：数字、承诺、分歧、已完成的推进。
所以提示词里明确要求保留具体信息、丢弃寒暄。

照搬 etutor-cn `api/src/agents/summary.ts`：

- 每 8 条消息（4 轮）压一次，且至少要有 12 条历史才值得压；
- 模型失败/超时时由 router 用 `fallback_summary` 兜底（不抛错）；
- 注入 partner 时写明「这是 0 条之前的历史」。
"""
from __future__ import annotations

import asyncio
import re
from typing import Any

SUMMARY_MAX_CHARS = 700

# 一次最多压这么多条（与 routes.ts 的 LIMIT 8 一致）
BATCH = 8

_SYSTEM = """你把一段英语角色扮演对话压缩成"后续对话必须遵守的纪要"。

规则：
1. 保留所有具体信息：金额、时间、数量、人名、地点、承诺、待办。
2. 保留尚未解决的分歧。
3. 丢弃寒暄、语气词、重复内容。
4. 用第三人称陈述，不写"我""你"。
5. 不超过 150 个英文单词，纯文本，不要列表符号，不要标题。

只输出纪要正文。"""


def _content(turn: Any) -> str:
    if isinstance(turn, dict):
        return str(turn.get("content_md") or turn.get("content") or "")
    return str(getattr(turn, "content_md", "") or getattr(turn, "content", "") or "")


def _role(turn: Any) -> str:
    if isinstance(turn, dict):
        return str(turn.get("role") or "user")
    return str(getattr(turn, "role", "user") or "user")


def should_summarize(total_messages: int, summarized_upto: int) -> bool:
    """至少 12 条历史、且未摘要的已攒够 8 条，才值得压一次。"""
    unsummarized = int(total_messages) - int(summarized_upto)
    return int(total_messages) >= 12 and unsummarized >= BATCH


def fallback_summary(turns: list[dict] | list[Any]) -> str:
    """mock / 降级用：把旧消息压成可读的骨架，不调用模型。"""
    lines: list[str] = []
    for turn in turns:
        who = "AI" if _role(turn) == "assistant" else "Learner"
        text = re.sub(r"\s+", " ", _content(turn)).strip()[:120]
        lines.append(f"{who}: {text}")
    return "\n".join(lines)[:SUMMARY_MAX_CHARS]


async def summarize_with(llm, turns: list[dict] | list[Any], timeout: float = 30.0) -> str:
    """用模型压纪要；超时/失败抛异常，由调用方用 fallback 兜底。"""
    transcript = "\n".join(
        f"{'AI' if _role(turn) == 'assistant' else 'Learner'}: {_content(turn)}" for turn in turns
    )

    async def collect() -> str:
        parts: list[str] = []
        async for delta in llm.stream(
            _SYSTEM,
            [{"role": "user", "content": transcript[-6000:]}],
            max_tokens=900,
        ):
            parts.append(delta)
        return "".join(parts).strip()[:SUMMARY_MAX_CHARS]

    return await asyncio.wait_for(collect(), timeout=timeout)


def render_summary(summary: str | None, covered_messages: int) -> str:
    """注入 partner 的文本块。"""
    if not summary or not summary.strip():
        return ""
    return (
        f"Earlier in this same conversation ({covered_messages} messages ago), summarised — "
        f"treat it as already established:\n{summary.strip()}"
    )

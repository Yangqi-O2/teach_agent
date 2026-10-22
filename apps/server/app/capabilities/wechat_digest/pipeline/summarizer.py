"""总结编排：分块 / Map-Reduce / 调用 LLM / 解析结构化结果。

流程（按群）：

1. 清洗后的消息按 token 预算分块（``chunk_messages``）；
2. 单块：一次 ``chat``；多块：先逐块总结（Map），再合并去重（Reduce）；
3. 用 ``----JSON----`` 分离「结构化文本」与「JSON 日程」；
4. 健壮提取 JSON；解析失败降级为纯文本总结（不抛错，契约 §4.2）。

只依赖 provider 的 ``chat()``，换模型 / 换供应商不影响管道。
"""
from __future__ import annotations

import json
import logging
import re
from typing import TYPE_CHECKING, Any

from ..sources.base import Message
from .prompts import JSON_MARK, build_merge_prompt, build_prompt

if TYPE_CHECKING:  # pragma: no cover - 仅类型提示，避免运行时依赖
    from ....core.llm import LLMClient

log = logging.getLogger(__name__)

# 单块 token 预算（保守；DeepSeek 等上下文很大，但保守更稳）
CHUNK_TOKEN_BUDGET = 12000

_TEMPERATURE = 0.3


def estimate_tokens(text: str) -> int:
    """粗略估算 token：中文 1 字≈1 token，ASCII 每 4 字符≈1 token。"""
    if not text:
        return 0
    cjk = len(re.findall(r"[\u4e00-\u9fff]", text))
    ascii_ = len(re.sub(r"[\u4e00-\u9fff]", "", text))
    return cjk + ascii_ // 4


def format_messages(messages: list[Message]) -> str:
    """把消息格式化成喂给模型的多行文本。"""
    return "\n".join(m.to_ai_line() for m in messages)


def chunk_messages(messages: list[Message], budget: int = CHUNK_TOKEN_BUDGET) -> list[list[Message]]:
    """按 token 预算贪心分块，保持时间顺序；单条超预算时独占一块。"""
    budget = max(200, int(budget or CHUNK_TOKEN_BUDGET))
    chunks: list[list[Message]] = []
    cur: list[Message] = []
    cur_tokens = 0
    for msg in messages:
        cost = max(1, estimate_tokens(msg.to_ai_line()))
        if cur and cur_tokens + cost > budget:
            chunks.append(cur)
            cur, cur_tokens = [], 0
        cur.append(msg)
        cur_tokens += cost
    if cur:
        chunks.append(cur)
    return chunks


def count_chunks(messages: list[Message], budget: int = CHUNK_TOKEN_BUDGET) -> int:
    """预估分块数量（不需要真的分块时用）。"""
    return len(chunk_messages(messages, budget))


async def _chat(client: "LLMClient", system: str, user: str) -> str:
    resp = await client.chat(
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        temperature=_TEMPERATURE,
    )
    return str((resp or {}).get("content") or "").strip()


async def summarize_group_raw(
    client: "LLMClient",
    group_name: str,
    messages: list[Message],
    style: str = "general",
    budget: int = CHUNK_TOKEN_BUDGET,
) -> tuple[str, int]:
    """总结单个群，返回 ``(模型原始输出, 分块数)``（含 Map-Reduce）。"""
    if not messages:
        return "", 0

    chunks = chunk_messages(messages, budget)
    system, _ = build_prompt(group_name, "", len(messages), style)

    if len(chunks) == 1:
        _, user = build_prompt(group_name, format_messages(chunks[0]), len(messages), style)
        return await _chat(client, system, user), 1

    # Map：各块先独立总结
    partials: list[str] = []
    for i, chunk in enumerate(chunks, 1):
        _, user = build_prompt(group_name, format_messages(chunk), len(chunk), style)
        partial = await _chat(client, system, user)
        partials.append(f"【分段 {i}/{len(chunks)}】\n{partial}")
        log.debug("群 %s 分段 %d/%d 总结完成", group_name, i, len(chunks))

    # Reduce：合并去重
    merge_system, merge_user = build_merge_prompt(group_name, partials, len(messages), style)
    return await _chat(client, merge_system, merge_user), len(chunks)


def extract_json(text: str) -> dict:
    """尽力从模型输出里提取 JSON 对象，失败返回 ``{}``。

    兼容：````` ```json ... ``` ````` 代码围栏、JSON 前后的解释性污染文本、
    以及整体就是纯 JSON 的情况。
    """
    if not text or not text.strip():
        return {}
    raw = text.strip()

    candidates: list[str] = []
    # 1) 代码围栏里的内容优先
    for match in re.finditer(r"```(?:json|JSON)?\s*(.*?)```", raw, flags=re.DOTALL):
        body = match.group(1).strip()
        if body:
            candidates.append(body)
    # 2) 原文整体
    candidates.append(raw)

    for cand in candidates:
        try:
            data = json.loads(cand)
            if isinstance(data, dict):
                return data
        except (json.JSONDecodeError, TypeError):
            pass
        # 3) 截取第一个 { 到最后一个 } 再试
        start, end = cand.find("{"), cand.rfind("}")
        if start != -1 and end > start:
            snippet = cand[start : end + 1]
            try:
                data = json.loads(snippet)
                if isinstance(data, dict):
                    return data
            except (json.JSONDecodeError, TypeError):
                continue
    return {}


def _normalize_schedules(raw_schedules: Any, group_name: str) -> list[dict]:
    schedules: list[dict] = []
    if not isinstance(raw_schedules, list):
        return schedules
    for item in raw_schedules:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or "").strip()
        datetime_ = str(item.get("datetime") or item.get("time") or "").strip()
        note = str(item.get("note") or "").strip()
        if not (title or datetime_):
            continue
        schedules.append(
            {
                "title": title or "未命名事项",
                "datetime": datetime_,
                "note": note,
                "done": bool(item.get("done", False)),
                "source_sender": str(item.get("source_sender") or "").strip(),
            }
        )
    return schedules


def _fallback_one_line(structured_text: str) -> str:
    """从结构化文本里兜底抽一句话。"""
    m = re.search(r"【一句话】[：:]?\s*(.+)", structured_text)
    if m:
        return m.group(1).strip()
    for line in structured_text.splitlines():
        line = line.strip().strip("#").strip()
        if line and line not in ("【结构化总结】", "【总结】"):
            return line[:100]
    return ""


def parse_response(group_name: str, raw: str, message_count: int = 0) -> dict:
    """解析模型输出为 ``DigestPayload.groups[i]`` 结构（契约 §4.2）。

    解析失败时降级：``one_line`` 用文本兜底、``items=[]``、``schedules=[]``、
    ``structured_text`` 保留原文，绝不抛错。
    """
    raw = (raw or "").strip()
    structured_text = raw
    json_part: str | None = None
    if JSON_MARK in raw:
        head, tail = raw.split(JSON_MARK, 1)
        structured_text = head.strip()
        json_part = tail.strip()
        # JSON 标记前后可能还有围栏/解释，统一交给 extract_json

    data = extract_json(json_part if json_part else raw)

    one_line = str(data.get("one_line") or "").strip()
    items_raw = data.get("items") or []
    items = [str(x).strip() for x in items_raw if str(x).strip()] if isinstance(items_raw, list) else []
    schedules = _normalize_schedules(data.get("schedules"), group_name)

    # 只有 JSON 标记、第一部分为空时，把 JSON 之前的原文都算结构化文本
    if not structured_text:
        structured_text = one_line

    if not one_line and structured_text:
        one_line = _fallback_one_line(structured_text)
    if not one_line:
        one_line = "模型没有返回可读的总结"

    return {
        "name": group_name,
        "message_count": int(message_count or 0),
        "one_line": one_line,
        "items": items,
        "schedules": schedules,
        "structured_text": structured_text or one_line,
    }


async def summarize_group(
    client: "LLMClient",
    group_name: str,
    messages: list[Message],
    style: str = "general",
    budget: int = CHUNK_TOKEN_BUDGET,
) -> tuple[dict, int]:
    """总结单个群并解析：``(group_payload, 分块数)``。"""
    if not messages:
        return parse_response(group_name, "", 0), 0
    raw, chunks = await summarize_group_raw(client, group_name, messages, style, budget)
    return parse_response(group_name, raw, len(messages)), chunks


async def summarize_groups(
    client: "LLMClient",
    by_group: dict[str, list[Message]],
    style: str = "general",
    budget: int = CHUNK_TOKEN_BUDGET,
    on_group: Any = None,
) -> tuple[list[dict], int]:
    """按群总结全部消息，返回 ``(groups_payload, 分块总数)``。

    ``on_group(i, total, group_name)`` 可选回调，用于任务进度。
    """
    groups: list[dict] = []
    total_chunks = 0
    items = [(name, msgs) for name, msgs in by_group.items()]
    total = len(items)
    for i, (name, msgs) in enumerate(items, 1):
        if on_group is not None:
            on_group(i, total, name)
        group_payload, chunks = await summarize_group(client, name, msgs, style, budget)
        total_chunks += chunks
        groups.append(group_payload)
    return groups, total_chunks

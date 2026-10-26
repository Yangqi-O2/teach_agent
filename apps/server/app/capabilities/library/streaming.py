"""SSE 编码与下行合并（教材库自带一份）。

为什么不复用 english 的那份：能力之间不互相 import 是这套框架的前提，否则禁用、
替换任何一个能力都会牵连另一个。这 40 行重复是有意的。
"""
from __future__ import annotations

import json
import time
from collections.abc import AsyncIterator
from typing import Any

SSE_HEADERS: dict[str, str] = {
    "Content-Type": "text/event-stream; charset=utf-8",
    "Cache-Control": "no-cache, no-transform",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",  # nginx 关缓冲，否则流式会退化成一次性输出
}


def sse(event: str, data: Any) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


async def iter_coalesced(
    source: AsyncIterator[str], *, interval: float = 0.05, max_bytes: int = 1024
) -> AsyncIterator[str]:
    """把上游 token 合并成 ≤20 帧/秒、≤1KB/帧；首帧立即产出，不压延迟。"""
    buffer = ""
    first = True
    last_emit = time.monotonic()
    async for delta in source:
        if not delta:
            continue
        buffer += delta
        if first:
            first = False
            last_emit = time.monotonic()
            chunk, buffer = buffer, ""
            yield chunk
            continue
        if len(buffer.encode("utf-8")) >= max_bytes or (time.monotonic() - last_emit) >= interval:
            last_emit = time.monotonic()
            chunk, buffer = buffer, ""
            yield chunk
    if buffer:
        yield buffer

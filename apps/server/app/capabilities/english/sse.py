"""SSE 编码与下行合并。

两个移植要点（来自原项目踩过的坑）：
1. SSE 事件以 `\\n\\n` 分帧，不要把每个 token 直接写出去——模型 token 密集时会打爆前端；
2. 首帧必须立刻发：合并器最多压 50ms，这 50ms 会整个加在首字延迟上，不值得。
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
    "X-Accel-Buffering": "no",  # nginx 关闭缓冲，否则流式会变成一次性输出
}


def sse(event: str, data: Any) -> str:
    """把一个事件编码成 SSE 帧。"""
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


async def iter_coalesced(
    source: AsyncIterator[str], *, interval: float = 0.05, max_bytes: int = 1024
) -> AsyncIterator[str]:
    """把上游 token 流合并成 ≤20 帧/秒、≤1KB/帧的下行分片；首帧立即产出。"""
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

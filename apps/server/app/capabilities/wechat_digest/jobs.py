"""群聊简报后台任务：解析 → 清洗 → Map-Reduce 总结 → 落库。

由 ``core.jobs.JobManager`` 在线程池里执行；内部用 ``asyncio.run`` 调
``LLMClient.chat``（异步），不新建任何 HTTP 客户端，也不读环境变量。

进度阶段（契约 §3.4）：

====  ====
5     解析聊天记录
15    清洗降噪
20→80 总结第 i/n 个群
88    解析结构化结果
95    保存简报
100   已完成（由 JobManager 统一写入）
====  ====
"""
from __future__ import annotations

import asyncio
import logging

from sqlmodel import Session

from ...core.errors import ApiError
from ...core.jobs import JobCancelled, JobContext
from ...core.llm import LLMClient, load_provider
from ...db import engine
from . import service
from .models import Digest
from .pipeline import summarizer

log = logging.getLogger(__name__)

JOB_TYPE = service.JOB_TYPE

# 单次 LLM 调用超时（秒）。分块多时整体耗时会更长，这里只约束单次。
LLM_TIMEOUT = 120.0


def _friendly_error(exc: Exception) -> str:
    if isinstance(exc, ApiError):
        return exc.message
    text = str(exc).strip()
    return text or exc.__class__.__name__


async def _summarize(
    client: LLMClient,
    ctx: JobContext,
    prepared: service.Prepared,
    style: str,
) -> tuple[list[dict], int]:
    """按群总结并汇报进度；返回 ``(groups_payload, 分块总数)``。"""
    groups: list[dict] = []
    total_chunks = 0
    items = list(prepared.cleaned.items())
    total = len(items)
    for i, (name, messages) in enumerate(items, 1):
        # 20 → 80 之间按群推进；progress() 内部会检查取消
        pct = 20 + int(60 * i / total)
        ctx.progress(min(pct, 80), f"总结第 {i}/{total} 个群")
        raw, chunks = await summarizer.summarize_group_raw(client, name, messages, style)
        total_chunks += chunks
        groups.append(summarizer.parse_response(name, raw, len(messages)))
    # 全部群总结完再进入「解析结构化结果」，避免 n>1 时进度回退（88 → 80）
    ctx.progress(88, "解析结构化结果")
    return groups, total_chunks


def run_digest_job(ctx: JobContext, payload: dict) -> dict:
    """任务入口（同步函数，跑在线程池）。"""
    digest_id = int(payload.get("digest_id") or 0)
    if not digest_id:
        raise ValueError("任务参数缺少 digest_id")

    # 1. 首次进入：置 running（顺带确认记录还在，可能已被用户删掉）
    with Session(engine) as session:
        digest = session.get(Digest, digest_id)
        if digest is None:
            raise ValueError("简报记录不存在，可能已被删除")
        digest.status = "running"
        digest.error = None
        digest.updated_at = service.now_iso()
        session.add(digest)
        session.commit()

    try:
        source_id = str(payload.get("source") or "paste")
        params = payload.get("params") or {}
        style = str(payload.get("style") or "") or "general"
        provider_id = payload.get("provider_id")

        # 2. 解析（核心异常会转成 ApiError，message 是给用户看的文案）
        ctx.progress(5, "解析聊天记录")
        with Session(engine) as session:
            settings = service.load_settings(session)
        prepared = service.prepare(source_id, params, settings["max_chars"])

        # 3. 清洗（prepare 内部已完成，这里只更新进度）
        ctx.progress(15, "清洗降噪")

        # 4. 取模型配置（没有供应商 / 没有 Key 会在 load_provider 抛 409 ApiError）
        with Session(engine) as session:
            runtime = load_provider(session, provider_id)
        client = LLMClient(runtime, timeout=LLM_TIMEOUT)

        # 5. Map-Reduce 总结
        groups, chunks = asyncio.run(_summarize(client, ctx, prepared, style))

        # 6. 组装 DigestPayload 并保存
        digest_payload = service.build_payload(
            source=prepared.source,
            group_name=prepared.group_name,
            style=style,
            provider=runtime.name,
            model=runtime.chat_model,
            stats_before=prepared.total_before,
            stats_after=total_kept(groups, prepared),
            chunks=chunks,
            groups=groups,
        )
        ctx.progress(95, "保存简报")
        with Session(engine) as session:
            service.save_payload(session, digest_id, digest_payload)

        one_line = ""
        if groups:
            one_line = str(groups[0].get("one_line") or "")
        log.info("群聊简报生成完成: digest=%s groups=%d chunks=%d", digest_id, len(groups), chunks)
        return {"digest_id": digest_id, "one_line": one_line, "stats": digest_payload["stats"]}
    except JobCancelled:
        # 取消：把简报置 cancelled，然后继续抛给 JobManager 记录任务状态
        with Session(engine) as session:
            service.set_digest_status(session, digest_id, "cancelled", error="任务已取消")
        log.info("群聊简报已取消: digest=%s", digest_id)
        raise
    except Exception as exc:  # noqa: BLE001 - 任何失败都要落库，前端才看得到原因
        log.exception("群聊简报生成失败: digest=%s", digest_id)
        with Session(engine) as session:
            service.set_digest_status(session, digest_id, "error", error=_friendly_error(exc))
        raise


def total_kept(groups: list[dict], prepared: service.Prepared) -> int:
    """清洗后保留条数：优先按群 payload 求和（与预览口径一致）。"""
    total = sum(int(g.get("message_count") or 0) for g in groups)
    return total or prepared.total_after

"""群聊简报能力：manifest / 路由 / 迁移 / Agent 工具 / 后台任务注册。

实现契约：``docs/WECHAT-DIGEST.md``。
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from sqlmodel import Session, col, select

from ...core.capability import Capability, CapabilityManifest, NavItem
from ...core.jobs import jobs as job_manager
from ...core.llm import LLMClient, load_provider
from ...core.tools import Tool, ToolContext
from ...db import engine
from . import service
from .jobs import JOB_TYPE, LLM_TIMEOUT, _friendly_error, run_digest_job
from .models import Digest
from .pipeline.prompts import STYLES
from .pipeline.summarizer import summarize_groups
from .router import router
from .sources import list_sources

log = logging.getLogger(__name__)

_job_registered = False


# ---------------------------------------------------------------- Agent 工具


async def _tool_summarize_group_chat(
    ctx: ToolContext,
    text: str = "",
    group_name: str = "",
    style: str = "",
) -> dict:
    """同步跑完整管道并入库：解析 → 清洗 → LLM 总结 → 保存（契约 §7）。"""
    text = (text or "").strip()
    if not text:
        raise ValueError("聊天记录为空，请传入 text 参数")
    if not ctx.user_id:
        raise ValueError("缺少用户上下文")
    params = {"text": text, "group_name": (group_name or "").strip() or "粘贴内容"}

    with Session(engine) as session:
        settings = service.load_settings(session, ctx.user_id)
        prepared = service.prepare("paste", params, settings["max_chars"])
        chosen_style = (style or "").strip() or settings["default_style"]
        if chosen_style not in STYLES:
            chosen_style = settings["default_style"]
        runtime = load_provider(session, None, ctx.user_id)
        digest = service.create_digest(
            session,
            prepared=prepared,
            style=chosen_style,
            runtime=runtime,
            user_id=ctx.user_id,
        )
        digest_id = int(digest.id or 0)

    # digest 记录已建好：后续任何失败都要把状态置为 error，不能让它永远停在 queued。
    try:
        client = LLMClient(runtime, timeout=LLM_TIMEOUT)
        groups, chunks = await summarize_groups(client, prepared.cleaned, chosen_style)
        payload = service.build_payload(
            source=prepared.source,
            group_name=prepared.group_name,
            style=chosen_style,
            provider=runtime.name,
            model=runtime.chat_model,
            stats_before=prepared.total_before,
            stats_after=sum(int(g.get("message_count") or 0) for g in groups)
            or prepared.total_after,
            chunks=chunks,
            groups=groups,
        )
        with Session(engine) as session:
            saved = service.save_payload(session, digest_id, payload)
            if not saved:
                raise RuntimeError("保存简报失败：记录可能已被删除")
            # 与 jobs.py 一致：成功入库后按 history_limit 清理最早的历史
            service.trim_history(
                session,
                service.load_settings(session, ctx.user_id)["history_limit"],
                keep_id=digest_id,
                user_id=ctx.user_id,
            )
    except Exception as exc:  # noqa: BLE001 - 失败落库后重新抛出，工具层返回 {"ok": false}
        log.exception("工具 summarize_group_chat 失败: digest=%s", digest_id)
        with Session(engine) as session:
            service.set_digest_status(session, digest_id, "error", error=_friendly_error(exc))
        raise

    one_line = str(groups[0].get("one_line") or "") if groups else ""
    return {
        "digest_id": digest_id,
        "one_line": one_line,
        "stats": payload["stats"],
        "groups": [
            {
                "name": group.get("name"),
                "one_line": group.get("one_line"),
                "items": group.get("items") or [],
                "schedules": group.get("schedules") or [],
            }
            for group in groups
        ],
    }


def _tool_list_group_digests(ctx: ToolContext, limit: int = 10) -> list[dict]:
    """最近的简报摘要列表（契约 §7）。"""
    try:
        limit = max(1, min(int(limit or 10), 100))
    except (TypeError, ValueError):
        limit = 10
    with Session(engine) as session:
        rows = session.exec(
            select(Digest)
            .where(Digest.user_id == ctx.user_id)
            .order_by(col(Digest.created_at).desc(), col(Digest.id).desc())
            .limit(limit)
        ).all()
        return [service.summary_of(row) for row in rows]


class WechatDigestCapability(Capability):
    manifest = CapabilityManifest(
        id="wechat_digest",
        name="群聊简报",
        description="粘贴群聊记录 → 清洗降噪 → 结构化总结 / 待办 / 日程，可导出 TXT、MD、ICS、JSON。",
        icon="message-square",
        nav=NavItem(label="群聊简报", path="/cap/wechat-digest", order=20),
        version="0.1.0",
        status="beta",
        settings_schema={
            "type": "object",
            "properties": {
                "default_style": {
                    "type": "string",
                    "title": "默认总结风格",
                    "enum": ["general", "course", "club"],
                    "default": "general",
                },
                "max_chars": {
                    "type": "integer",
                    "title": "单次粘贴上限（字符）",
                    "default": 60000,
                    "description": "超过会拒绝，避免一次塞进太多内容",
                },
                "history_limit": {
                    "type": "integer",
                    "title": "最多保留历史条数",
                    "default": 30,
                    "description": "超出后自动清理最早的简报",
                },
            },
        },
    )

    def router(self):
        return router

    def migrations_dir(self) -> Path:
        return Path(__file__).resolve().parent / "migrations"

    def tools(self) -> list[Tool]:
        return [
            Tool(
                name="summarize_group_chat",
                description=(
                    "把一段粘贴的群聊记录整理成群聊简报：先清洗降噪，再总结出一句话、"
                    "重要事项、待办和日程，并保存到「群聊简报」。"
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "text": {
                            "type": "string",
                            "description": "聊天记录原文，支持 [时间] 昵称: 内容、微信/QQ 复制格式、纯「昵称: 内容」",
                        },
                        "group_name": {"type": "string", "description": "会话 / 群名，可省略"},
                        "style": {
                            "type": "string",
                            "description": "总结风格：general 通用 / course 课程 / club 社团，可省略",
                            "enum": ["general", "course", "club"],
                        },
                    },
                    "required": ["text"],
                },
                handler=_tool_summarize_group_chat,
            ),
            Tool(
                name="list_group_digests",
                description="列出最近生成的群聊简报（标题、一句话、状态、生成时间）。",
                parameters={
                    "type": "object",
                    "properties": {
                        "limit": {
                            "type": "integer",
                            "description": "返回条数，默认 10，最多 100",
                            "default": 10,
                        }
                    },
                },
                handler=_tool_list_group_digests,
            ),
        ]

    async def on_startup(self, app: Any) -> None:  # noqa: ARG002
        """注册后台任务类型（幂等：重复触发只注册一次）。"""
        global _job_registered
        if _job_registered:
            return
        job_manager.register(JOB_TYPE, run_digest_job)
        _job_registered = True
        log.info("群聊简报任务处理器已注册: %s", JOB_TYPE)
        # 触发数据源注册（sources/__init__.py 在 import 时已完成，这里再兜底一次）
        log.debug("当前数据源: %s", [source["id"] for source in list_sources()])


CAPABILITY = WechatDigestCapability()

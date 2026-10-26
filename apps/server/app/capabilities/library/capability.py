"""教材库能力：上传 / 分类 / 解析（含扫描件 OCR）/ 基于指定教材的问答。

这个能力把原先的骨架（parsers / chunking / models）接成了完整闭环：
- `capability.py` 让它被内核发现（此前没有这个文件，迁移从未执行过）；
- `service.py` 负责解析与索引，`ocr.py` 负责扫描件；
- `retrieval.py` 负责混合检索，`qa.py` 负责「只用教材回答 + 回验引用」。
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from fastapi import APIRouter

from ...core.capability import Capability, CapabilityManifest, NavItem
from ...core.jobs import jobs
from ...core.tools import Tool, ToolContext
from .settings import DEFAULTS

log = logging.getLogger(__name__)


# ---------------------------------------------------------------- Agent 工具


async def _search(ctx: ToolContext, query: str = "", document_ids: str = "", limit: int = 6) -> dict:
    """在用户可见（或指定）的教材里检索原文段落。"""
    from . import retrieval

    if not ctx.user_id:
        raise ValueError("缺少用户上下文")
    if not (query or "").strip():
        raise ValueError("query 不能为空")
    scope = [int(item) for item in str(document_ids).replace("，", ",").split(",") if item.strip().isdigit()]
    result = await retrieval.search(
        ctx.user_id,
        query,
        document_ids=scope or None,
        limit=max(1, min(int(limit or 6), 12)),
    )
    return {
        "mode": result.mode,
        "note": result.note,
        "hits": [
            {
                "index": index,
                "document_title": hit.document_title,
                "loc_label": hit.loc_label,
                "heading_path": hit.heading_path,
                "text": hit.text[:1200],
                "score": round(hit.score, 4),
            }
            for index, hit in enumerate(result.hits, 1)
        ],
    }


async def _list_documents(ctx: ToolContext) -> dict:
    """列出当前用户能看到的教材（含解析状态）。"""
    from . import store

    if not ctx.user_id:
        raise ValueError("缺少用户上下文")
    rows = store.q(
        "SELECT id, title, kind, status, chunk_count, visibility, parse_warning "
        f"FROM documents WHERE {store.scope_sql()} ORDER BY created_at DESC LIMIT 50",
        uid=ctx.user_id,
    )
    return {"items": rows, "total": len(rows)}


# ---------------------------------------------------------------- 任务注册


def register_jobs() -> None:
    from . import service

    def _handler(ctx: Any, payload: dict) -> dict:
        from . import retrieval, service

        document_id = int(payload["document_id"])
        try:
            return service.ingest_document(
                document_id=document_id,
                user_id=ctx.user_id,
                ocr_mode=str(payload.get("ocr_mode") or "auto"),
                ctx=ctx,
            )
        except Exception as exc:
            # ingest_document 内部已经尽量写状态；这里兜住「非预期异常」，
            # 保证文档不会卡在 queued 让前端一直转圈。
            retrieval.delete_chunks(document_id)
            service.mark_failed(document_id, f"解析异常：{exc}")
            raise

    jobs.register("library.ingest", _handler)


class LibraryCapability(Capability):
    manifest = CapabilityManifest(
        id="library",
        name="教材库",
        description=(
            "上传 PDF / EPUB / DOCX / TXT 等教材并按课程分类；扫描版 PDF 自动 OCR 成可检索文本。"
            "选定一本教材提问，AI 只用这本书的内容作答，并逐条给出页码/章节出处。"
        ),
        icon="library",
        nav=NavItem(label="教材库", path="/cap/library", order=15),
        version="0.1.0",
        status="stable",
        settings_schema={
            "type": "object",
            "properties": {
                "default_visibility": {
                    "type": "string",
                    "enum": ["private", "shared"],
                    "title": "上传默认可见性",
                    "description": "private 仅自己可见；shared 所有成员可读（只有你能改删）",
                    "default": DEFAULTS["default_visibility"],
                },
                "ocr_mode": {
                    "type": "string",
                    "enum": ["off", "auto", "force"],
                    "title": "OCR 策略",
                    "description": "auto 只对没有文本层的页做 OCR；force 全部重跑；off 关闭",
                    "default": DEFAULTS["ocr_mode"],
                },
                "qa_top_k": {
                    "type": "integer",
                    "title": "问答检索段数",
                    "description": "每次提问从教材里取几段作为依据，越大越全但更慢更贵",
                    "default": DEFAULTS["qa_top_k"],
                },
                "max_upload_mb": {
                    "type": "integer",
                    "title": "单文件上限（MB）",
                    "description": "超过这个大小的教材会被拒绝",
                    "default": DEFAULTS["max_upload_mb"],
                },
                "low_confidence_warn": {
                    "type": "number",
                    "title": "OCR 置信度告警阈值",
                    "description": "低于该值会在教材详情里提示「请核对原文」",
                    "default": DEFAULTS["low_confidence_warn"],
                },
            },
        },
    )

    def router(self) -> APIRouter | None:
        try:
            from .router import router as library_router
        except Exception:  # noqa: BLE001 - 坏插件不该拖垮主站
            log.exception("library 路由加载失败（能力暂时不可用）")
            return None
        return library_router

    def migrations_dir(self) -> Path:
        return Path(__file__).resolve().parent / "migrations"

    def tools(self) -> list[Tool]:
        return [
            Tool(
                name="library_search",
                description="在用户的教材里检索原文段落（带教材名与页码），适合回答「书上怎么说的」这类问题。",
                parameters={
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "检索词或问题"},
                        "document_ids": {
                            "type": "string",
                            "description": "逗号分隔的教材 id，留空表示在所有可见教材里找",
                        },
                        "limit": {"type": "integer", "description": "返回几段，默认 6"},
                    },
                    "required": ["query"],
                },
                handler=_search,
            ),
            Tool(
                name="library_list_documents",
                description="列出用户能看到的教材及其解析状态，用于确认「教材传没传、解析好没好」。",
                parameters={"type": "object", "properties": {}},
                handler=_list_documents,
            ),
        ]

    async def on_startup(self, app: Any) -> None:  # noqa: ARG002
        register_jobs()


CAPABILITY = LibraryCapability()
register_jobs()

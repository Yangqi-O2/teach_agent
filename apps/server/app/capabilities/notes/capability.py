"""速记能力：框架演示 + 真实可用。

它同时展示了接入一个能力需要的全部东西：
- manifest（导航、图标、设置项 Schema）
- 自己的路由（挂到 /api/c/notes）
- 自己的数据库迁移
- 暴露给 Agent 的工具（create_note）
- 读取自己的能力设置
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from sqlmodel import Session

from ...core.capability import Capability, CapabilityManifest, NavItem
from ...core.tools import Tool, ToolContext
from ...db import engine
from ...models import CapabilityState
from .router import router


async def _create_note(ctx: ToolContext, title: str = "", content: str = "", tags: str = "") -> dict:
    from .models import Note

    title = (title or "").strip()
    content = (content or "").strip()
    if not title and not content:
        raise ValueError("title 与 content 至少给一个")
    if not ctx.user_id:
        raise ValueError("缺少用户上下文")
    with Session(engine) as session:
        state = session.get(CapabilityState, (ctx.user_id, "notes"))
        default_tags = "课堂"
        if state:
            try:
                default_tags = json.loads(state.settings_json).get("default_tags", default_tags)
            except json.JSONDecodeError:
                pass
        note = Note(
            user_id=ctx.user_id,
            title=title or content.splitlines()[0][:30],
            content=content,
            tags=(tags or default_tags).strip(),
        )
        session.add(note)
        session.commit()
        session.refresh(note)
        return {"id": note.id, "title": note.title}


class NotesCapability(Capability):
    manifest = CapabilityManifest(
        id="notes",
        name="速记",
        description="随手记下课堂灵感、待办与摘录；这也是给后续能力准备的示例模板。",
        icon="notebook-pen",
        nav=NavItem(label="速记", path="/cap/notes", order=10),
        version="0.1.0",
        settings_schema={
            "type": "object",
            "properties": {
                "default_tags": {
                    "type": "string",
                    "title": "默认标签",
                    "description": "新建速记时自动带上的标签",
                    "default": "课堂",
                }
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
                name="create_note",
                description="把一段内容记成速记（笔记），适合记录用户让你记住的灵感、待办或摘录。",
                parameters={
                    "type": "object",
                    "properties": {
                        "title": {"type": "string", "description": "速记标题"},
                        "content": {"type": "string", "description": "速记正文"},
                        "tags": {"type": "string", "description": "逗号分隔的标签，可省略"},
                    },
                    "required": ["content"],
                },
                handler=_create_note,
            )
        ]


CAPABILITY = NotesCapability()

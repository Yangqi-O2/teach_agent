"""校园雷达能力：教务处 / 信息公开 / 通知公告聚合 + 个性化推荐。

能力边界
--------
- 抓取是**全局行为**（全校共享一份数据），所以配置与手动更新只给管理员；
- 阅读与问答对**所有登录用户**开放，但会按各自的画像排序与解释；
- 条目表不带 user_id —— 公共信息不按用户复制，个性化发生在推荐层。
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from fastapi import APIRouter

from ...core.capability import Capability, CapabilityManifest, NavItem
from ...core.tools import Tool, ToolContext

log = logging.getLogger(__name__)


# ---------------------------------------------------------------- Agent 工具

async def _digest(ctx: ToolContext, limit: int = 8, days: int = 30) -> dict:
    """按当前用户画像挑出近期最相关的校园通知。"""
    from ...core import profile as profiles
    from ...db import engine
    from . import recommend, store
    from sqlmodel import Session

    if not ctx.user_id:
        raise ValueError("缺少用户上下文")
    with Session(engine) as session:
        profile_data = profiles.as_dict(profiles.read(session, ctx.user_id))

    school_key = profile_data.get("school_key") or "zzu"
    rows = store.items_for(school_key, limit=120, days=max(7, days))
    ranked = recommend.rank(rows, profile_data, limit=max(1, min(int(limit or 8), 20)))
    return {
        "school": profile_data.get("school") or "未填写（按郑州大学默认）",
        "profile_completeness": profile_data.get("completeness", 0),
        "items": [
            {
                "title": item["title"],
                "category": item["category"],
                "category_label": recommend.category_label(item["category"]),
                "published_at": item["published_at"],
                "deadline": item["deadline"],
                "reason": reason,
                "url": item["url"],
            }
            for item, reason in ranked
        ],
    }


async def _search(ctx: ToolContext, keyword: str = "", limit: int = 10) -> dict:
    """在已抓取的校园通知里按关键词检索。"""
    from . import store

    text = (keyword or "").strip()
    if not text:
        raise ValueError("keyword 不能为空")
    rows = store.q(
        "SELECT title, category, published_at, deadline, url FROM campus_items "
        "WHERE title LIKE :kw OR content LIKE :kw ORDER BY published_at DESC LIMIT :limit",
        kw=f"%{text}%",
        limit=max(1, min(int(limit or 10), 30)),
    )
    return {"keyword": text, "total": len(rows), "items": rows}


# ---------------------------------------------------------------- 能力

class CampusCapability(Capability):
    manifest = CapabilityManifest(
        id="campus",
        name="校园雷达",
        description=(
            "聚合学校教务处、信息公开网与通知公告，按你的学校、年级、专业和兴趣"
            "挑出相关的活动、竞赛与考试提醒，并回答「最近有什么值得参加的」。"
        ),
        icon="radar",
        nav=NavItem(label="校园雷达", path="/cap/campus", order=20),
        version="0.1.0",
        status="beta",          # 已可用，但目前只覆盖郑州大学，源数量有限
        settings_schema={
            "type": "object",
            "properties": {
                "lookahead_days": {
                    "type": "integer",
                    "title": "关注最近多少天",
                    "description": "信息流默认只看这段时间内发布或更新的通知",
                    "default": 60,
                },
                "default_category": {
                    "type": "string",
                    "enum": ["all", "contest", "exam", "lecture", "activity", "policy"],
                    "title": "默认看哪一类",
                    "description": "打开页面时的默认筛选",
                    "default": "all",
                },
            },
        },
    )

    def router(self) -> APIRouter | None:
        try:
            from .router import router as campus_router
        except Exception:  # noqa: BLE001 - 坏插件不该拖垮主站
            log.exception("campus 路由加载失败（能力暂时不可用）")
            return None
        return campus_router

    def migrations_dir(self) -> Path:
        return Path(__file__).resolve().parent / "migrations"

    def tools(self) -> list[Tool]:
        return [
            Tool(
                name="campus_digest",
                description=(
                    "按用户画像返回近期最相关的校园通知（活动/竞赛/考试），"
                    "带截止日期与推荐理由。适合回答「最近有什么比赛」「我该关注什么」。"
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "limit": {"type": "integer", "description": "返回几条，默认 8"},
                        "days": {"type": "integer", "description": "看最近多少天，默认 30"},
                    },
                },
                handler=_digest,
            ),
            Tool(
                name="campus_search",
                description="在已抓取的校园通知里按关键词检索（如「数学建模」「普通话测试」）。",
                parameters={
                    "type": "object",
                    "properties": {
                        "keyword": {"type": "string", "description": "关键词"},
                        "limit": {"type": "integer", "description": "返回几条，默认 10"},
                    },
                    "required": ["keyword"],
                },
                handler=_search,
            ),
        ]

    async def on_startup(self, app: Any) -> None:  # noqa: ARG002
        from . import scheduler, store

        try:
            created = store.ensure_sources()
            if created:
                log.info("校园雷达：初始化 %d 个抓取源", created)
        except Exception:  # noqa: BLE001
            log.exception("校园雷达：源初始化失败")

        scheduler.start()


CAPABILITY = CampusCapability()

"""校园雷达 HTTP 接口（前缀 `/api/c/campus`）。

权限划分：
- 读（信息流、概览、问答、源状态）：所有登录用户；
- 写（抓取间隔、手动更新、源开关、示例数据）：仅管理员。

条目是全校共享的公共信息，所以不按 user_id 过滤；个性化只体现在
「排序」与「推荐理由」上——那是按当前用户的画像现算的，不落库。
"""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlmodel import Session as DBSession

from ...core import profile as profiles
from ...core.auth import current_user, require_admin
from ...db import get_session
from ...models import User
from . import qa, recommend, scheduler, seed, store
from .sources import KIND_LABELS

log = logging.getLogger(__name__)

router = APIRouter(tags=["campus"])

CATEGORIES = ["contest", "exam", "lecture", "activity", "policy", "other"]


class ConfigIn(BaseModel):
    interval_minutes: int | None = Field(default=None, ge=0, le=10080)
    max_detail_per_run: int | None = Field(default=None, ge=0, le=200)
    enabled: bool | None = None


class CrawlIn(BaseModel):
    source_id: str | None = None


class SourceIn(BaseModel):
    enabled: bool


class AskIn(BaseModel):
    question: str = Field(min_length=1, max_length=500)
    limit: int = Field(default=10, ge=1, le=20)


def _uid(user: User) -> int:
    return user.id or 0


def _is_admin(user: User) -> bool:
    return user.role == "admin"


def _profile(db: DBSession, user: User) -> dict[str, Any]:
    return profiles.as_dict(profiles.read(db, _uid(user)))


def _school_key(profile: dict[str, Any]) -> str:
    # 没填学校时默认按示例学校（郑州大学）展示，并在响应里标注 school_fallback
    return profile.get("school_key") or "zzu"


def _item_out(row: dict[str, Any], reason: str = "") -> dict[str, Any]:
    return {
        "id": row["id"],
        "title": row["title"],
        "url": row["url"],
        "category": row["category"],
        "category_label": recommend.category_label(row["category"]),
        "published_at": row.get("published_at"),
        "deadline": row.get("deadline"),
        "audience": row.get("audience") or "",
        "summary": row.get("summary") or "",
        "reason": reason,
        "is_demo": bool(row.get("is_demo")),
        "source_id": row.get("source_id"),
    }


def _source_out(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row["id"],
        "name": row["name"],
        "url": row["url"],
        "kind": row["kind"],
        "kind_label": KIND_LABELS.get(row["kind"], row["kind"]),
        "enabled": bool(row["enabled"]),
        "last_status": row.get("last_status") or "pending",
        "last_error": row.get("last_error") or "",
        "last_run_at": row.get("last_run_at"),
        "next_run_at": row.get("next_run_at"),
        "item_count": row.get("item_count") or 0,
    }


def _config_out(can_manage: bool) -> dict[str, Any]:
    config = store.config()
    return {
        "interval_minutes": int(config.get("interval_minutes", "360") or 0),
        "max_detail_per_run": int(config.get("max_detail_per_run", "24") or 0),
        "enabled": config.get("enabled", "1") == "1",
        "can_manage": can_manage,
    }


# ---------------------------------------------------------------- 读

@router.get("/health")
async def health(
    user: User = Depends(current_user),
    db: DBSession = Depends(get_session),
) -> dict:
    profile = _profile(db, user)
    school_key = _school_key(profile)
    return {
        "school": profile.get("school") or "郑州大学（默认示例）",
        "school_key": school_key,
        "items": store.item_count(school_key),
        "sources": [_source_out(row) for row in store.list_sources()],
        "config": _config_out(_is_admin(user)),
        "categories": [{"value": key, "label": recommend.category_label(key)} for key in CATEGORIES],
    }


@router.get("/feed")
async def feed(
    category: str = Query(default="all"),
    days: int = Query(default=90, ge=7, le=730),
    limit: int = Query(default=40, ge=1, le=120),
    sort: str = Query(default="match"),
    user: User = Depends(current_user),
    db: DBSession = Depends(get_session),
) -> dict:
    profile = _profile(db, user)
    school_key = _school_key(profile)
    categories = [category] if category in CATEGORIES else None

    rows = store.items_for(school_key, limit=200, days=days, categories=categories)
    reasons = {int(row["id"]): reason for row, reason in recommend.rank(rows, profile, limit=len(rows))}

    if sort == "new":
        rows.sort(key=lambda row: (row.get("published_at") or "", row["id"]), reverse=True)
        picked = rows[:limit]
    else:
        picked = [row for row, _ in recommend.rank(rows, profile, limit=limit)]

    return {
        "school": profile.get("school") or "",
        "school_fallback": not bool(profile.get("school_key")),
        "profile_completeness": profile.get("completeness", 0),
        "total": len(rows),
        "demo_count": sum(1 for row in rows if row.get("is_demo")),
        "items": [_item_out(row, reasons.get(int(row["id"]), "")) for row in picked],
        "sources": [_source_out(row) for row in store.list_sources()],
        "runs": store.recent_runs(8),
        "config": _config_out(_is_admin(user)),
    }


@router.get("/digest")
async def digest(
    days: int = Query(default=90, ge=7, le=730),
    user: User = Depends(current_user),
    db: DBSession = Depends(get_session),
) -> dict:
    profile = _profile(db, user)
    school_key = _school_key(profile)
    rows = store.items_for(school_key, limit=300, days=days)
    counts = {key: 0 for key in CATEGORIES}
    for row in rows:
        counts[row["category"]] = counts.get(row["category"], 0) + 1
    urgent = recommend.upcoming(rows, days=14)
    return {
        "total": len(rows),
        "counts": [
            {"value": key, "label": recommend.category_label(key), "count": counts.get(key, 0)}
            for key in CATEGORIES
        ],
        "upcoming": [_item_out(row) for row in urgent[:6]],
        "profile_completeness": profile.get("completeness", 0),
        "last_run": (store.recent_runs(1) or [None])[0],
    }


@router.post("/ask")
async def ask(
    body: AskIn,
    user: User = Depends(current_user),
    db: DBSession = Depends(get_session),
) -> dict:
    profile = _profile(db, user)
    school_key = _school_key(profile)
    rows = store.items_for(school_key, limit=150, days=180)
    result = await qa.answer(
        body.question.strip(),
        profile,
        rows,
        user_id=_uid(user),
        limit=body.limit,
    )
    result["school"] = profile.get("school") or "郑州大学（默认示例）"
    result["profile_completeness"] = profile.get("completeness", 0)
    return result


# ---------------------------------------------------------------- 管理

@router.put("/config")
async def update_config(
    body: ConfigIn,
    user: User = Depends(require_admin),
) -> dict:
    patch: dict[str, Any] = {}
    if body.interval_minutes is not None:
        patch["interval_minutes"] = body.interval_minutes
    if body.max_detail_per_run is not None:
        patch["max_detail_per_run"] = body.max_detail_per_run
    if body.enabled is not None:
        patch["enabled"] = "1" if body.enabled else "0"
    if patch:
        store.set_config(patch)
        # 间隔变了就把所有源的 next_run_at 重排，否则新设置要等下一轮才生效
        if "interval_minutes" in patch or "enabled" in patch:
            for source in store.list_sources():
                store.schedule_next(source)
    log.info("校园雷达配置更新 by %s: %s", user.username, patch)
    return _config_out(True)


@router.post("/crawl")
async def crawl_now(
    body: CrawlIn | None = None,
    user: User = Depends(require_admin),
) -> dict:
    source_id = (body.source_id if body else None) or None
    if source_id:
        results = [await scheduler.run_source(source_id, trigger="manual")]
    else:
        results = await scheduler.run_all(trigger="manual")
    created = sum(item.get("created", 0) for item in results)
    failed = [item for item in results if item.get("status") == "error"]
    log.info("校园雷达手动更新 by %s：新增 %d，失败 %d", user.username, created, len(failed))
    return {
        "results": results,
        "created": created,
        "failed": len(failed),
        "message": (
            f"更新完成，新增 {created} 条"
            if not failed
            else f"新增 {created} 条，{len(failed)} 个源抓取失败（可查看源状态）"
        ),
    }


@router.patch("/sources/{source_id}")
async def toggle_source(
    source_id: str,
    body: SourceIn,
    user: User = Depends(require_admin),  # noqa: ARG001
) -> dict:
    store.execute(
        "UPDATE campus_sources SET enabled = :enabled WHERE id = :id",
        enabled=1 if body.enabled else 0,
        id=source_id,
    )
    row = store.get_source(source_id)
    if row is None:
        return {"ok": False}
    return _source_out(dict(row, item_count=0))


@router.post("/seed-demo")
async def seed_demo(
    user: User = Depends(require_admin),
    db: DBSession = Depends(get_session),
) -> dict:
    profile = _profile(db, user)
    result = seed.install(_school_key(profile))
    return dict(result, message=f"已导入 {result['created']} 条示例数据（带「示例」标记）")


@router.delete("/seed-demo")
async def clear_demo(user: User = Depends(require_admin)) -> dict:  # noqa: ARG001
    removed = seed.remove()
    return {"removed": removed, "message": f"已清除 {removed} 条示例数据"}

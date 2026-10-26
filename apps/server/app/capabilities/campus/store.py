"""校园雷达 · 数据访问层。

只做 SQL，不含业务判断。所有写操作走同一个 engine，避免像教材库那样
踩到「连接池换连接导致 last_insert_rowid() 失效」的坑——这里的 id 一律由
`insert()` 在**同一个连接**内取回。
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import text

from ...db import engine
from .sources import SOURCES

log = logging.getLogger(__name__)

DEFAULT_CONFIG: dict[str, str] = {
    # 抓取间隔（分钟）。0 表示关闭自动抓取，只能手动更新。
    "interval_minutes": "360",
    "max_detail_per_run": "24",     # 单次最多抓多少个详情页，防止一次打爆对方站点
    "enabled": "1",
}


def now() -> datetime:
    return datetime.now(timezone.utc)


def iso(value: datetime | None = None) -> str:
    return (value or now()).isoformat(timespec="seconds")


def q(sql: str, **params: Any) -> list[dict[str, Any]]:
    with engine.connect() as conn:
        rows = conn.execute(text(sql), params).mappings().all()
    return [dict(row) for row in rows]


def one(sql: str, **params: Any) -> dict[str, Any] | None:
    rows = q(sql, **params)
    return rows[0] if rows else None


def execute(sql: str, **params: Any) -> int:
    with engine.begin() as conn:
        return int(conn.execute(text(sql), params).rowcount or 0)


def insert(sql: str, **params: Any) -> int:
    """执行 INSERT 并在同一连接内取回自增 id。"""
    with engine.begin() as conn:
        result = conn.execute(text(sql), params)
        return int(result.lastrowid or 0)


# ---------------------------------------------------------------- 配置

def config() -> dict[str, str]:
    values = dict(DEFAULT_CONFIG)
    for row in q("SELECT key, value FROM campus_config"):
        values[row["key"]] = row["value"]
    return values


def set_config(patch: dict[str, Any]) -> dict[str, str]:
    stamp = iso()
    with engine.begin() as conn:
        for key, value in patch.items():
            conn.execute(
                text(
                    "INSERT INTO campus_config (key, value, updated_at) VALUES (:k, :v, :t) "
                    "ON CONFLICT(key) DO UPDATE SET value = :v, updated_at = :t"
                ),
                {"k": key, "v": str(value), "t": stamp},
            )
    return config()


def interval_minutes() -> int:
    try:
        return max(0, int(config().get("interval_minutes", "360")))
    except ValueError:
        return 360


# ---------------------------------------------------------------- 源

def ensure_sources() -> int:
    """把内置源写进库（幂等）。返回本次新增条数。"""
    created = 0
    stamp = iso()
    with engine.begin() as conn:
        for item in SOURCES:
            existing = conn.execute(
                text("SELECT id FROM campus_sources WHERE id = :id"), {"id": item["id"]}
            ).first()
            if existing:
                continue
            conn.execute(
                text(
                    "INSERT INTO campus_sources "
                    "(id, school_key, name, url, kind, enabled, interval_minutes, next_run_at, created_at) "
                    "VALUES (:id, :school_key, :name, :url, :kind, 1, 0, :next, :created)"
                ),
                {
                    "id": item["id"],
                    "school_key": item["school_key"],
                    "name": item["name"],
                    "url": item["url"],
                    "kind": item["kind"],
                    "next": stamp,
                    "created": stamp,
                },
            )
            created += 1
    return created


def list_sources() -> list[dict[str, Any]]:
    return q(
        "SELECT s.*, "
        "(SELECT count(*) FROM campus_items i WHERE i.source_id = s.id) AS item_count "
        "FROM campus_sources s ORDER BY s.school_key, s.kind"
    )


def get_source(source_id: str) -> dict[str, Any] | None:
    return one("SELECT * FROM campus_sources WHERE id = :id", id=source_id)


def due_sources(limit: int = 8) -> list[dict[str, Any]]:
    """到点该抓的源。next_run_at 为空也视为到期（首次）。"""
    stamp = iso()
    return q(
        "SELECT * FROM campus_sources "
        "WHERE enabled = 1 AND (next_run_at IS NULL OR next_run_at <= :now) "
        "ORDER BY next_run_at IS NULL DESC, next_run_at ASC LIMIT :limit",
        now=stamp,
        limit=limit,
    )


def schedule_next(source: dict[str, Any], minutes: int | None = None) -> None:
    step = minutes if minutes is not None else int(source.get("interval_minutes") or 0)
    if step <= 0:
        step = interval_minutes()
    if step <= 0:
        # 自动抓取关闭：不排下一次，等人工触发
        execute("UPDATE campus_sources SET next_run_at = NULL WHERE id = :id", id=source["id"])
        return
    execute(
        "UPDATE campus_sources SET next_run_at = :next WHERE id = :id",
        id=source["id"],
        next=iso(now() + timedelta(minutes=step)),
    )


def mark_source(
    source_id: str,
    *,
    status: str,
    error: str | None = None,
    created: int = 0,
) -> None:
    execute(
        "UPDATE campus_sources SET last_run_at = :at, last_status = :status, "
        "last_error = :error, last_created = :created WHERE id = :id",
        at=iso(),
        status=status,
        error=(error or "")[:500] or None,
        created=created,
        id=source_id,
    )


# ---------------------------------------------------------------- 条目

def find_item_by_url(url: str) -> dict[str, Any] | None:
    return one("SELECT * FROM campus_items WHERE url = :url", url=url)


def upsert_item(item: dict[str, Any]) -> str:
    """按 url 去重。返回 created / updated / skipped。

    - 库里没有 → 插入（created）
    - 有但正文 hash 变了 → 更新（updated）
    - 有且 hash 相同 → 跳过（skipped），这就是「避免重复爬取」的落点
    """
    existing = find_item_by_url(item["url"])
    stamp = iso()
    if existing is None:
        insert(
            "INSERT INTO campus_items (source_id, school_key, url, title, summary, content, "
            "content_hash, category, published_at, deadline, audience, tags_json, is_demo, "
            "first_seen_at, updated_at) VALUES (:source_id, :school_key, :url, :title, :summary, "
            ":content, :content_hash, :category, :published_at, :deadline, :audience, :tags_json, "
            ":is_demo, :first_seen, :updated)",
            source_id=item["source_id"],
            school_key=item["school_key"],
            url=item["url"],
            title=item["title"][:300],
            summary=item.get("summary", "")[:500],
            content=item.get("content", "")[:20000],
            content_hash=item.get("content_hash", ""),
            category=item.get("category", "other"),
            published_at=item.get("published_at"),
            deadline=item.get("deadline"),
            audience=item.get("audience", "")[:120],
            tags_json=json.dumps(item.get("tags", []), ensure_ascii=False),
            is_demo=1 if item.get("is_demo") else 0,
            first_seen=stamp,
            updated=stamp,
        )
        return "created"

    if item.get("content_hash") and item["content_hash"] != existing["content_hash"]:
        execute(
            "UPDATE campus_items SET title = :title, summary = :summary, content = :content, "
            "content_hash = :hash, category = :category, published_at = :published_at, "
            "deadline = :deadline, audience = :audience, tags_json = :tags, updated_at = :updated "
            "WHERE id = :id",
            id=existing["id"],
            title=item["title"][:300],
            summary=item.get("summary", "")[:500],
            content=item.get("content", "")[:20000],
            hash=item["content_hash"],
            category=item.get("category", existing["category"]),
            published_at=item.get("published_at") or existing["published_at"],
            deadline=item.get("deadline") or existing["deadline"],
            audience=item.get("audience", "")[:120],
            tags=json.dumps(item.get("tags", []), ensure_ascii=False),
            updated=stamp,
        )
        return "updated"
    return "skipped"


def items_for(
    school_key: str,
    *,
    limit: int = 60,
    days: int | None = 180,
    categories: list[str] | None = None,
) -> list[dict[str, Any]]:
    clauses = ["school_key = :school_key"]
    params: dict[str, Any] = {"school_key": school_key, "limit": limit}
    if days:
        clauses.append("(published_at IS NULL OR published_at >= :since)")
        params["since"] = (now() - timedelta(days=days)).date().isoformat()
    if categories:
        placeholders = ", ".join(f":c{index}" for index in range(len(categories)))
        clauses.append(f"category IN ({placeholders})")
        params.update({f"c{index}": value for index, value in enumerate(categories)})
    return q(
        "SELECT * FROM campus_items WHERE "
        + " AND ".join(clauses)
        + " ORDER BY COALESCE(published_at, first_seen_at) DESC LIMIT :limit",
        **params,
    )


def item_count(school_key: str | None = None) -> int:
    if school_key:
        row = one("SELECT count(*) AS n FROM campus_items WHERE school_key = :k", k=school_key)
    else:
        row = one("SELECT count(*) AS n FROM campus_items")
    return int(row["n"]) if row else 0


# ---------------------------------------------------------------- 运行记录

def start_run(source_id: str, trigger: str) -> int:
    return insert(
        "INSERT INTO campus_runs (source_id, trigger, started_at, status) "
        "VALUES (:source_id, :trigger, :started, 'running')",
        source_id=source_id,
        trigger=trigger,
        started=iso(),
    )


def finish_run(
    run_id: int,
    *,
    status: str,
    fetched: int = 0,
    created: int = 0,
    updated: int = 0,
    skipped: int = 0,
    error: str | None = None,
) -> None:
    execute(
        "UPDATE campus_runs SET finished_at = :finished, status = :status, fetched = :fetched, "
        "created = :created, updated = :updated, skipped = :skipped, error = :error WHERE id = :id",
        finished=iso(),
        status=status,
        fetched=fetched,
        created=created,
        updated=updated,
        skipped=skipped,
        error=(error or "")[:500] or None,
        id=run_id,
    )


def recent_runs(limit: int = 20) -> list[dict[str, Any]]:
    return q(
        "SELECT r.*, s.name AS source_name FROM campus_runs r "
        "LEFT JOIN campus_sources s ON s.id = r.source_id "
        "ORDER BY r.started_at DESC LIMIT :limit",
        limit=limit,
    )

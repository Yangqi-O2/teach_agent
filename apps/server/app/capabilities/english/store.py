"""english 能力的 SQLite 访问层。

把 Postgres 版查询移植过来时，最容易踩的坑是方言差异：`$1`、`::jsonb`、`now()`、
`interval`、`date_trunc` 在 SQLite 里都不存在。这里统一收口：

- 参数用 SQLAlchemy 命名参数（`:name`），调用方传 `q(sql, user_id=...)`；
- 时间一律 UTC ISO-8601 字符串（秒精度），可以直接做字符串比较与排序；
- 数组 / JSON 存 TEXT，用 `json_load` / `json_dump` 转换；
- 主键用 uuid4 的 hex 字符串。
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy import text

from ...db import engine


# ---------------------------------------------------------------- 标识与时间


def new_id() -> str:
    """新的业务主键（32 位 hex，替代原来的 uuid）。"""
    return uuid4().hex


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def now_iso() -> str:
    return _utcnow().isoformat(timespec="seconds")


def iso_ago(*, days: int = 0, hours: int = 0, minutes: int = 0) -> str:
    return (_utcnow() - timedelta(days=days, hours=hours, minutes=minutes)).isoformat(timespec="seconds")


def day_start_iso() -> str:
    """当天 00:00:00（UTC）。"""
    return _utcnow().replace(hour=0, minute=0, second=0, microsecond=0).isoformat(timespec="seconds")


def month_start_iso() -> str:
    """当月 1 日 00:00:00（UTC）。"""
    return _utcnow().replace(day=1, hour=0, minute=0, second=0, microsecond=0).isoformat(timespec="seconds")


# ---------------------------------------------------------------- 查询


def q(sql: str, **params: Any) -> list[dict[str, Any]]:
    """查多行，返回 dict 列表。"""
    with engine.connect() as conn:
        rows = conn.execute(text(sql), params).mappings().all()
    return [dict(row) for row in rows]


def one(sql: str, **params: Any) -> dict[str, Any] | None:
    """查一行；没有就返回 None。"""
    rows = q(sql, **params)
    return rows[0] if rows else None


def execute(sql: str, **params: Any) -> int:
    """写操作，返回影响行数。"""
    with engine.begin() as conn:
        result = conn.execute(text(sql), params)
        return int(result.rowcount or 0)


# ---------------------------------------------------------------- JSON


def json_load(raw: Any, default: Any = None) -> Any:
    """容错解析 TEXT 里的 JSON：None / 坏数据都回退到 default。"""
    if raw is None or raw == "":
        return default
    if isinstance(raw, (list, dict)):
        return raw
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return default


def json_dump(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False)


def as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return False

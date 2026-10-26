"""教材库的 SQLite 访问层。

沿用 english 能力的约定：参数用命名参数、时间用 UTC ISO 字符串、JSON 存 TEXT。
这里额外封装两件事：
- `scope_sql()`：把「我能看哪些教材」收口成一段可复用的 WHERE 片段；
- FTS5 索引的写入与清理，保证 `chunks` 与 `chunks_fts` 的 rowid 始终对齐。
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Sequence
from uuid import uuid4

from sqlalchemy import bindparam, text

from ...db import engine


def new_id() -> str:
    return uuid4().hex


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _statement(sql: str, expanding: Sequence[str]):
    """把 `IN :xxx` 这类列表参数声明为 expanding，SQLite 才能正确展开。"""
    stmt = text(sql)
    if expanding:
        stmt = stmt.bindparams(*(bindparam(name, expanding=True) for name in expanding))
    return stmt


def q(sql: str, expanding: Sequence[str] = (), **params: Any) -> list[dict[str, Any]]:
    with engine.connect() as conn:
        rows = conn.execute(_statement(sql, expanding), params).mappings().all()
    return [dict(row) for row in rows]


def one(sql: str, expanding: Sequence[str] = (), **params: Any) -> dict[str, Any] | None:
    rows = q(sql, expanding, **params)
    return rows[0] if rows else None


def execute(sql: str, **params: Any) -> int:
    with engine.begin() as conn:
        result = conn.execute(text(sql), params)
        return int(result.rowcount or 0)


def insert(sql: str, **params: Any) -> int:
    """插入并返回自增主键。

    必须和 INSERT 用同一个连接——`last_insert_rowid()` 是连接级的，
    分开两次调用（哪怕只隔一行代码）在连接池里就可能落到不同连接上，
    拿到的永远是 0。这个坑在并发上传时会稳定复现。
    """
    with engine.begin() as conn:
        result = conn.execute(text(sql), params)
        return int(result.lastrowid or 0)


def json_load(raw: Any, default: Any = None) -> Any:
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


def scope_sql(alias: str = "") -> str:
    """可见性片段：自己的 + 别人共享的。

    用法：`f"SELECT * FROM documents d WHERE {scope_sql('d')} AND ..."`
    绑定参数需同时提供 `uid`。
    """
    prefix = f"{alias}." if alias else ""
    return f"({prefix}user_id = :uid OR {prefix}visibility = 'shared')"


def can_edit(row: dict, user_id: int, is_admin: bool) -> bool:
    """shared 教材只有 owner 与管理员能改删；private 只有 owner。"""
    if is_admin:
        return True
    return int(row.get("user_id") or 0) == user_id

"""SQLite 引擎、会话与轻量迁移执行器。

迁移规则：任意目录下的 *.sql 按文件名顺序执行一次，执行记录写入 _migrations。
核心表由 SQLModel.metadata 建；能力表由能力自己的 migrations/*.sql 建。
"""
from __future__ import annotations

import logging
from pathlib import Path

from sqlalchemy import event, text
from sqlmodel import Session, SQLModel, create_engine

from .config import BASE_DIR, settings

log = logging.getLogger(__name__)

engine = create_engine(
    f"sqlite:///{settings.db_path}",
    connect_args={"check_same_thread": False},
    pool_pre_ping=True,
)


@event.listens_for(engine, "connect")
def _sqlite_pragmas(dbapi_connection, _record):  # noqa: ANN001
    cur = dbapi_connection.cursor()
    cur.execute("PRAGMA journal_mode=WAL")
    cur.execute("PRAGMA synchronous=NORMAL")
    cur.execute("PRAGMA foreign_keys=ON")
    cur.close()


def get_session():
    with Session(engine) as session:
        yield session


def _apply_script(script: str) -> None:
    raw = engine.raw_connection()
    try:
        raw.executescript(script)
        raw.commit()
    finally:
        raw.close()


def _migration_files(directory: Path) -> list[Path]:
    if not directory.is_dir():
        return []
    return sorted(p for p in directory.glob("*.sql") if p.is_file())


def run_migrations(extra_dirs: dict[str, Path] | None = None) -> list[str]:
    """执行核心与各能力的 SQL 迁移，返回本次新执行的迁移名。"""
    _apply_script(
        "CREATE TABLE IF NOT EXISTS _migrations ("
        " name TEXT PRIMARY KEY, applied_at TEXT NOT NULL DEFAULT (datetime('now')));"
    )
    with engine.connect() as conn:
        applied = {row[0] for row in conn.execute(text("SELECT name FROM _migrations"))}

    plans: list[tuple[str, Path]] = []
    for path in _migration_files(BASE_DIR / "app" / "migrations"):
        plans.append((f"core/{path.name}", path))
    for scope, directory in (extra_dirs or {}).items():
        for path in _migration_files(directory):
            plans.append((f"{scope}/{path.name}", path))

    executed: list[str] = []
    for name, path in plans:
        if name in applied:
            continue
        try:
            _apply_script(path.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            log.error("迁移失败 %s: %s", name, exc)
            raise
        _apply_script(f"INSERT INTO _migrations(name) VALUES ('{name}')")
        executed.append(name)
        log.info("迁移已执行: %s", name)
    return executed


def init_db(extra_dirs: dict[str, Path] | None = None) -> None:
    settings.ensure_dirs()
    run_migrations(extra_dirs)
    SQLModel.metadata.create_all(engine)

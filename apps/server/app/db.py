"""SQLite 引擎、会话与轻量迁移执行器。

迁移规则：任意目录下的 *.sql 按文件名顺序执行一次，执行记录写入 _migrations。
核心表由 SQLModel.metadata 建；能力表由能力自己的 migrations/*.sql 建。
"""
from __future__ import annotations

import logging
import shutil
from pathlib import Path

from sqlalchemy import event, text
from sqlmodel import Session, SQLModel, create_engine

from .config import BASE_DIR, LEGACY_DATA_DIR, settings

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


def _is_legacy_database() -> bool:
    """v0.1 是单用户、没有 users 表；检测到就备份后用新库，避免破坏性升级。"""
    path = settings.db_path
    if not path.exists() or path.stat().st_size == 0:
        return False
    import sqlite3

    try:
        with sqlite3.connect(path) as conn:
            names = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    except sqlite3.Error:
        return False
    if "users" in names:
        return False
    return bool(names & {"providers", "jobs", "notes", "capability_state", "events", "settings"})


def _backup_legacy_database() -> Path:
    from datetime import datetime

    engine.dispose()
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup = settings.db_path.with_name(f"app.db.v0.1-{stamp}.bak")
    settings.db_path.replace(backup)
    for suffix in ("-wal", "-shm"):
        leftover = settings.db_path.with_name(settings.db_path.name + suffix)
        if leftover.exists():
            leftover.unlink()
    log.warning("检测到 v0.1 单用户数据库，已备份为 %s，并创建多用户新库", backup)
    return backup


def _migrate_legacy_data_dir() -> None:
    """v0.2.0 起所有运行期数据统一放在仓库根的 data/；旧位置有数据就整体搬过来。"""
    legacy = LEGACY_DATA_DIR
    if legacy.resolve() == settings.data_dir.resolve():
        return
    if legacy.is_dir() and not settings.data_dir.exists():
        settings.data_dir.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(legacy), str(settings.data_dir))
        log.warning("数据目录已迁移：%s → %s", legacy, settings.data_dir)


def init_db(extra_dirs: dict[str, Path] | None = None) -> None:
    _migrate_legacy_data_dir()
    settings.ensure_dirs()
    if _is_legacy_database():
        _backup_legacy_database()
    run_migrations(extra_dirs)
    SQLModel.metadata.create_all(engine)

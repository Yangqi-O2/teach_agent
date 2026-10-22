"""核心数据表：供应商、任务、能力开关、事件、设置。

能力自己的表不在这里，由各能力的 migrations/*.sql 负责。
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlmodel import Field, SQLModel


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Provider(SQLModel, table=True):
    __tablename__ = "providers"

    id: int | None = Field(default=None, primary_key=True)
    name: str
    base_url: str
    api_key_enc: str | None = None
    key_hint: str | None = None
    chat_model: str = ""
    embed_model: str | None = None
    is_default: bool = False
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class Setting(SQLModel, table=True):
    __tablename__ = "settings"

    key: str = Field(primary_key=True)
    value: str = ""
    updated_at: datetime = Field(default_factory=utcnow)


class Job(SQLModel, table=True):
    __tablename__ = "jobs"

    id: str = Field(primary_key=True)
    type: str
    title: str
    status: str = "queued"          # queued | running | done | error | cancelled
    progress: int = 0
    message: str | None = None
    payload: str | None = None
    result: str | None = None
    error: str | None = None
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)
    finished_at: datetime | None = None


class CapabilityState(SQLModel, table=True):
    __tablename__ = "capability_state"

    id: str = Field(primary_key=True)
    enabled: bool = True
    settings_json: str = "{}"
    updated_at: datetime = Field(default_factory=utcnow)


class Event(SQLModel, table=True):
    __tablename__ = "events"

    id: int | None = Field(default=None, primary_key=True)
    kind: str = "info"
    message: str = ""
    payload: str | None = None
    created_at: datetime = Field(default_factory=utcnow)

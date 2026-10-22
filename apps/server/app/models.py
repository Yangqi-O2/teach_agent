"""核心数据表。

多用户模型：除 users / sessions / settings / _migrations 外，所有业务表都带 user_id，
由 API 层强制按当前登录用户过滤。
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlmodel import Field, SQLModel


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class User(SQLModel, table=True):
    __tablename__ = "users"

    id: int | None = Field(default=None, primary_key=True)
    username: str = Field(index=True, unique=True)      # 小写，唯一
    display_name: str = ""
    password_hash: str = ""
    role: str = "user"                                  # admin | user
    is_active: bool = True
    created_at: datetime = Field(default_factory=utcnow)
    last_login_at: datetime | None = None


class Session(SQLModel, table=True):
    __tablename__ = "sessions"

    id: str = Field(primary_key=True)                   # sha256(token)，库中不存原始 token
    user_id: int = Field(index=True)
    created_at: datetime = Field(default_factory=utcnow)
    last_seen_at: datetime = Field(default_factory=utcnow)
    expires_at: datetime = Field(default_factory=utcnow)
    user_agent: str | None = None


class Provider(SQLModel, table=True):
    __tablename__ = "providers"

    id: int | None = Field(default=None, primary_key=True)
    user_id: int = Field(index=True, default=0)
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
    """全局设置（站点级），仅管理员可写。"""
    __tablename__ = "settings"

    key: str = Field(primary_key=True)
    value: str = ""
    updated_at: datetime = Field(default_factory=utcnow)


class Job(SQLModel, table=True):
    __tablename__ = "jobs"

    id: str = Field(primary_key=True)
    user_id: int = Field(index=True, default=0)
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

    user_id: int = Field(primary_key=True, default=0)
    id: str = Field(primary_key=True)
    enabled: bool = True
    settings_json: str = "{}"
    updated_at: datetime = Field(default_factory=utcnow)


class Event(SQLModel, table=True):
    __tablename__ = "events"

    id: int | None = Field(default=None, primary_key=True)
    user_id: int = Field(index=True, default=0)
    kind: str = "info"
    message: str = ""
    payload: str | None = None
    created_at: datetime = Field(default_factory=utcnow)

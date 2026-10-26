"""教材库的数据表映射。

表结构由 migrations/001_library.sql 建；这里只做 SQLModel 映射。

双池约定：每个文档带 visibility（private/shared）+ user_id（owner）。
- private：仅 owner 可见
- shared：所有登录成员可见（只读），只有 owner（或管理员）能改删
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlmodel import Field, SQLModel


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Course(SQLModel, table=True):
    __tablename__ = "courses"

    id: int | None = Field(default=None, primary_key=True)
    user_id: int = Field(index=True, default=0)
    visibility: str = Field(default="private", index=True)      # private | shared
    name: str = ""
    color: str = "#14687b"
    term: str = ""                                              # 例如 2026 秋
    created_at: datetime = Field(default_factory=utcnow)


class Document(SQLModel, table=True):
    __tablename__ = "documents"

    id: int | None = Field(default=None, primary_key=True)
    user_id: int = Field(index=True, default=0)
    visibility: str = Field(default="private", index=True)
    course_id: int | None = Field(default=None, index=True)
    title: str = ""
    kind: str = ""                                              # docx / pptx / pdf / epub / md / txt / html / url
    filename: str | None = None
    size: int = 0
    sha256: str | None = Field(default=None, index=True)
    status: str = "queued"                                      # queued | parsing | indexing | ready | error
    progress: int = 0
    message: str | None = None
    error: str | None = None
    page_count: int = 0
    char_count: int = 0
    chunk_count: int = 0
    embedding_model: str | None = None
    meta_json: str = "{}"
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class Chunk(SQLModel, table=True):
    __tablename__ = "chunks"

    id: int | None = Field(default=None, primary_key=True)
    user_id: int = Field(index=True, default=0)                 # 冗余一份，便于检索过滤
    document_id: int = Field(index=True)
    ord: int = 0
    text: str = ""
    heading_path: str = ""
    loc_label: str = ""                                         # 第 N 页 / 第 N 张 / 章节名
    loc_index: int = 0
    n_chars: int = 0
    embedded: bool = False
    embedding: bytes | None = None

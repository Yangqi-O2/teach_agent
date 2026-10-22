"""群聊简报的数据表映射。

表结构由 migrations/001_wechat_digest.sql 负责建，这里只做 SQLModel 映射。
时间字段一律用 ISO 字符串（TEXT）：契约里的 created_at / updated_at 形如
``2026-10-22T20:31:00``，直接存原样最省心。
"""
from __future__ import annotations

from sqlmodel import Field, SQLModel


class Digest(SQLModel, table=True):
    __tablename__ = "wechat_digests"

    id: int | None = Field(default=None, primary_key=True)
    title: str = ""
    source: str = "paste"
    group_name: str = ""
    style: str = "general"
    status: str = "queued"          # queued | running | done | error | cancelled
    job_id: str | None = None
    provider: str = ""              # 供应商展示名
    model: str = ""
    message_count: int = 0          # 清洗前
    kept_count: int = 0             # 清洗后
    result_json: str = "{}"         # DigestPayload（§4.2）
    error: str | None = None
    created_at: str = ""
    updated_at: str = ""

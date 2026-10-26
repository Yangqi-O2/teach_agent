"""用户画像接口。

写入只在这里：`PUT /api/profile`。其他能力只读 `core.profile.read()`，
避免出现「谁都能改画像」导致推荐口径不一致。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlmodel import Session as DBSession

from ..core import profile as profiles
from ..core.auth import current_user
from ..db import get_session
from ..models import User

router = APIRouter(prefix="/profile", tags=["profile"])


class ProfileIn(BaseModel):
    """全部字段可选：`PUT` 是局部更新，只改传进来的字段。"""

    school: str | None = Field(default=None, max_length=60)
    grade: str | None = Field(default=None, max_length=30)
    department: str | None = Field(default=None, max_length=60)
    major: str | None = Field(default=None, max_length=60)
    class_name: str | None = Field(default=None, max_length=60)
    interests: list[str] | str | None = None
    goals: list[str] | str | None = None
    onboarded: bool | None = None


@router.get("")
async def get_profile(
    user: User = Depends(current_user),
    db: DBSession = Depends(get_session),
) -> dict:
    record = profiles.read(db, user.id or 0)
    return profiles.as_dict(record)


@router.put("")
async def update_profile(
    body: ProfileIn,
    user: User = Depends(current_user),
    db: DBSession = Depends(get_session),
) -> dict:
    payload = body.model_dump(exclude_unset=True)
    record = profiles.upsert(db, user.id or 0, payload)
    return profiles.as_dict(record)

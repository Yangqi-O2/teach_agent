"""管理员：成员管理。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, Field
from sqlmodel import Session as DBSession
from sqlmodel import select

from ..core import auth
from ..core.errors import ApiError
from ..db import get_session
from ..models import Job, Provider, Session, User
from .auth import public_user

router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(auth.require_admin)])


class CreateUserIn(BaseModel):
    username: str = Field(min_length=3, max_length=24)
    password: str = Field(min_length=1)
    display_name: str = ""
    role: str = "user"


class UpdateUserIn(BaseModel):
    display_name: str | None = None
    role: str | None = None
    is_active: bool | None = None


class ResetPasswordIn(BaseModel):
    password: str = Field(min_length=1)


class RegistrationIn(BaseModel):
    allow: bool


def _active_admins(db: DBSession) -> int:
    return len(
        db.exec(
            select(User).where(User.role == "admin").where(User.is_active == True)  # noqa: E712
        ).all()
    )


def _user_counts(db: DBSession, user_id: int) -> dict:
    return {
        "providers": len(db.exec(select(Provider).where(Provider.user_id == user_id)).all()),
        "jobs": len(db.exec(select(Job).where(Job.user_id == user_id)).all()),
    }


@router.get("/users")
async def list_users(db: DBSession = Depends(get_session)) -> list[dict]:
    users = db.exec(select(User).order_by(User.created_at)).all()
    return [{**public_user(u), **_user_counts(db, u.id or 0)} for u in users]


@router.post("/users")
async def create_user(
    body: CreateUserIn,
    db: DBSession = Depends(get_session),
    admin: User = Depends(auth.require_admin),
) -> dict:
    if body.role not in ("admin", "user"):
        raise ApiError("角色只能是 admin 或 user", code="invalid_role")
    username = auth.validate_username(body.username)
    auth.validate_password(body.password)
    if db.exec(select(User).where(User.username == username)).first() is not None:
        raise ApiError("用户名已被占用", code="username_taken", status=409)
    user = User(
        username=username,
        display_name=(body.display_name or username).strip()[:30],
        password_hash=auth.hash_password(body.password),
        role=body.role,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    auth.log_event(db, admin.id or 0, "admin", f"创建了成员：{user.display_name}")
    return public_user(user)


@router.patch("/users/{user_id}")
async def update_user(
    user_id: int,
    body: UpdateUserIn,
    db: DBSession = Depends(get_session),
    admin: User = Depends(auth.require_admin),
) -> dict:
    user = db.get(User, user_id)
    if user is None:
        raise ApiError("成员不存在", code="not_found", status=404)
    if body.role is not None:
        if body.role not in ("admin", "user"):
            raise ApiError("角色只能是 admin 或 user", code="invalid_role")
        if user.id == admin.id and body.role != "admin":
            raise ApiError("不能取消自己的管理员身份", code="invalid_operation")
        if user.role == "admin" and body.role == "user" and _active_admins(db) <= 1:
            raise ApiError("至少要保留一名管理员", code="invalid_operation")
        user.role = body.role
    if body.is_active is not None:
        if user.id == admin.id and not body.is_active:
            raise ApiError("不能停用自己的账号", code="invalid_operation")
        user.is_active = body.is_active
        if not body.is_active:
            for row in db.exec(select(Session).where(Session.user_id == user_id)).all():
                db.delete(row)
    if body.display_name is not None:
        user.display_name = body.display_name.strip()[:30] or user.username
    db.add(user)
    db.commit()
    db.refresh(user)
    return public_user(user)


@router.post("/users/{user_id}/password")
async def reset_password(
    user_id: int,
    body: ResetPasswordIn,
    db: DBSession = Depends(get_session),
    admin: User = Depends(auth.require_admin),
) -> dict:
    user = db.get(User, user_id)
    if user is None:
        raise ApiError("成员不存在", code="not_found", status=404)
    auth.validate_password(body.password)
    user.password_hash = auth.hash_password(body.password)
    db.add(user)
    for row in db.exec(select(Session).where(Session.user_id == user_id)).all():
        db.delete(row)
    db.commit()
    auth.log_event(db, admin.id or 0, "admin", f"重置了 {user.display_name} 的密码")
    return {"ok": True}


@router.delete("/users/{user_id}")
async def delete_user(
    user_id: int,
    db: DBSession = Depends(get_session),
    admin: User = Depends(auth.require_admin),
) -> dict:
    user = db.get(User, user_id)
    if user is None:
        raise ApiError("成员不存在", code="not_found", status=404)
    if user.id == admin.id:
        raise ApiError("不能删除自己", code="invalid_operation")
    if user.role == "admin" and _active_admins(db) <= 1:
        raise ApiError("至少要保留一名管理员", code="invalid_operation")

    from sqlmodel import text

    for table in ("providers", "jobs", "events", "notes", "capability_state", "sessions"):
        try:
            db.exec(text(f"DELETE FROM {table} WHERE user_id = :uid"), params={"uid": user_id})  # type: ignore[call-arg]
        except Exception:  # noqa: BLE001
            db.rollback()
    db.delete(user)
    db.commit()
    auth.log_event(db, admin.id or 0, "admin", f"删除了成员：{user.username}")
    return {"ok": True}


@router.put("/registration")
async def update_registration(
    body: RegistrationIn,
    db: DBSession = Depends(get_session),
    admin: User = Depends(auth.require_admin),
) -> dict:
    auth.set_allow_registration(db, body.allow)
    auth.log_event(db, admin.id or 0, "admin", f"{'开启' if body.allow else '关闭'}了注册")
    return {"ok": True, "allow_registration": body.allow}

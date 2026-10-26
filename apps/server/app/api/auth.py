"""注册、登录、登出、改密。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, Field
from sqlmodel import Session as DBSession

from ..config import APP_NAME, VERSION
from ..core import auth
from ..core.errors import ApiError
from ..db import get_session
from ..models import User

router = APIRouter(prefix="/auth", tags=["auth"])


class RegisterIn(BaseModel):
    username: str = Field(min_length=3, max_length=24)
    password: str = Field(min_length=1)
    display_name: str = ""
    # 注册第二步（个人基本信息）可以直接带上来；也可以先注册再 PUT /api/profile。
    # 全部可选，老客户端不受影响。
    school: str | None = Field(default=None, max_length=60)
    grade: str | None = Field(default=None, max_length=30)
    department: str | None = Field(default=None, max_length=60)
    major: str | None = Field(default=None, max_length=60)
    class_name: str | None = Field(default=None, max_length=60)
    interests: list[str] | str | None = None
    goals: list[str] | str | None = None


class LoginIn(BaseModel):
    username: str
    password: str


class ChangePasswordIn(BaseModel):
    current_password: str
    new_password: str


def public_user(user: User) -> dict:
    return {
        "id": user.id,
        "username": user.username,
        "display_name": user.display_name or user.username,
        "role": user.role,
        "is_active": user.is_active,
        "created_at": user.created_at.isoformat() if user.created_at else None,
        "last_login_at": user.last_login_at.isoformat() if user.last_login_at else None,
    }


@router.get("/config")
async def auth_config(db: DBSession = Depends(get_session)) -> dict:
    return {
        "app": {"name": APP_NAME, "version": VERSION},
        "allow_registration": auth.allow_registration(db),
        "has_users": auth.count_users(db) > 0,
    }


@router.post("/register")
async def register(
    body: RegisterIn,
    request: Request,
    response: Response,
    db: DBSession = Depends(get_session),
) -> dict:
    profile_fields = {
        key: getattr(body, key)
        for key in (
            "school",
            "grade",
            "department",
            "major",
            "class_name",
            "interests",
            "goals",
        )
        if getattr(body, key) is not None
    }
    user, token = auth.register(
        db,
        body.username,
        body.password,
        body.display_name,
        request,
        profile=profile_fields or None,
    )
    auth.set_cookie(response, token)
    return public_user(user)


@router.post("/login")
async def login(
    body: LoginIn,
    request: Request,
    response: Response,
    db: DBSession = Depends(get_session),
) -> dict:
    username = (body.username or "").strip().lower()
    key = f"{username}|{request.client.host if request.client else '-'}"
    auth.rate_limit_check(key)
    try:
        user = auth.authenticate(db, username, body.password)
    except ApiError:
        auth.rate_limit_record(key)
        raise
    token = auth.create_session(db, user, request)
    auth.set_cookie(response, token)
    auth.log_event(db, user.id or 0, "auth", f"登录：{user.display_name}")
    return public_user(user)


@router.post("/logout")
async def logout(
    request: Request,
    response: Response,
    db: DBSession = Depends(get_session),
) -> dict:
    auth.destroy_session(db, request.cookies.get(auth.COOKIE_NAME))
    auth.clear_cookie(response)
    return {"ok": True}


@router.get("/me")
async def me(user: User | None = Depends(auth.optional_user)) -> dict:
    if user is None:
        raise ApiError("请先登录", code="unauthorized", status=401)
    return public_user(user)


@router.put("/password")
async def change_password(
    body: ChangePasswordIn,
    request: Request,
    response: Response,
    user: User = Depends(auth.current_user),
    db: DBSession = Depends(get_session),
) -> dict:
    auth.validate_password(body.new_password)
    auth.change_password(db, user, body.current_password, body.new_password)
    auth.log_event(db, user.id or 0, "auth", "修改了登录密码")
    # 旧会话已全部撤销，重新签发一个
    token = auth.create_session(db, user, request)
    auth.set_cookie(response, token)
    return {"ok": True}

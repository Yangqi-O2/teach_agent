"""账号、会话与权限。

- 密码：hashlib.scrypt（stdlib，参数写在哈希串里，便于以后升级）
- 会话：随机 token 给浏览器，库里只存 sha256(token)，数据库泄露也无法直接冒用
- Cookie：HttpOnly + SameSite=Lax（本地部署；放到 HTTPS 后设置 TJH_COOKIE_SECURE=true）
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import re
import secrets
import time
from datetime import datetime, timedelta, timezone

from fastapi import Depends, Request, Response
from sqlmodel import Session as DBSession
from sqlmodel import select

from ..config import settings
from ..db import get_session
from ..models import Event, Session, Setting, User
from .errors import ApiError

log = logging.getLogger(__name__)

USERNAME_RE = re.compile(r"^[a-zA-Z0-9_]{3,24}$")
COOKIE_NAME = settings.session_cookie
_SCRYPT = {"n": 2**14, "r": 8, "p": 1, "dklen": 32}

# 登录失败限流（进程内）。单机部署足够；多进程部署需要换 Redis。
_attempts: dict[str, list[float]] = {}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _b64e(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _b64d(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


# ---------------- 密码 ----------------

def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode("utf-8"), salt=salt, **_SCRYPT)
    return "scrypt${n}${r}${p}${salt}${digest}".format(
        salt=_b64e(salt), digest=_b64e(digest), **_SCRYPT
    )


def verify_password(password: str, stored: str) -> bool:
    if not stored:
        return False
    try:
        scheme, n, r, p, salt, digest = stored.split("$")
        if scheme != "scrypt":
            return False
        expected = _b64d(digest)
        actual = hashlib.scrypt(
            password.encode("utf-8"),
            salt=_b64d(salt),
            n=int(n),
            r=int(r),
            p=int(p),
            dklen=len(expected),
        )
        return hmac.compare_digest(actual, expected)
    except (ValueError, TypeError):
        return False


def validate_username(username: str) -> str:
    value = (username or "").strip().lower()
    if not USERNAME_RE.match(value):
        raise ApiError("用户名需为 3–24 位字母、数字或下划线", code="invalid_username")
    return value


def validate_password(password: str) -> str:
    if not password or len(password) < settings.password_min_length:
        raise ApiError(f"密码至少 {settings.password_min_length} 位", code="weak_password")
    if len(password) > 128:
        raise ApiError("密码太长了", code="weak_password")
    return password


# ---------------- 会话 ----------------

def _token_id(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def create_session(db: DBSession, user: User, request: Request | None = None) -> str:
    token = secrets.token_urlsafe(32)
    now = _now()
    db.add(
        Session(
            id=_token_id(token),
            user_id=user.id or 0,
            created_at=now,
            last_seen_at=now,
            expires_at=now + timedelta(days=settings.session_days),
            user_agent=(request.headers.get("user-agent", "")[:200] if request else None),
        )
    )
    # 顺手清理过期会话
    for stale in db.exec(select(Session).where(Session.expires_at < now)).all():
        db.delete(stale)
    db.commit()
    return token


def destroy_session(db: DBSession, token: str | None) -> None:
    if not token:
        return
    row = db.get(Session, _token_id(token))
    if row is not None:
        db.delete(row)
        db.commit()


def set_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        COOKIE_NAME,
        token,
        max_age=settings.session_days * 86400,
        httponly=True,
        samesite="lax",
        secure=settings.cookie_secure,
        path="/",
    )


def clear_cookie(response: Response) -> None:
    response.delete_cookie(COOKIE_NAME, path="/")


def resolve_user(db: DBSession, token: str | None) -> User | None:
    if not token:
        return None
    row = db.get(Session, _token_id(token))
    if row is None:
        return None
    if row.expires_at < _now():
        db.delete(row)
        db.commit()
        return None
    user = db.get(User, row.user_id)
    if user is None or not user.is_active:
        return None
    # 限流写入：每小时最多更新一次 last_seen
    if (_now() - row.last_seen_at).total_seconds() > 3600:
        row.last_seen_at = _now()
        db.add(row)
        db.commit()
    return user


# ---------------- FastAPI 依赖 ----------------

def optional_user(request: Request, db: DBSession = Depends(get_session)) -> User | None:
    return resolve_user(db, request.cookies.get(COOKIE_NAME))


def current_user(request: Request, db: DBSession = Depends(get_session)) -> User:
    user = resolve_user(db, request.cookies.get(COOKIE_NAME))
    if user is None:
        raise ApiError("请先登录", code="unauthorized", status=401)
    return user


def require_admin(user: User = Depends(current_user)) -> User:
    if user.role != "admin":
        raise ApiError("需要管理员权限", code="forbidden", status=403)
    return user


# ---------------- 站点开关 ----------------

def allow_registration(db: DBSession) -> bool:
    row = db.get(Setting, "auth.allow_registration")
    if row is None:
        return settings.allow_registration
    return row.value.strip().lower() in ("true", "1", '"true"')


def set_allow_registration(db: DBSession, value: bool) -> None:
    row = db.get(Setting, "auth.allow_registration") or Setting(key="auth.allow_registration")
    row.value = "true" if value else "false"
    db.add(row)
    db.commit()


def count_users(db: DBSession) -> int:
    return len(db.exec(select(User)).all())


# ---------------- 限流 ----------------

def rate_limit_check(key: str) -> None:
    now = time.time()
    window = settings.login_window_seconds
    hits = [t for t in _attempts.get(key, []) if now - t < window]
    _attempts[key] = hits
    if len(hits) >= settings.login_max_attempts:
        raise ApiError(
            "尝试次数过多，请稍后再试", code="rate_limited", status=429
        )


def rate_limit_record(key: str) -> None:
    _attempts.setdefault(key, []).append(time.time())


# ---------------- 事件 ----------------

def log_event(db: DBSession, user_id: int, kind: str, message: str) -> None:
    db.add(Event(user_id=user_id, kind=kind, message=message))
    db.commit()


# ---------------- 注册 / 登录 ----------------

def _adopt_orphans(db: DBSession, user_id: int) -> None:
    """v0.2 迁移用：把旧的无主数据归给第一个注册的用户。"""
    from sqlmodel import text

    tables = ["providers", "jobs", "events", "notes", "capability_state"]
    for table in tables:
        try:
            db.exec(text(f"UPDATE {table} SET user_id = :uid WHERE user_id = 0"), params={"uid": user_id})  # type: ignore[call-arg]
        except Exception:  # noqa: BLE001 - 表可能不存在
            db.rollback()
    db.commit()


def register(
    db: DBSession,
    username: str,
    password: str,
    display_name: str = "",
    request: Request | None = None,
) -> tuple[User, str]:
    username = validate_username(username)
    validate_password(password)

    first_user = count_users(db) == 0
    if not first_user and not allow_registration(db):
        raise ApiError("站点已关闭注册，请联系管理员开通账号", code="registration_closed", status=403)

    existing = db.exec(select(User).where(User.username == username)).first()
    if existing is not None:
        raise ApiError("用户名已被占用", code="username_taken", status=409)

    user = User(
        username=username,
        display_name=(display_name or username).strip()[:30],
        password_hash=hash_password(password),
        role="admin" if first_user else "user",
        last_login_at=_now(),
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    if first_user:
        _adopt_orphans(db, user.id or 0)
        log.info("首个用户 %s 已创建，角色 admin", username)

    token = create_session(db, user, request)
    log_event(db, user.id or 0, "auth", f"注册了新账号：{user.display_name}")
    return user, token


def authenticate(db: DBSession, username: str, password: str) -> User:
    username = (username or "").strip().lower()
    user = db.exec(select(User).where(User.username == username)).first()
    if user is None or not verify_password(password, user.password_hash):
        raise ApiError("用户名或密码不正确", code="invalid_credentials", status=401)
    if not user.is_active:
        raise ApiError("账号已被停用，请联系管理员", code="account_disabled", status=403)
    user.last_login_at = _now()
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def change_password(db: DBSession, user: User, current: str, new: str) -> None:
    if not verify_password(current, user.password_hash):
        raise ApiError("当前密码不正确", code="invalid_credentials")
    validate_password(new)
    user.password_hash = hash_password(new)
    db.add(user)
    db.commit()
    # 让该用户的其他会话失效
    for row in db.exec(select(Session).where(Session.user_id == user.id)).all():
        db.delete(row)
    db.commit()
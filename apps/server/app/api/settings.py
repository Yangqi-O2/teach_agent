"""站点级设置的键值存储。读取需登录，写入仅管理员。"""
from __future__ import annotations

import json

from fastapi import APIRouter, Depends
from sqlmodel import Session, select

from ..core.auth import current_user, require_admin
from ..db import get_session
from ..models import Setting, User

router = APIRouter(prefix="/settings", tags=["settings"])


@router.get("")
async def get_settings(
    session: Session = Depends(get_session), _: User = Depends(current_user)
) -> dict:
    rows = session.exec(select(Setting)).all()
    out: dict = {}
    for row in rows:
        try:
            out[row.key] = json.loads(row.value)
        except json.JSONDecodeError:
            out[row.key] = row.value
    return out


@router.put("")
async def update_settings(
    payload: dict,
    session: Session = Depends(get_session),
    admin: User = Depends(require_admin),
) -> dict:
    for key, value in payload.items():
        row = session.get(Setting, key) or Setting(key=key)
        row.value = json.dumps(value, ensure_ascii=False)
        session.add(row)
    session.commit()
    return {"ok": True}

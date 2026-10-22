"""系统级接口：总体信息、能力清单、工具清单、事件流（均按当前用户隔离）。"""
from __future__ import annotations

import json
from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from sqlmodel import Session, select

from ..config import APP_NAME, APP_SLUG, VERSION, settings
from ..core.auth import current_user
from ..core.capability import capabilities
from ..core.errors import ApiError
from ..core.tools import registry as tools
from ..db import get_session
from ..models import CapabilityState, Event, Provider, User

router = APIRouter(tags=["system"])


def _states(session: Session, user_id: int) -> dict[str, CapabilityState]:
    rows = session.exec(select(CapabilityState).where(CapabilityState.user_id == user_id)).all()
    return {row.id: row for row in rows}


def _enabled_ids(session: Session, user_id: int) -> set[str]:
    states = _states(session, user_id)
    return {cap.manifest.id for cap in capabilities.all() if states.get(cap.manifest.id, None) is None or states[cap.manifest.id].enabled}


@router.get("/info")
async def info(session: Session = Depends(get_session), user: User = Depends(current_user)) -> dict:
    providers = session.exec(select(Provider).where(Provider.user_id == user.id)).all()
    states = _states(session, user.id or 0)
    enabled = _enabled_ids(session, user.id or 0)
    visible_tools = [t for t in tools.list() if not t.capability or t.capability in enabled]
    return {
        "app": {"name": APP_NAME, "slug": APP_SLUG, "version": VERSION},
        "user": {
            "id": user.id,
            "username": user.username,
            "display_name": user.display_name or user.username,
            "role": user.role,
        },
        "data_dir": str(settings.data_dir.resolve()) if user.role == "admin" else None,
        "web_dist_exists": settings.web_dist.is_dir(),
        "providers": {
            "total": len(providers),
            "with_key": sum(1 for p in providers if p.api_key_enc),
            "default": next((p.name for p in providers if p.is_default), None),
        },
        "capabilities": len(capabilities.all()),
        "enabled_capabilities": len(enabled),
        "tools": len(visible_tools),
        "time": datetime.now(timezone.utc).isoformat(),
    }


@router.get("/capabilities", response_model=None)
async def list_capabilities(session: Session = Depends(get_session), user: User = Depends(current_user)) -> list[dict]:
    states = _states(session, user.id or 0)
    result = []
    for cap in capabilities.all():
        state = states.get(cap.manifest.id)
        result.append(
            {
                **cap.manifest.model_dump(),
                "enabled": state.enabled if state else True,
                "settings": json.loads(state.settings_json) if state else {},
                "has_tools": len(cap.tools()) > 0,
            }
        )
    return result


@router.put("/capabilities/{capability_id}")
async def update_capability(
    capability_id: str,
    payload: dict,
    session: Session = Depends(get_session),
    user: User = Depends(current_user),
) -> dict:
    cap = capabilities.get(capability_id)
    if cap is None:
        raise ApiError(f"能力不存在: {capability_id}", code="not_found", status=404)
    state = session.get(CapabilityState, (user.id or 0, capability_id)) or CapabilityState(
        user_id=user.id or 0, id=capability_id
    )
    if "enabled" in payload:
        state.enabled = bool(payload["enabled"])
    if "settings" in payload:
        incoming = payload["settings"] or {}
        schema = cap.manifest.settings_schema or {}
        props = schema.get("properties") or {}
        clean: dict = {}
        for key, value in incoming.items():
            prop = props.get(key)
            if prop is None:
                continue
            expected = prop.get("type")
            if expected == "boolean":
                clean[key] = bool(value)
            elif expected == "number":
                clean[key] = float(value)
            elif expected == "integer":
                clean[key] = int(value)
            elif expected == "string":
                clean[key] = str(value)
            else:
                clean[key] = value
        state.settings_json = json.dumps(clean, ensure_ascii=False)
    session.add(state)
    session.commit()
    return {"ok": True, "id": capability_id}


@router.get("/tools")
async def list_tools(session: Session = Depends(get_session), user: User = Depends(current_user)) -> list[dict]:
    states = _states(session, user.id or 0)
    enabled = _enabled_ids(session, user.id or 0)
    out = []
    for tool in tools.list():
        capability_enabled = (not tool.capability) or tool.capability in enabled
        out.append({**tool.as_public(), "capability_enabled": capability_enabled})
    return out


@router.get("/events")
async def list_events(
    limit: int = 20,
    session: Session = Depends(get_session),
    user: User = Depends(current_user),
) -> list[dict]:
    rows = session.exec(
        select(Event)
        .where(Event.user_id == (user.id or 0))
        .order_by(Event.id.desc())
        .limit(limit)
    ).all()
    return [
        {
            "id": e.id,
            "kind": e.kind,
            "message": e.message,
            "payload": e.payload,
            "created_at": e.created_at.isoformat() if e.created_at else None,
        }
        for e in rows
    ]

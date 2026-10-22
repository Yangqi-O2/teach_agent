"""系统级接口：健康检查、总体信息、能力清单、工具清单、事件流。"""
from __future__ import annotations

import json
from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from sqlmodel import Session, select

from ..config import APP_NAME, APP_SLUG, VERSION, settings
from ..core.capability import capabilities
from ..core.errors import ApiError
from ..core.tools import registry as tools
from ..db import get_session
from ..models import CapabilityState, Event, Provider

router = APIRouter(tags=["system"])


@router.get("/health")
async def health() -> dict:
    return {"ok": True, "name": APP_NAME, "version": VERSION}


@router.get("/info")
async def info(session: Session = Depends(get_session)) -> dict:
    providers = list(session.exec(select(Provider)).all())
    return {
        "app": {"name": APP_NAME, "slug": APP_SLUG, "version": VERSION},
        "data_dir": str(settings.data_dir.resolve()),
        "web_dist_exists": settings.web_dist.is_dir(),
        "providers": {
            "total": len(providers),
            "with_key": sum(1 for p in providers if p.api_key_enc),
            "default": next((p.name for p in providers if p.is_default), None),
        },
        "capabilities": len(capabilities.all()),
        "tools": len(tools.list()),
        "time": datetime.now(timezone.utc).isoformat(),
    }


def _state_map(session: Session) -> dict[str, CapabilityState]:
    return {s.id: s for s in session.exec(select(CapabilityState)).all()}


@router.get("/capabilities")
async def list_capabilities(session: Session = Depends(get_session)) -> list[dict]:
    states = _state_map(session)
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
) -> dict:
    cap = capabilities.get(capability_id)
    if cap is None:
        raise ApiError(f"能力不存在: {capability_id}", code="not_found", status=404)
    state = session.get(CapabilityState, capability_id) or CapabilityState(id=capability_id)
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
async def list_tools(session: Session = Depends(get_session)) -> list[dict]:
    states = _state_map(session)
    out = []
    for tool in tools.list():
        enabled = states.get(tool.capability).enabled if tool.capability in states else True
        out.append({**tool.as_public(), "capability_enabled": enabled})
    return out


@router.get("/events")
async def list_events(limit: int = 20, session: Session = Depends(get_session)) -> list[dict]:
    rows = session.exec(select(Event).order_by(Event.id.desc()).limit(limit)).all()
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

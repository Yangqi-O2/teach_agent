"""模型供应商：增删改查、设默认、连通性测试、拉模型列表。

每个用户只能看到、修改自己的供应商；API Key 只进不出。
"""
from __future__ import annotations

import json

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlmodel import Session, select

from ..core.auth import current_user
from ..core.crypto import decrypt, encrypt, hint
from ..core.errors import ApiError
from ..core.llm import LLMClient, ProviderRuntime, normalize_base_url
from ..db import get_session
from ..models import Event, Provider, User

router = APIRouter(prefix="/providers", tags=["providers"])


class ProviderIn(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    base_url: str = Field(min_length=1)
    api_key: str | None = None
    chat_model: str = ""
    embed_model: str | None = None
    is_default: bool = False


class ProviderPatch(BaseModel):
    name: str | None = None
    base_url: str | None = None
    api_key: str | None = None          # 不传=不变，空串=清除
    chat_model: str | None = None
    embed_model: str | None = None


def _out(p: Provider) -> dict:
    return {
        "id": p.id,
        "name": p.name,
        "base_url": p.base_url,
        "chat_model": p.chat_model,
        "embed_model": p.embed_model,
        "is_default": p.is_default,
        "has_key": bool(p.api_key_enc),
        "key_hint": p.key_hint,
        "created_at": p.created_at.isoformat() if p.created_at else None,
    }


def _runtime(p: Provider) -> ProviderRuntime:
    key = decrypt(p.api_key_enc) or ""
    return ProviderRuntime(
        id=p.id or 0,
        name=p.name,
        base_url=p.base_url,
        api_key=key,
        chat_model=p.chat_model,
        embed_model=p.embed_model,
    )


def _own(db: Session, user: User, provider_id: int) -> Provider:
    provider = db.get(Provider, provider_id)
    if provider is None or provider.user_id != (user.id or 0):
        raise ApiError("供应商不存在", code="not_found", status=404)
    return provider


def _audit(db: Session, user: User, message: str, payload: str | None = None) -> None:
    db.add(Event(user_id=user.id or 0, kind="provider", message=message, payload=payload))


@router.get("")
async def list_providers(
    session: Session = Depends(get_session), user: User = Depends(current_user)
) -> list[dict]:
    rows = session.exec(
        select(Provider)
        .where(Provider.user_id == (user.id or 0))
        .order_by(Provider.is_default.desc(), Provider.id)
    ).all()
    return [_out(p) for p in rows]


@router.post("")
async def create_provider(
    body: ProviderIn,
    session: Session = Depends(get_session),
    user: User = Depends(current_user),
) -> dict:
    mine = session.exec(select(Provider).where(Provider.user_id == (user.id or 0))).all()
    provider = Provider(
        user_id=user.id or 0,
        name=body.name.strip(),
        base_url=normalize_base_url(body.base_url),
        api_key_enc=encrypt(body.api_key),
        key_hint=hint(body.api_key),
        chat_model=body.chat_model.strip(),
        embed_model=(body.embed_model or "").strip() or None,
        is_default=(body.is_default or not mine),
    )
    if provider.is_default:
        for p in mine:
            p.is_default = False
            session.add(p)
    session.add(provider)
    _audit(session, user, f"添加供应商：{provider.name}")
    session.commit()
    session.refresh(provider)
    return _out(provider)


@router.put("/{provider_id}")
async def update_provider(
    provider_id: int,
    body: ProviderPatch,
    session: Session = Depends(get_session),
    user: User = Depends(current_user),
) -> dict:
    provider = _own(session, user, provider_id)
    fields = body.model_fields_set
    if body.name is not None:
        provider.name = body.name.strip()
    if body.base_url is not None:
        provider.base_url = normalize_base_url(body.base_url)
    if "api_key" in fields:
        if body.api_key == "":
            provider.api_key_enc = None
            provider.key_hint = None
        elif body.api_key:
            provider.api_key_enc = encrypt(body.api_key)
            provider.key_hint = hint(body.api_key)
    if body.chat_model is not None:
        provider.chat_model = body.chat_model.strip()
    if body.embed_model is not None:
        provider.embed_model = body.embed_model.strip() or None
    session.add(provider)
    _audit(session, user, f"更新供应商：{provider.name}")
    session.commit()
    session.refresh(provider)
    return _out(provider)


@router.delete("/{provider_id}")
async def delete_provider(
    provider_id: int,
    session: Session = Depends(get_session),
    user: User = Depends(current_user),
) -> dict:
    provider = _own(session, user, provider_id)
    was_default = provider.is_default
    session.delete(provider)
    session.commit()
    if was_default:
        nxt = session.exec(
            select(Provider).where(Provider.user_id == (user.id or 0)).order_by(Provider.id)
        ).first()
        if nxt:
            nxt.is_default = True
            session.add(nxt)
            session.commit()
    return {"ok": True}


@router.post("/{provider_id}/default")
async def set_default(
    provider_id: int,
    session: Session = Depends(get_session),
    user: User = Depends(current_user),
) -> dict:
    provider = _own(session, user, provider_id)
    for p in session.exec(select(Provider).where(Provider.user_id == (user.id or 0))).all():
        p.is_default = p.id == provider_id
        session.add(p)
    session.commit()
    return {"ok": True}


@router.post("/{provider_id}/test")
async def test_provider(
    provider_id: int,
    session: Session = Depends(get_session),
    user: User = Depends(current_user),
) -> dict:
    provider = _own(session, user, provider_id)
    runtime = _runtime(provider)
    if not runtime.api_key:
        return {"ok": False, "error": "还没有填写 API Key", "latency_ms": 0, "models": []}
    result = await LLMClient(runtime, timeout=20).test()
    session.add(
        Event(
            user_id=user.id or 0,
            kind="provider",
            message=f"测试连接：{provider.name} → {'成功' if result.get('ok') else '失败'}",
            payload=json.dumps({"latency_ms": result.get("latency_ms")}, ensure_ascii=False),
        )
    )
    session.commit()
    return result


@router.get("/{provider_id}/models")
async def list_models(
    provider_id: int,
    session: Session = Depends(get_session),
    user: User = Depends(current_user),
) -> dict:
    provider = _own(session, user, provider_id)
    runtime = _runtime(provider)
    if not runtime.api_key:
        raise ApiError("还没有填写 API Key", code="no_api_key", status=409)
    try:
        models = await LLMClient(runtime, timeout=20).list_models()
    except Exception as exc:  # noqa: BLE001
        raise ApiError(f"拉取模型列表失败：{exc}", code="models_error", status=502) from exc
    return {"models": models}

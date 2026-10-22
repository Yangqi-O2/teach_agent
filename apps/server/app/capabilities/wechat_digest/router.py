"""群聊简报接口，统一挂载在 ``/api/c/wechat_digest``（契约 §3）。

错误一律走核心 ``ApiError``：

- 数据源为空 / 解析不出消息 → 422 ``empty_source``
- 超出字符上限 → 413 ``too_long``
- 没有可用模型供应商 → 409 ``no_provider``（由核心 ``load_provider`` 抛）
- 记录不存在 → 404 ``not_found``
"""
from __future__ import annotations

from urllib.parse import quote

from fastapi import APIRouter, Depends, Query, Response
from pydantic import BaseModel, Field
from sqlmodel import Session, col, select

from ...core.auth import current_user
from ...core.errors import ApiError
from ...core.llm import load_provider
from ...db import get_session
from ...models import User
from . import service
from .models import Digest
from .pipeline import exporters
from .pipeline.prompts import STYLES, list_styles
from .sources import list_sources

router = APIRouter(tags=["wechat_digest"])


# ---------------------------------------------------------------- 请求模型


class PreviewIn(BaseModel):
    source: str = "paste"
    params: dict = Field(default_factory=dict)


class DigestIn(BaseModel):
    source: str = "paste"
    params: dict = Field(default_factory=dict)
    style: str | None = None
    provider_id: int | None = None


# ---------------------------------------------------------------- 元数据


@router.get("/options")
async def get_options(
    session: Session = Depends(get_session), user: User = Depends(current_user)
) -> dict:
    """页面启动元数据：数据源、总结风格、能力设置。"""
    settings = service.load_settings(session, user.id or 0)
    return {
        "sources": list_sources(),
        "styles": list_styles(),
        "settings": {
            "default_style": settings["default_style"],
            "max_chars": settings["max_chars"],
            "history_limit": settings["history_limit"],
        },
    }


# ---------------------------------------------------------------- 预览


@router.post("/preview")
async def preview(
    body: PreviewIn,
    session: Session = Depends(get_session),
    user: User = Depends(current_user),
) -> dict:
    """只解析 + 清洗，不调用模型。"""
    settings = service.load_settings(session, user.id or 0)
    prepared = service.prepare(body.source, body.params, settings["max_chars"])
    return service.preview_of(prepared)


# ---------------------------------------------------------------- 创建 + 历史


@router.post("/digests", status_code=202)
async def create_digest(
    body: DigestIn,
    session: Session = Depends(get_session),
    user: User = Depends(current_user),
) -> dict:
    """校验通过后创建记录并提交后台任务，返回 202。"""
    settings = service.load_settings(session, user.id or 0)

    style = (body.style or "").strip() or settings["default_style"]
    if style not in STYLES:
        raise ApiError(f"未知的总结风格：{style}", code="invalid_style", status=422)

    # 先解析清洗（文本可解析、长度都在这里校验），再确认有可用模型
    prepared = service.prepare(body.source, body.params, settings["max_chars"])
    runtime = load_provider(session, body.provider_id, user.id or 0)  # 没有供应商 → 409 no_provider

    digest, job_id = service.enqueue_digest(
        session,
        prepared=prepared,
        style=style,
        runtime=runtime,
        provider_id=body.provider_id,
        history_limit=settings["history_limit"],
        user_id=user.id or 0,
    )
    return {"ok": True, "job_id": job_id, "digest": service.summary_of(digest)}


@router.get("/digests")
async def list_digests(
    limit: int = Query(20, ge=1, le=100),
    q: str = "",
    session: Session = Depends(get_session),
    user: User = Depends(current_user),
) -> list[dict]:
    """历史列表；``q`` 对 title / group_name 做 LIKE 过滤。"""
    stmt = select(Digest).where(Digest.user_id == (user.id or 0))
    keyword = (q or "").strip()
    if keyword:
        like = f"%{keyword}%"
        stmt = stmt.where(
            col(Digest.title).like(like) | col(Digest.group_name).like(like)  # type: ignore[operator]
        )
    stmt = stmt.order_by(col(Digest.created_at).desc(), col(Digest.id).desc()).limit(limit)
    return [service.summary_of(row) for row in session.exec(stmt).all()]


# ---------------------------------------------------------------- 详情 / 删除 / 导出


def _get_digest(session: Session, digest_id: int, user_id: int) -> Digest:
    digest = session.get(Digest, digest_id)
    if digest is None or digest.user_id != user_id:
        raise ApiError("简报不存在", code="not_found", status=404)
    return digest


@router.get("/digests/{digest_id}")
async def get_digest(
    digest_id: int,
    session: Session = Depends(get_session),
    user: User = Depends(current_user),
) -> dict:
    return service.detail_of(_get_digest(session, digest_id, user.id or 0))


@router.delete("/digests/{digest_id}")
async def delete_digest(
    digest_id: int,
    session: Session = Depends(get_session),
    user: User = Depends(current_user),
) -> dict:
    digest = _get_digest(session, digest_id, user.id or 0)
    session.delete(digest)
    session.commit()
    return {"ok": True}


@router.get("/digests/{digest_id}/export")
async def export_digest(
    digest_id: int,
    fmt: str = Query("txt", alias="format"),
    session: Session = Depends(get_session),
    user: User = Depends(current_user),
) -> Response:
    """导出文件下载：txt / json / md / ics。"""
    key = exporters.normalize_format(fmt)
    if not exporters.is_supported(key):
        raise ApiError(
            f"不支持的导出格式：{fmt}（可选 {', '.join(exporters.EXPORTERS)}）",
            code="invalid_format",
            status=422,
        )
    digest = _get_digest(session, digest_id, user.id or 0)
    content = service.export_content(digest, key)
    filename = service.export_filename(digest, key)
    # Content-Disposition 同时给 ASCII 兜底名与 RFC 5987 的 UTF-8 中文名
    disposition = (
        f'attachment; filename="wechat-digest-{digest.id}.{exporters.extension(key)}"; '
        f"filename*=UTF-8''{quote(filename, safe='')}"
    )
    return Response(
        content=content.encode("utf-8"),
        media_type=exporters.media_type(key),
        headers={"Content-Disposition": disposition},
    )

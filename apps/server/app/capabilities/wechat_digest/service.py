"""群聊简报的可复用业务逻辑：解析 / 清洗 / 落库 / 导出。

router（接口）、jobs（后台任务）、capability（Agent 工具）三方共用，避免逻辑重复。
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sqlmodel import Session, col, select

from ...core.errors import ApiError
from ...core.jobs import jobs as job_manager
from ...models import CapabilityState
from .models import Digest
from .pipeline import exporters
from .pipeline.cleaners import clean_groups
from .pipeline.prompts import DEFAULT_STYLE, STYLES
from .sources import get_source
from .sources.base import Message

log = logging.getLogger(__name__)

CAPABILITY_ID = "wechat_digest"
JOB_TYPE = "wechat_digest"

# 能力设置的默认值（与 manifest.settings_schema 保持一致，契约 §8）
DEFAULT_SETTINGS: dict[str, Any] = {
    "default_style": DEFAULT_STYLE,
    "max_chars": 60000,
    "history_limit": 30,
}

SAMPLE_LIMIT = 5


def now_iso() -> str:
    """本地时间 ISO 字符串（秒级）：``2026-10-22T20:31:00``，与契约示例一致。"""
    return datetime.now().isoformat(timespec="seconds")


# ---------------------------------------------------------------- 设置


def load_settings(session: Session) -> dict[str, Any]:
    """读取能力设置；缺失 / 非法值一律用默认值兜底。"""
    settings = dict(DEFAULT_SETTINGS)
    state = session.get(CapabilityState, CAPABILITY_ID)
    if state is None or not state.settings_json:
        return settings
    try:
        stored = json.loads(state.settings_json)
    except (json.JSONDecodeError, TypeError):
        log.warning("wechat_digest 设置不是合法 JSON，已使用默认值")
        return settings
    if not isinstance(stored, dict):
        return settings

    for key, default in DEFAULT_SETTINGS.items():
        if key not in stored:
            continue
        value = stored[key]
        if isinstance(default, int):
            try:
                settings[key] = max(1, int(value))
            except (TypeError, ValueError):
                continue
        else:
            text = str(value or "").strip()
            if text:
                settings[key] = text
    if settings["default_style"] not in STYLES:
        settings["default_style"] = DEFAULT_STYLE
    return settings


# ---------------------------------------------------------------- 解析 + 清洗


@dataclass
class Prepared:
    """一次「解析 + 清洗」的结果（预览与生成共用）。"""

    source: str
    params: dict[str, Any]
    group_name: str
    raw: dict[str, list[Message]] = field(default_factory=dict)
    cleaned: dict[str, list[Message]] = field(default_factory=dict)
    stats: dict[str, dict] = field(default_factory=dict)

    @property
    def total_before(self) -> int:
        return sum(int(st.get("before", 0)) for st in self.stats.values())

    @property
    def total_after(self) -> int:
        return sum(int(st.get("after", 0)) for st in self.stats.values())

    @property
    def total_dropped(self) -> int:
        return sum(int(st.get("dropped", 0)) for st in self.stats.values())

    def sample(self, limit: int = SAMPLE_LIMIT) -> list[dict]:
        """清洗后前 N 条，拆成 time / sender / text 三元组（契约 §3.2）。"""
        out: list[dict] = []
        for messages in self.cleaned.values():
            for msg in messages:
                if len(out) >= limit:
                    return out
                out.append({"time": msg.time, "sender": msg.sender, "text": msg.text})
        return out


def prepare(
    source_id: str | None,
    params: dict[str, Any] | None,
    max_chars: int | None = None,
) -> Prepared:
    """取数据源 → 校验 → 解析 → 多级清洗。解析不出消息抛 ``empty_source``。"""
    source = get_source(source_id)
    available, hint = source.available()
    if not available:
        raise ApiError(hint or f"数据源「{source.name}」当前不可用", code="source_unavailable", status=422)

    params = dict(params or {})
    if not params:
        raise ApiError("数据源为空，请先粘贴聊天记录或填写参数", code="empty_source", status=422)

    text = params.get("text")
    if isinstance(text, str):
        if not text.strip():
            raise ApiError("聊天记录为空，请先粘贴微信群 / QQ 群的聊天记录", code="empty_source", status=422)
        limit = int(max_chars or DEFAULT_SETTINGS["max_chars"])
        if len(text) > limit:
            raise ApiError(
                f"聊天记录 {len(text)} 字，超过单次上限 {limit} 字，请分几次总结",
                code="too_long",
                status=413,
            )

    try:
        raw = source.load(params)
    except ApiError:
        raise
    except ValueError as exc:
        raise ApiError(
            str(exc) or "没有从文本里解析出任何消息，支持 [时间] 昵称: 内容 等格式",
            code="empty_source",
            status=422,
        ) from exc
    except Exception as exc:  # noqa: BLE001 - 数据源实现未知异常统一转 422
        log.exception("数据源 %s 解析失败", source.id)
        raise ApiError(f"解析聊天记录失败：{exc}", code="source_error", status=422) from exc

    cleaned, stats = clean_groups(raw)
    if not any(cleaned.values()):
        raise ApiError(
            "聊天记录里没有可总结的有效内容（可能全是表情、收到、拍一拍等），换一段文本试试",
            code="empty_source",
            status=422,
        )

    group_name = str(params.get("group_name") or "").strip() or next(iter(raw), "粘贴内容")
    return Prepared(
        source=source.id,
        params=params,
        group_name=group_name,
        raw=raw,
        cleaned=cleaned,
        stats=stats,
    )


def preview_of(prepared: Prepared) -> dict:
    """``POST /preview`` 响应（契约 §3.2）。"""
    groups = []
    for name, st in prepared.stats.items():
        groups.append(
            {
                "name": name,
                "before": int(st.get("before", 0)),
                "after": int(st.get("after", 0)),
                "dropped": int(st.get("dropped", 0)),
                "drop_reasons": dict(st.get("drop_reasons") or {}),
            }
        )
    return {
        "ok": True,
        "source": prepared.source,
        "total_before": prepared.total_before,
        "total_after": prepared.total_after,
        "groups": groups,
        "sample": prepared.sample(),
    }


# ---------------------------------------------------------------- 落库


def create_digest(
    session: Session,
    *,
    prepared: Prepared,
    style: str,
    runtime: Any,
) -> Digest:
    """创建一条 ``queued`` 简报记录并返回（还没提交任务）。"""
    now = now_iso()
    group_name = prepared.group_name or "粘贴内容"
    digest = Digest(
        title=f"{group_name} · 群聊简报",
        source=prepared.source,
        group_name=group_name,
        style=style,
        status="queued",
        provider=str(getattr(runtime, "name", "") or ""),
        model=str(getattr(runtime, "chat_model", "") or ""),
        message_count=prepared.total_before,
        kept_count=prepared.total_after,
        result_json="{}",
        created_at=now,
        updated_at=now,
    )
    session.add(digest)
    session.commit()
    session.refresh(digest)
    return digest


def enqueue_digest(
    session: Session,
    *,
    prepared: Prepared,
    style: str,
    runtime: Any,
    provider_id: int | None = None,
    history_limit: int = DEFAULT_SETTINGS["history_limit"],
) -> tuple[Digest, str]:
    """创建记录 + 提交后台任务，返回 ``(digest, job_id)``。"""
    digest = create_digest(session, prepared=prepared, style=style, runtime=runtime)
    assert digest.id is not None
    job_id = job_manager.submit(
        JOB_TYPE,
        f"群聊简报：{digest.group_name}",
        payload={
            "digest_id": digest.id,
            "source": prepared.source,
            "params": prepared.params,
            "style": style,
            "provider_id": provider_id,
        },
    )
    digest.job_id = job_id
    digest.updated_at = now_iso()
    session.add(digest)
    session.commit()
    session.refresh(digest)
    log.info("群聊简报已入队: digest=%s job=%s", digest.id, job_id)
    trim_history(session, history_limit, keep_id=digest.id)
    return digest, job_id


def trim_history(session: Session, limit: int, keep_id: int | None = None) -> int:
    """只保留最近 ``limit`` 条已结束的简报，超出的删掉（契约 §8 history_limit）。"""
    limit = max(1, int(limit or DEFAULT_SETTINGS["history_limit"]))
    rows = session.exec(
        select(Digest).order_by(col(Digest.created_at).desc(), col(Digest.id).desc())
    ).all()
    removed = 0
    for index, row in enumerate(rows):
        if index < limit or row.id == keep_id:
            continue
        if row.status in ("queued", "running"):
            continue
        session.delete(row)
        removed += 1
    if removed:
        session.commit()
        log.info("已清理 %d 条历史简报", removed)
    return removed


def set_digest_status(
    session: Session,
    digest_id: int,
    status: str,
    *,
    error: str | None = None,
    clear_error: bool = False,
) -> bool:
    """更新简报状态（jobs 出错 / 取消时用）；记录不存在返回 False。"""
    digest = session.get(Digest, digest_id)
    if digest is None:
        return False
    digest.status = status
    if error is not None:
        digest.error = error
    elif clear_error:
        digest.error = None
    digest.updated_at = now_iso()
    session.add(digest)
    session.commit()
    return True


def build_payload(
    *,
    source: str,
    group_name: str,
    style: str,
    provider: str,
    model: str,
    stats_before: int,
    stats_after: int,
    chunks: int,
    groups: list[dict],
    created_at: str | None = None,
) -> dict:
    """构造 ``DigestPayload``（契约 §4.2）。"""
    before = int(stats_before or 0)
    after = int(stats_after or 0)
    return {
        "version": 1,
        "source": source,
        "group_name": group_name,
        "style": style,
        "provider": provider,
        "model": model,
        "created_at": created_at or now_iso(),
        "stats": {
            "before": before,
            "after": after,
            "dropped": max(0, before - after),
            "chunks": int(chunks or 0),
        },
        "groups": groups,
    }


def save_payload(session: Session, digest_id: int, payload: dict) -> bool:
    """把结果写入 ``result_json`` 并置 ``status=done``。"""
    digest = session.get(Digest, digest_id)
    if digest is None:
        log.warning("保存简报失败：记录 %s 不存在（可能已被删除）", digest_id)
        return False
    stats = payload.get("stats") or {}
    digest.result_json = json.dumps(payload, ensure_ascii=False)
    digest.status = "done"
    digest.error = None
    digest.message_count = int(stats.get("before", digest.message_count) or 0)
    digest.kept_count = int(stats.get("after", digest.kept_count) or 0)
    digest.updated_at = now_iso()
    session.add(digest)
    session.commit()
    return True


# ---------------------------------------------------------------- 对外结构


def resolve_result(digest: Digest) -> dict | None:
    """解析 ``result_json``；不是合法 JSON 或为空时返回 None。"""
    try:
        payload = json.loads(digest.result_json or "{}")
    except (json.JSONDecodeError, TypeError):
        return None
    return payload if isinstance(payload, dict) and payload else None


def one_line_of(digest: Digest) -> str:
    """从结果里取「一句话」（表里不单存该列，按契约 §3.5 / §3.6 派生）。"""
    payload = resolve_result(digest) or {}
    for group in payload.get("groups") or []:
        if isinstance(group, dict) and str(group.get("one_line") or "").strip():
            return str(group["one_line"]).strip()
    return ""


def summary_of(digest: Digest) -> dict:
    """``GET /digests`` 列表项（契约 §3.5）。"""
    return {
        "id": digest.id,
        "title": digest.title,
        "group_name": digest.group_name,
        "source": digest.source,
        "style": digest.style,
        "status": digest.status,
        "provider": digest.provider,
        "model": digest.model,
        "message_count": digest.message_count,
        "kept_count": digest.kept_count,
        "one_line": one_line_of(digest),
        "created_at": digest.created_at,
    }


def detail_of(digest: Digest) -> dict:
    """``GET /digests/{id}`` 详情（契约 §3.6）；未完成时 result 为 null。"""
    result = resolve_result(digest) if digest.status == "done" else None
    return {
        "id": digest.id,
        "title": digest.title,
        "group_name": digest.group_name,
        "source": digest.source,
        "style": digest.style,
        "status": digest.status,
        "job_id": digest.job_id,
        "provider": digest.provider,
        "model": digest.model,
        "message_count": digest.message_count,
        "kept_count": digest.kept_count,
        "one_line": one_line_of(digest),
        "error": digest.error,
        "created_at": digest.created_at,
        "updated_at": digest.updated_at,
        "result": result,
    }


# ---------------------------------------------------------------- 导出


def export_content(digest: Digest, fmt: str | None) -> str:
    """渲染导出内容；未完成或格式不支持时抛 ApiError。"""
    key = exporters.normalize_format(fmt)
    if not exporters.is_supported(key):
        raise ApiError(f"不支持的导出格式：{key}", code="invalid_format", status=422)
    if digest.status != "done":
        raise ApiError("简报还没生成完成，暂时无法导出", code="not_ready", status=409)
    payload = resolve_result(digest)
    if payload is None:
        raise ApiError("简报结果为空，无法导出", code="empty_result", status=409)
    return exporters.render(key, payload)


def export_filename(digest: Digest, fmt: str | None) -> str:
    """导出文件名（中文安全，配合 filename*=UTF-8''...）。"""
    base = (digest.title or digest.group_name or "群聊简报").strip()
    for ch in ('/', "\\", "\n", "\r", "\t"):
        base = base.replace(ch, "-")
    created = (digest.created_at or "")[:10]
    stem = f"{base}-{created}" if created else base
    return f"{stem}.{exporters.extension(fmt)}"

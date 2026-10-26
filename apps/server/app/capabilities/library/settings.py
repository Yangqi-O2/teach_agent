"""教材库按用户的设置（存在主站 `capability_state`，前端能力面板自动渲染）。"""
from __future__ import annotations

import json
import logging

from sqlmodel import Session

from ...db import engine
from ...models import CapabilityState

log = logging.getLogger(__name__)

CAPABILITY_ID = "library"

# 默认值 == capability.py 里 settings_schema 的 default，改一处要同步另一处
DEFAULTS: dict = {
    "default_visibility": "private",   # 上传默认是否公开
    "ocr_mode": "auto",                # off | auto | force
    "qa_top_k": 6,                     # 每次问答检索几段
    "max_upload_mb": 60,
    "low_confidence_warn": 0.55,       # OCR 置信度低于此值就提示核对
}


def default_settings() -> dict:
    return dict(DEFAULTS)


def get_settings(user_id: int) -> dict:
    merged = default_settings()
    if not user_id:
        return merged
    try:
        with Session(engine) as session:
            state = session.get(CapabilityState, (user_id, CAPABILITY_ID))
    except Exception:  # noqa: BLE001
        log.exception("读取 library 能力设置失败（已用默认值）")
        return merged
    if state is None or not state.settings_json:
        return merged
    try:
        raw = json.loads(state.settings_json)
    except (TypeError, ValueError):
        return merged
    if not isinstance(raw, dict):
        return merged
    for key, default in DEFAULTS.items():
        if key not in raw or raw[key] is None:
            continue
        value = raw[key]
        try:
            if isinstance(default, bool):
                merged[key] = value if isinstance(value, bool) else str(value).lower() in {"1", "true", "yes", "on"}
            elif isinstance(default, int) and not isinstance(default, bool):
                merged[key] = int(value)
            elif isinstance(default, float):
                merged[key] = float(value)
            else:
                merged[key] = str(value)
        except (TypeError, ValueError):
            continue
    return merged

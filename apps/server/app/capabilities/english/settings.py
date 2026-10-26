"""english 能力按用户的设置（存在主站 `capability_state` 里，前端能力面板自动渲染）。

所有 AI 相关参数都从这里读，不再走环境变量——主站的模型接入是按用户配置的。
"""
from __future__ import annotations

import json
import logging

from sqlmodel import Session

from ...db import engine
from ...models import CapabilityState

log = logging.getLogger(__name__)

CAPABILITY_ID = "english"

# 默认值 == capability.py 里 settings_schema 的 default，两边保持一致
DEFAULTS: dict = {
    "daily_quota": 30,            # 每天对话轮数上限（assistant 消息数）
    "partner_model": "",          # 角色扮演模型；留空=跟随供应商默认模型
    "planner_model": "",          # 规划 / 纠错 / 记忆 / 摘要 / 释义模型
    "fallback_model": "",         # 预算降级时用的便宜模型；留空=不降级
    "monthly_token_budget": 2_000_000,
    "price_in_per_m": 2.4,        # 元 / 百万 token
    "price_out_per_m": 9.6,
    "repair_enabled": True,       # 回复质量不达标记时静默重写一次
    "mock_mode": False,           # 离线演示：不调用真实模型（内容为假）
}


def default_settings() -> dict:
    return dict(DEFAULTS)


def get_settings(user_id: int) -> dict:
    """DEFAULTS ← 用户保存的设置（逐项覆盖，类型按默认值矫正）。"""
    merged = default_settings()
    if not user_id:
        return merged
    try:
        with Session(engine) as session:
            state = session.get(CapabilityState, (user_id, CAPABILITY_ID))
    except Exception:  # noqa: BLE001
        log.exception("读取 english 能力设置失败（已用默认值）")
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
        if key not in raw:
            continue
        value = raw[key]
        if value is None:
            continue
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

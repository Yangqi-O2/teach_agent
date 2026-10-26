"""成本与预算。

早期最该盯的不是「总共花了多少」，而是「单轮多少钱」和「预算还剩几天」。
所以这里按轮记账，月底按累计判断要不要降级模型（照搬 `api/src/agents/budget.ts`）。

单位约定：`cost_of` 返回**元**（float），router 落库时再转 `cost_micros = round(cost*1e6)`。
"""
from __future__ import annotations

import math

from ..store import month_start_iso, one

# 粗估 token：英文约 4 字符/token，中文约 1.5 字符/token，取折中 3
CHARS_PER_TOKEN = 3

# 默认单价（元 / 百万 token），与 settings.DEFAULTS 保持一致
DEFAULT_PRICE_IN_PER_M = 2.4
DEFAULT_PRICE_OUT_PER_M = 9.6
DEFAULT_MONTHLY_BUDGET = 2_000_000


def est_tokens(text: str) -> int:
    """粗估 token 数（空字符串为 0）。"""
    if not text:
        return 0
    return math.ceil(len(text) / CHARS_PER_TOKEN)


def cost_of(
    tokens_in: int,
    tokens_out: int,
    price_in: float = DEFAULT_PRICE_IN_PER_M,
    price_out: float = DEFAULT_PRICE_OUT_PER_M,
) -> float:
    """按「元 / 百万 token」单价算一次调用的成本（元）。"""
    return (int(tokens_in) * float(price_in) + int(tokens_out) * float(price_out)) / 1_000_000


def budget_decision(used: int, limit: int) -> dict:
    """超过 90% 降到备用模型；超过 100% 也继续服务，但只用便宜模型。"""
    limit = int(limit)
    used = int(used)
    ratio = 0.0 if limit <= 0 else used / limit
    return {
        "used": used,
        "limit": limit,
        "ratio": ratio,
        "degrade": limit > 0 and ratio >= 0.9,
    }


def month_tokens(user_id: int) -> int:
    """本自然月该用户所有 assistant 消息的 token 合计（UTC 月初起算）。"""
    row = one(
        "SELECT sum(coalesce(m.tokens_in, 0) + coalesce(m.tokens_out, 0)) AS total "
        "FROM english_messages m JOIN english_conversations c ON c.id = m.conversation_id "
        "WHERE c.user_id = :user_id AND m.role = 'assistant' AND m.created_at > :month_start",
        user_id=user_id,
        month_start=month_start_iso(),
    )
    return int((row or {}).get("total") or 0)


def check_budget(user_id: int, settings: dict | None = None) -> dict:
    """按月累计 token 判定是否要降级；settings 省略时读该用户的能力设置。"""
    if settings is None:
        from ..settings import get_settings

        settings = get_settings(user_id)
    limit = int(settings.get("monthly_token_budget") or 0)
    return budget_decision(month_tokens(user_id), limit)

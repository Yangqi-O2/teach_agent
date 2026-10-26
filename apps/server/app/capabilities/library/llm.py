"""教材库取模型客户端。

和 english 能力的差别：这边只有一个用途（问答），不需要按角色分模型，
所以只要能拿到「当前用户的默认供应商」就够了；拿不到时返回 None，
让检索退化为纯关键词、让问答给出明确提示，而不是整个能力起不来。
"""
from __future__ import annotations

from typing import Any

from sqlmodel import Session

from ...core.llm import LLMClient, load_provider
from ...core.errors import ApiError
from ...db import engine


def load_llm(user_id: int, provider_id: int | None = None) -> LLMClient:
    with Session(engine) as session:
        runtime = load_provider(session, provider_id=provider_id, user_id=user_id)
    return LLMClient(runtime, timeout=90.0)


def try_load_llm(user_id: int) -> Any:
    """拿不到供应商就返回 None——用于「向量检索可选」这种场景。"""
    try:
        return load_llm(user_id)
    except ApiError:
        return None

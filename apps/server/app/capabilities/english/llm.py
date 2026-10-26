"""供应商适配：把主站「按用户配置的 OpenAI 兼容供应商」包成 english 需要的最小接口。

原项目用环境变量区分 partner / planner 两个模型；这里改为：
- 模型名来自能力设置（留空则跟随该用户默认供应商的 chat_model）；
- 预算降级时切 fallback_model；
- 无供应商 / 无 Key 抛主站 ApiError（与 wechat_digest 能力一致），前端引导去「设置 → 模型接入」；
- 离线演示可打开 mock_mode，不产生任何真实调用（内容为假，不要用于验收质量）。
"""
from __future__ import annotations

import json
import logging
import re
from collections.abc import AsyncIterator
from dataclasses import replace
from typing import Any

from pydantic import BaseModel, ValidationError
from sqlmodel import Session

from ...core.llm import LLMClient, ProviderRuntime, load_provider
from ...db import engine
from . import mock as mock_module
from .settings import get_settings

log = logging.getLogger(__name__)


class LLMError(Exception):
    """模型调用 / 结构化输出失败。retryable=False 表示重试也没用（如两次都不合法）。"""

    def __init__(self, message: str, retryable: bool = True):
        super().__init__(message)
        self.retryable = retryable


def safe_json(text: str) -> Any:
    """把模型输出里的 JSON 抠出来：容忍 ```json 围栏与前后废话。"""
    trimmed = (text or "").strip()
    trimmed = re.sub(r"^```(?:json)?", "", trimmed, flags=re.IGNORECASE).strip()
    trimmed = re.sub(r"```$", "", trimmed).strip()
    try:
        return json.loads(trimmed)
    except ValueError:
        start, end = trimmed.find("{"), trimmed.rfind("}")
        if start >= 0 and end > start:
            try:
                return json.loads(trimmed[start : end + 1])
            except ValueError:
                return None
        return None


class EnglishLLM:
    """一次请求生命周期内复用的轻量封装。"""

    def __init__(self, client: LLMClient, *, model: str, name: str | None = None, mock: bool = False):
        self.client = client
        self.model = model
        self.name = name or model
        self.mock = mock

    # —— 流式对话（角色扮演）——
    async def stream(
        self, system: str, messages: list[dict], max_tokens: int = 600
    ) -> AsyncIterator[str]:
        payload = [{"role": "system", "content": system}, *messages]
        async for delta in self.client.stream(
            payload, model=self.model, temperature=0.9, max_tokens=max_tokens
        ):
            yield delta

    # —— 结构化输出（规划 / 纠错 / 记忆 / 摘要 / 释义）——
    async def json(
        self,
        system: str,
        user: str,
        schema: type[BaseModel],
        max_tokens: int = 1200,
    ) -> BaseModel:
        """国内模型没有严格 json_schema，只能 json_object + 校验 + 反馈重试一次。"""
        feedback = ""
        for attempt in range(2):
            prompt = user
            if feedback:
                prompt = f"{user}\n\n上一次输出不合格：{feedback}\n只输出合法 JSON，不要任何解释。"
            result = await self.client.chat(
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": prompt},
                ],
                model=self.model,
                temperature=0.7,
                max_tokens=max_tokens,
                response_format={"type": "json_object"},
            )
            raw = result.get("content") or ""
            parsed = safe_json(raw)
            if parsed is not None:
                try:
                    return schema.model_validate(parsed)
                except ValidationError as exc:
                    feedback = json.dumps(exc.errors()[:3], ensure_ascii=False, default=str)
                    log.warning("english.json 校验失败（第 %d 次）: %s", attempt + 1, feedback[:200])
                    continue
            feedback = "输出不是合法 JSON"
            log.warning("english.json 不是合法 JSON（第 %d 次）", attempt + 1)
        raise LLMError("模型连续两次未产出合法 JSON", retryable=False)


def get_llm(user_id: int, kind: str = "partner", *, degrade: bool = False) -> EnglishLLM:
    """按用户设置取一个 LLM。kind: partner（角色扮演）| planner（结构化任务）。"""
    settings = get_settings(user_id)
    if settings.get("mock_mode"):
        return mock_module.MockLLM()  # type: ignore[return-value]

    kind = "planner" if kind == "planner" else "partner"
    model_override = str(settings.get(f"{kind}_model") or "").strip()
    fallback = str(settings.get("fallback_model") or "").strip()

    with Session(engine) as session:
        runtime: ProviderRuntime = load_provider(session, user_id=user_id)

    model = model_override or runtime.chat_model
    if degrade and fallback:
        model = fallback
    client = LLMClient(replace(runtime, chat_model=model), timeout=60.0)
    return EnglishLLM(client, model=model)

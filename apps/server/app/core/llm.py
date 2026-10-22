"""OpenAI 兼容模型客户端：一家配置通吃 DeepSeek / OpenAI / Kimi / 通义 / Ollama…

只依赖 base_url + api_key，把各家差异挡在外面。
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from urllib.parse import urlparse

from openai import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    AsyncOpenAI,
    AuthenticationError,
    NotFoundError,
    RateLimitError,
)
from sqlmodel import Session, select

from ..models import Provider
from .crypto import decrypt
from .errors import ApiError

log = logging.getLogger(__name__)


@dataclass
class ProviderRuntime:
    id: int
    name: str
    base_url: str
    api_key: str
    chat_model: str
    embed_model: str | None = None


def normalize_base_url(raw: str) -> str:
    url = (raw or "").strip().rstrip("/")
    if not url:
        raise ApiError("Base URL 不能为空", code="invalid_base_url")
    if "://" not in url:
        url = "https://" + url
    parsed = urlparse(url)
    if parsed.path in ("", "/"):
        url += "/v1"
    return url


def load_provider(session: Session, provider_id: int | None = None) -> ProviderRuntime:
    provider: Provider | None = None
    if provider_id is not None:
        provider = session.get(Provider, provider_id)
    else:
        provider = session.exec(select(Provider).where(Provider.is_default == True)).first()  # noqa: E712
        if provider is None:
            provider = session.exec(select(Provider).order_by(Provider.id)).first()
    if provider is None:
        raise ApiError(
            "还没有配置模型供应商，请先在「设置 → 模型接入」里添加一个",
            code="no_provider",
            status=409,
        )
    api_key = decrypt(provider.api_key_enc) or ""
    if not api_key:
        raise ApiError(
            f"供应商「{provider.name}」缺少 API Key",
            code="no_api_key",
            status=409,
        )
    return ProviderRuntime(
        id=provider.id or 0,
        name=provider.name,
        base_url=normalize_base_url(provider.base_url),
        api_key=api_key,
        chat_model=provider.chat_model,
        embed_model=provider.embed_model,
    )


class LLMClient:
    def __init__(self, runtime: ProviderRuntime, timeout: float = 60.0):
        self.runtime = runtime
        self.client = AsyncOpenAI(
            base_url=runtime.base_url,
            api_key=runtime.api_key,
            timeout=timeout,
            max_retries=1,
        )

    # —— 探测 / 测试 ——
    async def list_models(self) -> list[str]:
        resp = await self.client.models.list()
        return sorted({m.id for m in resp.data})

    async def test(self) -> dict:
        started = time.perf_counter()
        models: list[str] = []
        models_error: str | None = None
        chat_ok: bool | None = None
        chat_error: str | None = None
        try:
            models = await self.list_models()
        except Exception as exc:  # noqa: BLE001
            models_error = self._friendly(exc)
        if self.runtime.chat_model:
            try:
                await self.client.chat.completions.create(
                    model=self.runtime.chat_model,
                    messages=[{"role": "user", "content": "ping"}],
                    max_tokens=1,
                )
                chat_ok = True
            except Exception as exc:  # noqa: BLE001
                chat_ok = False
                chat_error = self._friendly(exc)
        latency_ms = int((time.perf_counter() - started) * 1000)
        ok = chat_ok is True or (chat_ok is None and models_error is None)
        return {
            "ok": ok,
            "latency_ms": latency_ms,
            "models": models,
            "models_error": models_error,
            "chat_ok": chat_ok,
            "chat_error": chat_error,
            "error": None if ok else (chat_error or models_error),
        }

    # —— 对话 ——
    async def chat(
        self,
        messages: list[dict],
        model: str | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
        tools: list[dict] | None = None,
    ) -> dict:
        try:
            resp = await self.client.chat.completions.create(
                model=model or self.runtime.chat_model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                tools=tools or None,
            )
        except Exception as exc:  # noqa: BLE001
            raise self._as_api_error(exc) from exc
        choice = resp.choices[0].message
        return {
            "content": choice.content or "",
            "tool_calls": [tc.model_dump() for tc in (choice.tool_calls or [])],
            "usage": resp.usage.model_dump() if resp.usage else None,
        }

    async def stream(
        self,
        messages: list[dict],
        model: str | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
    ):
        """逐段产出文本增量。"""
        try:
            stream = await self.client.chat.completions.create(
                model=model or self.runtime.chat_model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                stream=True,
            )
            async for chunk in stream:
                if not chunk.choices:
                    continue
                delta = chunk.choices[0].delta
                if delta and delta.content:
                    yield delta.content
        except Exception as exc:  # noqa: BLE001
            raise self._as_api_error(exc) from exc

    # —— 向量 ——
    async def embed(self, texts: list[str], model: str | None = None) -> list[list[float]]:
        target = model or self.runtime.embed_model
        if not target:
            raise ApiError("该供应商没有配置向量模型", code="no_embed_model", status=409)
        try:
            resp = await self.client.embeddings.create(model=target, input=texts)
        except Exception as exc:  # noqa: BLE001
            raise self._as_api_error(exc) from exc
        return [item.embedding for item in resp.data]

    # —— 错误翻译 ——
    def _as_api_error(self, exc: Exception) -> ApiError:
        return ApiError(self._friendly(exc), code="llm_error", status=502)

    def _friendly(self, exc: Exception) -> str:
        if isinstance(exc, AuthenticationError):
            return "API Key 无效或已过期（401）"
        if isinstance(exc, NotFoundError):
            return "模型或接口不存在（404），请检查 Base URL 与模型名"
        if isinstance(exc, RateLimitError):
            return "请求过于频繁或额度不足（429）"
        if isinstance(exc, APITimeoutError):
            return "连接超时，请检查网络或 Base URL"
        if isinstance(exc, APIConnectionError):
            return "无法连接到模型服务，请检查 Base URL 与网络"
        if isinstance(exc, APIStatusError):
            return f"模型服务返回错误（{exc.status_code}）"
        return str(exc) or exc.__class__.__name__

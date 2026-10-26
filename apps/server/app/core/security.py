"""安全边界：安全响应头、跨站请求来源校验。

为什么是纯 ASGI 而不是 BaseHTTPMiddleware
------------------------------------------
`BaseHTTPMiddleware` 会给响应套一层缓冲，SSE 会被攒到结束才吐。
教材问答（/qa/stream）和情景英语对话都是流式的，套上去等于功能失效。
这里直接操作 ASGI 消息，只改写 `http.response.start`，不动 body。

两层防护的分工
--------------
- `OriginGuard`：挡 CSRF。Cookie 已经是 SameSite=Lax，但 Lax 只覆盖跨站 POST，
  同站子域、以及部分浏览器对 Lax 的实现差异仍有风险，所以再加一道来源校验。
  只对写方法生效，读请求零开销。
- `SecurityHeadersMiddleware`：挡 XSS 执行、点击劫持、MIME 嗅探、Referer 泄漏。
  CSP 取 `script-src 'self'`（主题引导脚本已外置到 /theme-init.js）。
"""
from __future__ import annotations

import json
import logging
from urllib.parse import urlsplit

from starlette.datastructures import MutableHeaders

log = logging.getLogger(__name__)

SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})

# 只允许同源加载；不允许内联脚本、不允许被 iframe 嵌套。
DEFAULT_CSP = (
    "default-src 'self'; "
    "script-src 'self'; "
    "style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data: blob:; "
    "font-src 'self' data:; "
    "connect-src 'self'; "
    "media-src 'self' blob:; "
    "object-src 'none'; "
    "base-uri 'self'; "
    "form-action 'self'; "
    "frame-ancestors 'none'"
)


class SecurityHeadersMiddleware:
    """给所有 HTTP 响应补齐安全头。"""

    def __init__(
        self,
        app,
        *,
        csp: str | None = DEFAULT_CSP,
        hsts_seconds: int = 0,
    ) -> None:
        self.app = app
        self.hsts_seconds = max(0, hsts_seconds)
        self.static: dict[str, str] = {
            "X-Content-Type-Options": "nosniff",
            "X-Frame-Options": "DENY",
            "Referrer-Policy": "strict-origin-when-cross-origin",
            "Permissions-Policy": "geolocation=(), microphone=(), camera=(), payment=()",
            "Cross-Origin-Opener-Policy": "same-origin",
        }
        if csp:
            self.static["Content-Security-Policy"] = csp
        if self.hsts_seconds:
            self.static["Strict-Transport-Security"] = (
                f"max-age={self.hsts_seconds}; includeSubDomains"
            )

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_with_headers(message):
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                for key, value in self.static.items():
                    # 不覆盖路由自己设置的值（例如静态资源自定义 Cache-Control 之外的头部）
                    if key not in headers:
                        headers.append(key, value)
            await send(message)

        await self.app(scope, receive, send_with_headers)


class OriginGuard:
    """写请求的来源校验（CSRF 兜底）。

    规则：POST / PUT / PATCH / DELETE 到 /api/ 时，如果请求带了 Origin 或 Referer，
    其主机名必须与当前请求的 Host 一致，或在显式白名单里。都没带则放行
    （非浏览器客户端，如 curl / 脚本，本来就不受 Cookie 自动携带的 CSRF 影响）。
    """

    def __init__(self, app, *, allowed_origins: list[str] | None = None, enabled: bool = True) -> None:
        self.app = app
        self.enabled = enabled
        self.allowed: set[str] = set()
        for item in allowed_origins or []:
            host = urlsplit(item).hostname
            if host:
                self.allowed.add(host.lower())

    async def __call__(self, scope, receive, send):
        if not self.enabled or scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        if scope["method"] in SAFE_METHODS or not scope.get("path", "").startswith("/api/"):
            await self.app(scope, receive, send)
            return

        origin = self._origin(scope)
        if origin is None or self._same_site(origin, scope):
            await self.app(scope, receive, send)
            return

        log.warning("拒绝跨站写请求：origin=%s path=%s", origin, scope.get("path"))
        body = json.dumps(
            {"code": "cross_origin_blocked", "message": "请求来源不被允许"},
            ensure_ascii=False,
        ).encode("utf-8")
        await send(
            {
                "type": "http.response.start",
                "status": 403,
                "headers": [
                    (b"content-type", b"application/json; charset=utf-8"),
                    (b"content-length", str(len(body)).encode()),
                    (b"cache-control", b"no-store"),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})

    @staticmethod
    def _origin(scope) -> str | None:
        headers = {key.lower(): value for key, value in scope.get("headers", [])}
        raw = headers.get(b"origin") or headers.get(b"referer")
        if not raw:
            return None
        try:
            parts = urlsplit(raw.decode("latin-1"))
        except ValueError:
            return None
        if not parts.scheme or not parts.hostname:
            return None
        # "null" 来源（沙箱 iframe、file://）同样拒绝
        return parts.hostname.lower()

    def _same_site(self, origin_host: str, scope) -> bool:
        if origin_host in self.allowed:
            return True
        headers = {key.lower(): value for key, value in scope.get("headers", [])}
        host = headers.get(b"x-forwarded-host") or headers.get(b"host")
        if not host:
            return False
        hostname = host.decode("latin-1").split(",")[0].strip().split(":")[0].lower()
        return hostname == origin_host

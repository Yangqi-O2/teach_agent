"""安全边界测试：响应头、跨站写请求拦截、限流字典上限、HSTS 开关。"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.core import auth
from app.core.security import DEFAULT_CSP, OriginGuard, SecurityHeadersMiddleware


def test_security_headers_present(auth_client: TestClient):
    resp = auth_client.get("/api/health")
    assert resp.status_code == 200
    assert resp.headers["x-content-type-options"] == "nosniff"
    assert resp.headers["x-frame-options"] == "DENY"
    assert resp.headers["referrer-policy"] == "strict-origin-when-cross-origin"
    assert "Content-Security-Policy" in resp.headers


def test_csp_blocks_inline_script():
    """主题引导脚本已外置，所以 script-src 不应该出现 unsafe-inline。"""
    assert "script-src 'self'" in DEFAULT_CSP
    assert "script-src 'self' 'unsafe-inline'" not in DEFAULT_CSP
    assert "frame-ancestors 'none'" in DEFAULT_CSP
    assert "object-src 'none'" in DEFAULT_CSP


def test_cross_origin_write_blocked(auth_client: TestClient):
    resp = auth_client.post(
        "/api/auth/login",
        json={"username": "nobody", "password": "whatever"},
        headers={"origin": "https://evil.example"},
    )
    assert resp.status_code == 403
    assert resp.json()["code"] == "cross_origin_blocked"


def test_same_origin_write_allowed(auth_client: TestClient):
    """同源写请求不能被误杀——否则整个站都登录不了。"""
    resp = auth_client.post(
        "/api/auth/login",
        json={"username": "tester", "password": "test-password-123"},
        headers={"origin": "http://testserver"},
    )
    assert resp.status_code == 200


def test_request_without_origin_allowed(second_user_client):
    """curl / 脚本不带 Origin，本来就不受 Cookie 自动携带的 CSRF 影响。

    这里刻意用一个独立客户端：session 级夹具的会话不能被登出污染。
    """
    fresh = second_user_client("noorigin")
    assert fresh.post("/api/auth/logout").status_code == 200


def test_referer_fallback_is_checked(second_user_client):
    fresh = second_user_client("refcheck")
    resp = fresh.post("/api/auth/logout", headers={"referer": "https://evil.example/page"})
    assert resp.status_code == 403


def test_read_requests_not_blocked(auth_client: TestClient):
    """只校验写方法；读请求带外部 Origin 不该被拦（CORS 负责限制跨源读取）。"""
    resp = auth_client.get("/api/health", headers={"origin": "https://evil.example"})
    assert resp.status_code == 200


def _run_middleware(hsts_seconds: int) -> dict[str, str]:
    """直接驱动中间件，检查它究竟写了哪些头。"""
    import asyncio

    captured: dict[str, str] = {}

    async def app(scope, receive, send):
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    async def send(message):
        if message["type"] == "http.response.start":
            for key, value in message["headers"]:
                captured[key.decode()] = value.decode()

    middleware = SecurityHeadersMiddleware(app, hsts_seconds=hsts_seconds)
    asyncio.run(middleware({"type": "http", "headers": []}, None, send))
    return captured


def test_hsts_only_when_configured():
    assert "strict-transport-security" not in _run_middleware(0)
    headers = _run_middleware(31536000)
    assert headers["strict-transport-security"].startswith("max-age=31536000")


def test_origin_guard_respects_whitelist():
    """CORS 白名单里的来源应被放行（前后端分域部署时用得上）。"""
    import asyncio

    calls = {"reached": False}

    async def app(scope, receive, send):
        calls["reached"] = True

    guard = OriginGuard(app, allowed_origins=["https://app.example"], enabled=True)
    scope = {
        "type": "http",
        "method": "POST",
        "path": "/api/auth/login",
        "headers": [(b"origin", b"https://app.example"), (b"host", b"api.example")],
    }
    asyncio.run(guard(scope, None, None))
    assert calls["reached"] is True


def test_rate_limit_dict_is_bounded():
    """扫不同用户名会让限流字典无限增长，必须能自我收敛。"""
    auth._attempts.clear()
    original = auth._MAX_TRACKED_KEYS
    auth._MAX_TRACKED_KEYS = 50
    try:
        for index in range(200):
            auth.rate_limit_check(f"user{index}|127.0.0.1")
        assert len(auth._attempts) <= 50
    finally:
        auth._MAX_TRACKED_KEYS = original
        auth._attempts.clear()


def test_rate_limit_blocks_after_threshold(monkeypatch):
    auth._attempts.clear()
    monkeypatch.setattr(auth.settings, "login_max_attempts", 3)
    key = "brute|10.0.0.1"
    for _ in range(3):
        auth.rate_limit_check(key)
        auth.rate_limit_record(key)
    with pytest.raises(Exception) as excinfo:
        auth.rate_limit_check(key)
    assert "rate_limited" in str(getattr(excinfo.value, "code", "")) or "过多" in str(excinfo.value)
    auth._attempts.clear()

"""pytest 公共夹具。

关键顺序：**先把 TJH_DATA_DIR 指到临时目录，再 import app.***
``app.config.settings`` 在导入时就读取环境变量，晚设置会污染真实 data 目录。
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

# apps/server 加入 sys.path，保证 `pytest`（非 python -m）也能 import app
SERVER_DIR = Path(__file__).resolve().parents[1]
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))

TEST_DATA_DIR = tempfile.mkdtemp(prefix="tjh-wechat-digest-test-")
os.environ["TJH_DATA_DIR"] = TEST_DATA_DIR
os.environ.setdefault("TJH_LOG_LEVEL", "ERROR")
# 测试里绝不启动校园雷达的自动抓取：否则一次慢跑就会真的去打学校站点
os.environ["TJH_CAMPUS_SCHEDULER"] = "0"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402


TEST_USER = {"username": "tester", "password": "test-password-123", "display_name": "测试同学"}


def _register(client: TestClient, user: dict) -> None:
    resp = client.post("/api/auth/register", json=user)
    assert resp.status_code == 200, resp.text


@pytest.fixture(scope="session")
def client() -> TestClient:
    """带 lifespan 的 TestClient（启动时才会注册 wechat_digest 任务处理器）。

    v0.2 起接口都要求登录，这里在启动后注册一个会话级用户（首个注册者即管理员），
    后续所有用例共用这个已登录的 cookie。
    """
    with TestClient(app) as test_client:
        _register(test_client, TEST_USER)
        yield test_client


@pytest.fixture(scope="session")
def auth_client(client: TestClient) -> TestClient:
    """语义化别名：已登录的 TestClient（english 等能力接口测试用）。"""
    return client


@pytest.fixture(scope="session")
def second_user_client():
    """另起一个普通用户，用来验证跨用户数据隔离。

    返回工厂：`c = second_user_client("bob")`。不带 lifespan 的 TestClient 不会重复
    触发启动钩子，但仍可正常注册与发请求（app 已被主 client 夹具启动）。
    """
    counter = {"n": 0}

    def _make(username: str | None = None) -> TestClient:
        counter["n"] += 1
        name = username or f"user{counter['n']}"
        fresh = TestClient(app)
        _register(fresh, {"username": name, "password": "test-password-123"})
        return fresh

    return _make


@pytest.fixture(scope="session")
def data_dir() -> str:
    return TEST_DATA_DIR


@pytest.fixture
def workdir():
    """自建临时目录（替代 pytest 的 tmp_path）。

    本机沙箱会拦截 `/tmp/pytest-of-*` 的 mkdir，标准库 tempfile 更稳。
    """
    import shutil

    path = Path(tempfile.mkdtemp(prefix="tjh-test-"))
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)

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

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402


@pytest.fixture(scope="session")
def client() -> TestClient:
    """带 lifespan 的 TestClient（启动时才会注册 wechat_digest 任务处理器）。"""
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture(scope="session")
def data_dir() -> str:
    return TEST_DATA_DIR

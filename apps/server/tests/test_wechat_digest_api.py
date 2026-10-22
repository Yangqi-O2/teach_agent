"""群聊简报 · 接口 + 任务流程测试（用 TestClient 与假 LLM，不发真实网络请求）。

覆盖：options / preview（多格式中文样本）/ 409 无供应商 / 404 /
创建 + 轮询任务完成 + 详情 + 历史 + 四种导出 + 删除 / 任务失败落库 /
Agent 工具注册与调用 / 历史条数清理。
"""
from __future__ import annotations

import asyncio
import json
import time

import pytest
from sqlmodel import Session, select

from app.capabilities.wechat_digest import jobs as digest_jobs
from app.capabilities.wechat_digest import service
from app.capabilities.wechat_digest.models import Digest
from app.core.tools import registry as tool_registry
from app.db import engine
from app.models import Provider

# 混合格式的中文样本（契约 /options 的 sample_params 同款风格）
SAMPLE_TEXT = (
    "[2026-10-22 17:50] 李老师: 周五前交实验报告\n"
    "张三: 收到\n"
    "李老师: 下周三随堂测验，范围第 3-4 章\n"
    "李老师: 收到\n"
    "李四: 好的\n"
    "王五: 周五实验报告提交到学习通，截止 23:59\n"
)

LLM_OUTPUT = """【一句话】周五前交实验报告，下周三随堂测验。
【重要事项】
1. 周五前交实验报告（提交到学习通）
2. 下周三随堂测验，范围第 3-4 章
【待办】
1. 交实验报告，截止周五 23:59
----JSON----
{"one_line": "周五前交实验报告，下周三随堂测验。", "items": ["周五前交实验报告", "下周三随堂测验"], "schedules": [{"title": "交实验报告", "datetime": "2026-10-24T23:59", "note": "提交到学习通", "done": false, "source_sender": "李老师"}, {"title": "随堂测验", "datetime": "2026-10-29T10:00", "note": "范围第 3-4 章", "done": false, "source_sender": "李老师"}]}
"""


class FakeLLMClient:
    """假的 LLMClient：只实现 chat，返回固定结构化输出。"""

    calls: int = 0

    def __init__(self, runtime, timeout: float = 60.0):
        self.runtime = runtime
        self.timeout = timeout

    async def chat(self, messages, **kwargs):
        type(self).calls += 1
        return {"content": LLM_OUTPUT, "tool_calls": [], "usage": {"total_tokens": 1}}


class FailingLLMClient(FakeLLMClient):
    async def chat(self, messages, **kwargs):
        raise RuntimeError("模型服务炸了")


class SlowLLMClient(FakeLLMClient):
    async def chat(self, messages, **kwargs):
        await asyncio.sleep(0.4)
        return {"content": LLM_OUTPUT, "tool_calls": [], "usage": None}


@pytest.fixture()
def fake_llm(monkeypatch):
    monkeypatch.setattr(digest_jobs, "LLMClient", FakeLLMClient)
    return FakeLLMClient


# ---------------------------------------------------------------- 小工具


def _clear_providers() -> None:
    with Session(engine) as session:
        for row in session.exec(select(Provider)).all():
            session.delete(row)
        session.commit()


def _clear_digests() -> None:
    with Session(engine) as session:
        for row in session.exec(select(Digest)).all():
            session.delete(row)
        session.commit()


def _create_provider(client) -> dict:
    resp = client.post(
        "/api/providers",
        json={
            "name": "测试供应商",
            "base_url": "https://example.invalid/v1",
            "api_key": "sk-test-1234567890",
            "chat_model": "DeepSeek-V4-Flash",
            "is_default": True,
        },
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def _wait_job(client, job_id: str, timeout: float = 15.0) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        resp = client.get(f"/api/jobs/{job_id}")
        assert resp.status_code == 200, resp.text
        job = resp.json()
        if job["status"] in ("done", "error", "cancelled"):
            return job
        time.sleep(0.05)
    raise AssertionError(f"任务 {job_id} 超时未结束")


def _preview_body() -> dict:
    return {"source": "paste", "params": {"text": SAMPLE_TEXT, "group_name": "高数A班"}}


# ---------------------------------------------------------------- 能力 / 工具注册


def test_capability_and_tools_registered(client) -> None:
    caps = client.get("/api/capabilities").json()
    cap = next(c for c in caps if c["id"] == "wechat_digest")
    assert cap["name"] == "群聊简报"
    assert cap["status"] == "beta"
    assert cap["icon"] == "message-square"
    assert cap["nav"] == {"label": "群聊简报", "path": "/cap/wechat-digest", "order": 20}
    props = cap["settings_schema"]["properties"]
    assert props["default_style"]["enum"] == ["general", "course", "club"]
    assert props["max_chars"]["default"] == 60000
    assert props["history_limit"]["default"] == 30
    assert cap["has_tools"] is True

    tools = {t["name"]: t for t in client.get("/api/tools").json()}
    assert "summarize_group_chat" in tools
    assert "list_group_digests" in tools
    assert tools["summarize_group_chat"]["capability"] == "wechat_digest"
    assert tools["summarize_group_chat"]["parameters"]["required"] == ["text"]
    assert tools["list_group_digests"]["parameters"]["properties"]["limit"]["default"] == 10


# ---------------------------------------------------------------- options


def test_options(client) -> None:
    resp = client.get("/api/c/wechat_digest/options")
    assert resp.status_code == 200
    data = resp.json()

    assert [s["id"] for s in data["sources"]] == ["paste"]
    paste = data["sources"][0]
    assert paste["badge"] == "推荐"
    assert paste["params_schema"]["properties"]["text"]["required"] is True
    assert paste["sample_params"]["group_name"] == "高数A班"

    assert [s["id"] for s in data["styles"]] == ["general", "course", "club"]
    assert data["settings"] == {
        "default_style": "general",
        "max_chars": 60000,
        "history_limit": 30,
    }


# ---------------------------------------------------------------- preview


def test_preview_multiformat_sample(client) -> None:
    resp = client.post("/api/c/wechat_digest/preview", json=_preview_body())
    assert resp.status_code == 200, resp.text
    data = resp.json()

    assert data["ok"] is True
    assert data["source"] == "paste"
    assert data["total_before"] == 6
    assert data["total_after"] == 3
    assert data["groups"] == [
        {
            "name": "高数A班",
            "before": 6,
            "after": 3,
            "dropped": 3,
            "drop_reasons": {"low_value": 3, "duplicate": 0, "placeholder_limit": 0},
        }
    ]
    assert len(data["sample"]) == 3
    assert data["sample"][0] == {
        "time": "2026-10-22 17:50",
        "sender": "李老师",
        "text": "周五前交实验报告",
    }
    assert all(set(item) == {"time", "sender", "text"} for item in data["sample"])


def test_preview_sample_limited_to_five(client) -> None:
    text = "\n".join(f"张三: 这是第{i}条有效消息" for i in range(1, 9))
    resp = client.post(
        "/api/c/wechat_digest/preview",
        json={"source": "paste", "params": {"text": text, "group_name": "测试群"}},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_before"] == 8
    assert len(data["sample"]) == 5


def test_preview_empty_source_422(client) -> None:
    resp = client.post(
        "/api/c/wechat_digest/preview", json={"source": "paste", "params": {"text": ""}}
    )
    assert resp.status_code == 422
    assert resp.json()["code"] == "empty_source"

    resp = client.post(
        "/api/c/wechat_digest/preview",
        json={"source": "paste", "params": {"text": "张三: 收到\n李四: 好的"}},
    )
    assert resp.status_code == 422
    assert resp.json()["code"] == "empty_source"
    assert "没有" in resp.json()["message"]


def test_preview_too_long_413(client) -> None:
    text = "张三: " + "很" * 60001
    resp = client.post(
        "/api/c/wechat_digest/preview",
        json={"source": "paste", "params": {"text": text, "group_name": "大群"}},
    )
    assert resp.status_code == 413
    body = resp.json()
    assert body["code"] == "too_long"
    assert "60000" in body["message"]


def test_preview_unknown_source_422(client) -> None:
    resp = client.post(
        "/api/c/wechat_digest/preview",
        json={"source": "onebot", "params": {"text": "x"}},
    )
    assert resp.status_code == 422
    assert resp.json()["code"] == "invalid_source"


# ---------------------------------------------------------------- 历史清理


def test_trim_history_keeps_latest() -> None:
    _clear_digests()
    with Session(engine) as session:
        for i in range(4):
            session.add(
                Digest(
                    title=f"trim-test-{i}",
                    status="done",
                    created_at=f"2026-10-2{i}T10:00:00",
                    updated_at=f"2026-10-2{i}T10:00:00",
                )
            )
        session.commit()
        removed = service.trim_history(session, 2)
    assert removed == 2
    with Session(engine) as session:
        left = session.exec(select(Digest).where(Digest.title.like("trim-test-%"))).all()
        assert sorted(row.title for row in left) == ["trim-test-2", "trim-test-3"]
    _clear_digests()


# ---------------------------------------------------------------- 409 / 404


def test_create_without_provider_409(client) -> None:
    _clear_providers()
    resp = client.post(
        "/api/c/wechat_digest/digests",
        json={**_preview_body(), "style": "general", "provider_id": None},
    )
    assert resp.status_code == 409
    body = resp.json()
    assert body["code"] == "no_provider"
    assert "设置" in body["message"]
    # 创建前拦截：不应该留下任何记录
    assert client.get("/api/c/wechat_digest/digests").json() == []


def test_digest_not_found_404(client) -> None:
    assert client.get("/api/c/wechat_digest/digests/999999").status_code == 404
    assert client.get("/api/c/wechat_digest/digests/999999").json()["code"] == "not_found"
    assert client.delete("/api/c/wechat_digest/digests/999999").status_code == 404
    assert (
        client.get("/api/c/wechat_digest/digests/999999/export", params={"format": "txt"}).status_code
        == 404
    )


def test_export_not_ready_409(client) -> None:
    with Session(engine) as session:
        digest = Digest(
            title="未完成简报",
            status="running",
            created_at=service.now_iso(),
            updated_at=service.now_iso(),
        )
        session.add(digest)
        session.commit()
        session.refresh(digest)
        digest_id = digest.id
    try:
        resp = client.get(
            f"/api/c/wechat_digest/digests/{digest_id}/export", params={"format": "txt"}
        )
        assert resp.status_code == 409
        assert resp.json()["code"] == "not_ready"
    finally:
        client.delete(f"/api/c/wechat_digest/digests/{digest_id}")


# ---------------------------------------------------------------- 完整生成流程


def test_create_and_complete_flow(client, fake_llm) -> None:
    _create_provider(client)

    resp = client.post(
        "/api/c/wechat_digest/digests",
        json={**_preview_body(), "style": "course", "provider_id": None},
    )
    assert resp.status_code == 202, resp.text
    created = resp.json()
    assert created["ok"] is True
    job_id = created["job_id"]
    summary = created["digest"]
    digest_id = summary["id"]
    assert summary["title"] == "高数A班 · 群聊简报"
    assert summary["style"] == "course"
    assert summary["status"] in ("queued", "running", "done")
    assert summary["provider"] == "测试供应商"
    assert summary["model"] == "DeepSeek-V4-Flash"
    assert summary["message_count"] == 6
    assert summary["kept_count"] == 3

    job = _wait_job(client, job_id)
    assert job["status"] == "done", job
    assert job["type"] == "wechat_digest"
    assert job["progress"] == 100
    assert job["message"] == "已完成"
    assert job["result"]["digest_id"] == digest_id
    assert job["result"]["stats"] == {"before": 6, "after": 3, "dropped": 3, "chunks": 1}

    detail = client.get(f"/api/c/wechat_digest/digests/{digest_id}").json()
    assert detail["status"] == "done"
    assert detail["job_id"] == job_id
    assert detail["one_line"] == "周五前交实验报告，下周三随堂测验。"
    assert detail["error"] is None
    payload = detail["result"]
    assert payload["version"] == 1
    assert payload["source"] == "paste"
    assert payload["group_name"] == "高数A班"
    assert payload["style"] == "course"
    assert payload["provider"] == "测试供应商"
    assert payload["model"] == "DeepSeek-V4-Flash"
    assert payload["stats"] == {"before": 6, "after": 3, "dropped": 3, "chunks": 1}
    group = payload["groups"][0]
    assert group["name"] == "高数A班"
    assert group["message_count"] == 3
    assert group["one_line"] == "周五前交实验报告，下周三随堂测验。"
    assert group["items"] == ["周五前交实验报告", "下周三随堂测验"]
    assert [s["title"] for s in group["schedules"]] == ["交实验报告", "随堂测验"]
    assert group["schedules"][0]["source_sender"] == "李老师"
    assert set(group["schedules"][0]) == {"title", "datetime", "note", "done", "source_sender"}
    assert "【一句话】" in group["structured_text"]

    listing = client.get("/api/c/wechat_digest/digests", params={"limit": 10}).json()
    item = next(row for row in listing if row["id"] == digest_id)
    assert set(item) == {
        "id",
        "title",
        "group_name",
        "source",
        "style",
        "status",
        "provider",
        "model",
        "message_count",
        "kept_count",
        "one_line",
        "created_at",
    }
    assert item["one_line"] == "周五前交实验报告，下周三随堂测验。"
    assert [row["id"] for row in client.get(
        "/api/c/wechat_digest/digests", params={"q": "高数"}
    ).json()] == [digest_id]
    assert client.get("/api/c/wechat_digest/digests", params={"q": "不存在的关键词"}).json() == []

    # 四种导出
    expected_types = {
        "txt": "text/plain",
        "json": "application/json",
        "md": "text/markdown",
        "ics": "text/calendar",
    }
    for fmt, content_type in expected_types.items():
        resp = client.get(
            f"/api/c/wechat_digest/digests/{digest_id}/export", params={"format": fmt}
        )
        assert resp.status_code == 200, (fmt, resp.text)
        assert resp.headers["content-type"].startswith(content_type)
        disposition = resp.headers["content-disposition"]
        assert disposition.startswith("attachment;")
        assert "filename*=UTF-8''" in disposition
        if fmt == "json":
            assert json.loads(resp.content) == payload
        elif fmt == "ics":
            assert "BEGIN:VCALENDAR" in resp.text
            assert "SUMMARY:" in resp.text
            assert "DTSTART" in resp.text
            assert "20261024T235900" in resp.text
        elif fmt == "md":
            assert "- [ ] **交实验报告**" in resp.text
        elif fmt == "txt":
            assert "群聊简报 · 高数A班" in resp.text
            assert "清洗：原始 6 条 → 保留 3 条" in resp.text

    bad = client.get(
        f"/api/c/wechat_digest/digests/{digest_id}/export", params={"format": "pdf"}
    )
    assert bad.status_code == 422
    assert bad.json()["code"] == "invalid_format"

    assert client.delete(f"/api/c/wechat_digest/digests/{digest_id}").json() == {"ok": True}
    assert client.get(f"/api/c/wechat_digest/digests/{digest_id}").status_code == 404


def test_job_failure_marks_digest_error(client, monkeypatch) -> None:
    monkeypatch.setattr(digest_jobs, "LLMClient", FailingLLMClient)
    _create_provider(client)

    resp = client.post(
        "/api/c/wechat_digest/digests",
        json={**_preview_body(), "style": "general", "provider_id": None},
    )
    assert resp.status_code == 202, resp.text
    created = resp.json()
    digest_id = created["digest"]["id"]

    job = _wait_job(client, created["job_id"])
    assert job["status"] == "error"
    assert "模型服务炸了" in (job["error"] or "")

    detail = client.get(f"/api/c/wechat_digest/digests/{digest_id}").json()
    assert detail["status"] == "error"
    assert "模型服务炸了" in (detail["error"] or "")
    assert detail["result"] is None
    assert client.delete(f"/api/c/wechat_digest/digests/{digest_id}").status_code == 200


def test_cancel_job_sets_digest_cancelled(client, monkeypatch) -> None:
    """契约 §3.4：取消后 job 与 digest 都应为 cancelled。"""
    monkeypatch.setattr(digest_jobs, "LLMClient", SlowLLMClient)
    _create_provider(client)

    resp = client.post(
        "/api/c/wechat_digest/digests",
        json={**_preview_body(), "style": "general", "provider_id": None},
    )
    assert resp.status_code == 202, resp.text
    created = resp.json()
    digest_id = created["digest"]["id"]
    job_id = created["job_id"]

    # 等任务真正开始（线程池拿到 ctx 后 cancel 才生效）
    deadline = time.time() + 5
    while time.time() < deadline:
        if client.get(f"/api/jobs/{job_id}").json()["status"] == "running":
            break
        time.sleep(0.02)
    cancel = client.post(f"/api/jobs/{job_id}/cancel")
    assert cancel.status_code == 200, cancel.text

    deadline = time.time() + 10
    status = None
    while time.time() < deadline:
        detail = client.get(f"/api/c/wechat_digest/digests/{digest_id}").json()
        status = detail["status"]
        if status in ("cancelled", "error", "done"):
            break
        time.sleep(0.05)
    assert status == "cancelled", detail
    assert client.get(f"/api/jobs/{job_id}").json()["status"] == "cancelled"
    assert client.delete(f"/api/c/wechat_digest/digests/{digest_id}").status_code == 200


# ---------------------------------------------------------------- Agent 工具


def test_tool_summarize_group_chat(client, monkeypatch) -> None:
    from app.capabilities.wechat_digest import capability as digest_capability

    monkeypatch.setattr(digest_jobs, "LLMClient", FakeLLMClient)
    monkeypatch.setattr(digest_capability, "LLMClient", FakeLLMClient)
    _create_provider(client)

    result = asyncio.run(
        tool_registry.execute(
            "summarize_group_chat",
            {"text": SAMPLE_TEXT, "group_name": "工具群", "style": "general"},
        )
    )
    assert result["ok"] is True, result
    data = result["data"]
    assert data["digest_id"]
    assert data["one_line"] == "周五前交实验报告，下周三随堂测验。"
    assert data["stats"] == {"before": 6, "after": 3, "dropped": 3, "chunks": 1}
    assert data["groups"][0]["name"] == "工具群"
    assert data["groups"][0]["items"] == ["周五前交实验报告", "下周三随堂测验"]
    assert len(data["groups"][0]["schedules"]) == 2

    detail = client.get(f"/api/c/wechat_digest/digests/{data['digest_id']}").json()
    assert detail["status"] == "done"
    assert detail["group_name"] == "工具群"

    listed = asyncio.run(tool_registry.execute("list_group_digests", {"limit": 5}))
    assert listed["ok"] is True
    assert any(row["id"] == data["digest_id"] for row in listed["data"])

    assert client.delete(f"/api/c/wechat_digest/digests/{data['digest_id']}").status_code == 200


def test_tool_summarize_empty_text_rejected() -> None:
    result = asyncio.run(tool_registry.execute("summarize_group_chat", {"text": "  "}))
    assert result["ok"] is False
    assert "聊天记录为空" in result["error"]


def test_tool_summarize_failure_marks_digest_error(client, monkeypatch) -> None:
    """工具失败路径：已创建的 digest 必须置 error，不能永远停在 queued。"""
    from app.capabilities.wechat_digest import capability as digest_capability

    _create_provider(client)

    async def boom(*args, **kwargs):
        raise RuntimeError("工具内部模型调用失败")

    monkeypatch.setattr(digest_capability, "summarize_groups", boom)

    result = asyncio.run(
        tool_registry.execute(
            "summarize_group_chat",
            {"text": SAMPLE_TEXT, "group_name": "工具失败群", "style": "general"},
        )
    )
    assert result["ok"] is False
    assert "工具内部模型调用失败" in result["error"]

    rows = client.get("/api/c/wechat_digest/digests", params={"q": "工具失败群"}).json()
    assert len(rows) == 1, rows
    row = rows[0]
    assert row["status"] == "error", row
    detail = client.get(f"/api/c/wechat_digest/digests/{row['id']}").json()
    assert detail["status"] == "error"
    assert detail["error"] and "工具内部模型调用失败" in detail["error"]
    assert detail["result"] is None
    assert client.delete(f"/api/c/wechat_digest/digests/{row['id']}").status_code == 200


def test_summarize_progress_is_monotonic_for_multiple_groups(monkeypatch) -> None:
    """多群时进度不能回退：50 → 80 → 88（修复 88 在循环内导致的 88→80）。"""
    from app.capabilities.wechat_digest import service
    from app.capabilities.wechat_digest.sources.base import Message

    prepared = service.Prepared(
        source="paste",
        params={},
        group_name="群A",
        cleaned={
            "群A": [Message("群A", "张三", "周五交作业")],
            "群B": [Message("群B", "李四", "明天考试")],
        },
        stats={
            "群A": {"before": 1, "after": 1, "dropped": 0},
            "群B": {"before": 1, "after": 1, "dropped": 0},
        },
    )
    seen: list[int] = []

    class FakeCtx:
        def progress(self, pct: int, message: str | None = None) -> None:
            seen.append(int(pct))

        def check_cancelled(self) -> None:
            return None

    class FakeClient:
        async def chat(self, messages, **kwargs):
            return {"content": LLM_OUTPUT, "tool_calls": [], "usage": None}

    groups, chunks = asyncio.run(
        digest_jobs._summarize(FakeClient(), FakeCtx(), prepared, "general")  # type: ignore[arg-type]
    )
    assert len(groups) == 2
    assert chunks == 2
    assert seen == sorted(seen), f"进度回退: {seen}"
    assert seen == [50, 80, 88]

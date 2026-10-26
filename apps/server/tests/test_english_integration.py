"""情景英语能力 · 端到端集成测试（Lead 维护）。

不 mock 内部函数，而是打开能力的「离线演示模式」（mock LLM），走真实 HTTP + SSE + SQLite 全链路：
建情景 → 生成话题 → 对话（流式）→ 会话落库 → 生词入库/复习 → 记忆/错误档案 → 成本看板 → 跨用户隔离。
这样能验证各 agent 模块、router、迁移、能力设置之间的接线是否正确。
"""
from __future__ import annotations

import json

import pytest


def _enable_mock(client) -> None:
    resp = client.put("/api/capabilities/english", json={"settings": {"mock_mode": True}})
    assert resp.status_code == 200, resp.text


def _parse_sse(response) -> list[tuple[str, dict]]:
    """把 SSE 响应解析成 [(event, data)]；严格按空行分帧，不按行猜。"""
    events: list[tuple[str, dict]] = []
    event = "message"
    data_lines: list[str] = []
    for line in response.iter_lines():
        if line == "":
            if data_lines:
                raw = "\n".join(data_lines)
                try:
                    payload = json.loads(raw)
                except ValueError:
                    payload = {"_raw": raw}
                events.append((event, payload))
            event, data_lines = "message", []
            continue
        if line.startswith("event:"):
            event = line[len("event:") :].strip()
        elif line.startswith("data:"):
            data_lines.append(line[len("data:") :].lstrip())
    if data_lines:
        events.append((event, json.loads("\n".join(data_lines))))
    return events


@pytest.fixture()
def english_client(auth_client):
    _enable_mock(auth_client)
    return auth_client


def test_scenario_generation_and_persistence(english_client) -> None:
    resp = english_client.post("/api/c/english/scenarios", json={"domain": "一带一路", "cefr": "B1"})
    assert resp.status_code == 200, resp.text
    plan = resp.json()
    assert plan["id"] and plan["slug"]
    assert plan["provider"] == "mock"
    assert 6 <= len(plan["topics"]) <= 10

    listed = english_client.get("/api/c/english/scenarios").json()["items"]
    assert any(item["id"] == plan["id"] for item in listed)

    detail = english_client.get(f"/api/c/english/scenarios/{plan['id']}").json()
    assert detail["title_zh"] == plan["title_zh"]
    assert len(detail["topics"]) == len(plan["topics"])
    assert detail["topics"][0]["beats"]  # JSON 列已还原成 list

    assert english_client.get("/api/c/english/scenarios/not-exist").status_code == 404
    assert english_client.post("/api/c/english/scenarios", json={"domain": "x"}).status_code == 400


def test_chat_stream_end_to_end(english_client) -> None:
    plan = english_client.post(
        "/api/c/english/scenarios", json={"domain": "求职面试", "cefr": "B1"}
    ).json()

    with english_client.stream(
        "POST",
        "/api/c/english/chat",
        json={"scenarioId": plan["id"], "message": "I has went to the company yesterday."},
    ) as response:
        assert response.status_code == 200, response.read()
        events = _parse_sse(response)

    names = [name for name, _ in events]
    assert "delta" in names
    assert names[-1] == "done"
    assert "meta" in names
    meta = dict(events)["meta"]
    assert meta["conversationId"]
    assert meta["topicId"]
    assert meta["provider"] == "mock"
    assert meta["ttftMs"] is not None
    assert "candidates" in meta and isinstance(meta["candidates"], list)

    # 流式正文能拼回去，且落库
    streamed = "".join(payload.get("text", "") for name, payload in events if name == "delta")
    assert len(streamed) > 10
    conv = english_client.get(f"/api/c/english/conversations/{meta['conversationId']}").json()
    roles = [message["role"] for message in conv["messages"]]
    assert roles == ["user", "assistant"]
    assert conv["messages"][1]["content_md"] == streamed

    # 会话列表（刷新页面后接着聊）
    convs = english_client.get(f"/api/c/english/scenarios/{plan['id']}/conversations").json()["items"]
    assert any(item["id"] == meta["conversationId"] for item in convs)

    # 续聊同一会话：不再新建
    with english_client.stream(
        "POST",
        "/api/c/english/chat",
        json={
            "scenarioId": plan["id"],
            "conversationId": meta["conversationId"],
            "message": "What should I prepare next?",
        },
    ) as response:
        events2 = _parse_sse(response)
    meta2 = dict(events2)["meta"]
    assert meta2["conversationId"] == meta["conversationId"]

    conv2 = english_client.get(f"/api/c/english/conversations/{meta['conversationId']}").json()
    assert len(conv2["messages"]) == 4

    # 记忆接口可读
    memory = english_client.get(f"/api/c/english/memory/{plan['id']}").json()
    assert "revision" in memory and "counts" in memory


def test_vocab_save_list_review(english_client) -> None:
    saved = english_client.post(
        "/api/c/english/vocab",
        json={"surface": "demurrage", "context": "The demurrage fee is high."},
    )
    assert saved.status_code == 200, saved.text
    body = saved.json()
    assert body["lemma"] == "demurrage"
    assert body["intervalDays"] >= 1

    listed = english_client.get("/api/c/english/vocab").json()
    lemma = next(item for item in listed["items"] if item["lemma"] == "demurrage")
    assert "glossZh" in lemma and "pos" in lemma  # mock 模式释义可能为 None，前端显示占位
    assert "mastery" in lemma and "due" in lemma

    reviewed = english_client.post(
        "/api/c/english/vocab/review", json={"lemma": "demurrage", "rating": 3}
    )
    assert reviewed.status_code == 200, reviewed.text
    assert reviewed.json()["intervalDays"] >= 1

    assert (
        english_client.post(
            "/api/c/english/vocab/review", json={"lemma": "not-a-word", "rating": 3}
        ).status_code
        == 404
    )
    assert english_client.post("/api/c/english/vocab", json={"surface": "!"}).status_code == 400


def test_contract_and_stats(english_client) -> None:
    plan = english_client.post(
        "/api/c/english/scenarios", json={"domain": "展会接待", "cefr": "A2"}
    ).json()
    with english_client.stream(
        "POST",
        "/api/c/english/chat",
        json={"scenarioId": plan["id"], "message": "Hello, nice to meet you."},
    ) as response:
        _parse_sse(response)

    put = english_client.put(
        "/api/c/english/contract",
        json={
            "must_use_words": ["deadline", "stakeholder", "budget", "scope", "risk"],
            "grammar_focus": ["article.a_an_the", "not.a.real.code"],
            "correction_intensity": "strict",
            "difficulty_delta": 1,
            "max_reply_words": 120,
        },
    )
    assert put.status_code == 200, put.text
    contract = put.json()["contract"]
    assert len(contract["must_use_words"]) == 3                       # 最多 3 个自然复用词
    assert contract["grammar_focus"] == ["article.a_an_the"]          # 未知语法点被过滤
    assert contract["correction_intensity"] == "strict"
    assert put.json()["warnings"]

    assert english_client.get("/api/c/english/contract").json()["correction_intensity"] == "strict"

    stats = english_client.get("/api/c/english/stats").json()
    assert stats["turns24h"] >= 1
    assert "budget" in stats and "quality" in stats and "health" in stats
    assert stats["budget"]["limit"] > 0


def test_documents_import_and_delete(english_client) -> None:
    text = "Port operations notes. " * 60
    imported = english_client.post(
        "/api/c/english/documents", json={"filename": "port-notes.md", "content": text}
    )
    assert imported.status_code == 200, imported.text
    doc = imported.json()
    assert doc["chunks"] >= 1

    listed = english_client.get("/api/c/english/documents").json()["items"]
    assert any(item["id"] == doc["id"] for item in listed)

    deleted = english_client.delete(f"/api/c/english/documents/{doc['id']}")
    assert deleted.status_code == 200
    assert english_client.delete(f"/api/c/english/documents/{doc['id']}").status_code == 404

    assert (
        english_client.post(
            "/api/c/english/documents", json={"filename": "x.md", "content": "太短"}
        ).status_code
        == 400
    )


def test_upload_text_file(english_client) -> None:
    files = {"file": ("notes.txt", b"Shipping terms and demurrage clauses. " * 40, "text/plain")}
    resp = english_client.post("/api/c/english/documents/upload", files=files)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["kind"] in {"text", "md", "txt"}  # 纯文本类统一归为 text（与 TS 一致）
    assert body["chars"] > 100
    english_client.delete(f"/api/c/english/documents/{body['id']}")


def test_quota_exceeded(auth_client, second_user_client) -> None:
    fresh = second_user_client("quotacarol")
    fresh.put("/api/capabilities/english", json={"settings": {"mock_mode": True, "daily_quota": 1}})
    plan = fresh.post("/api/c/english/scenarios", json={"domain": "校园生活"}).json()
    first = fresh.post(
        "/api/c/english/chat", json={"scenarioId": plan["id"], "message": "Hi there"}
    )
    assert first.status_code == 200, first.text
    second = fresh.post(
        "/api/c/english/chat", json={"scenarioId": plan["id"], "message": "One more?"}
    )
    assert second.status_code == 429
    assert second.json()["code"] == "QUOTA_EXCEEDED"


def test_cross_user_isolation(auth_client, second_user_client) -> None:
    _enable_mock(auth_client)
    plan = auth_client.post("/api/c/english/scenarios", json={"domain": "数据隔离"}).json()
    with auth_client.stream(
        "POST",
        "/api/c/english/chat",
        json={"scenarioId": plan["id"], "message": "Private message here"},
    ) as response:
        events = _parse_sse(response)
    conv_id = dict(events)["meta"]["conversationId"]

    bob = second_user_client("englishbob")
    bob.put("/api/capabilities/english", json={"settings": {"mock_mode": True}})
    assert bob.get(f"/api/c/english/conversations/{conv_id}").status_code in (403, 404)

    bob_vocab = bob.get("/api/c/english/vocab").json()
    assert all(item["lemma"] != "demurrage" for item in bob_vocab["items"])

    with bob.stream(
        "POST",
        "/api/c/english/chat",
        json={"scenarioId": plan["id"], "conversationId": conv_id, "message": "hijack"},
    ) as response:
        assert response.status_code in (403, 404)

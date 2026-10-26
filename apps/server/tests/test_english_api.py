"""情景英语（english）HTTP 接口测试。

原则（与规范 §0 一致）：**不联网、不调用真实模型**。
这里把 ``app.capabilities.english.llm.get_llm`` 换成断言性的 :class:`FakeLLM`：

- ``stream()`` 产出确定的英文句子（默认是一条「合格回复」：40–160 词、以问句结尾、
  无禁用套话，因此不会触发质量重写）；
- ``json()`` 按 schema 返回合法结构化数据（情景计划等）；
- ``mock = True`` 让 agents 走各自的确定性兜底分支（规则纠错 / 规则记忆 / 兜底知识卡）。

所以整条 /chat 链路（配额 → 准备 → 流式 → 质量 → 落库 → 纠错/记忆 → 事件）都能离线跑。
"""
from __future__ import annotations

import json
import uuid
from typing import Any

import pytest

from app.capabilities.english import llm as llm_module
from app.capabilities.english import settings as settings_module
from app.core.errors import ApiError

BASE = "/api/c/english"

#: 合格回复：59 词、以问句结尾、无禁用套话 → measure_reply()` 的 flags 为空
GOOD_REPLY = (
    "That makes sense, and I appreciate you being upfront about it. The real problem is timing: "
    "our warehouse is already full, so every truck that arrives late costs us space we do not have. "
    "I could accept the delay if you cover the storage fee, but I cannot absorb it quietly. "
    "How would you handle that on your side?"
)
#: 不合格回复：太短 + 没问句 → 触发一次静默重写（replace 事件）
BAD_REPLY = "I see."


# ================================================================ FakeLLM


def _plan_payload(user: str) -> dict[str, Any]:
    """按 PlanSchema 造一份合法的情景计划（6 个话题）。"""
    domain = "情景"
    for line in (user or "").splitlines():
        if "领域：" in line:
            domain = line.split("领域：", 1)[1].strip() or domain
            break
    topics = []
    for index in range(6):
        topics.append(
            {
                "title": f"Topic {index + 1} about {domain}"[:120],
                "beats": [
                    f"open with angle {index + 1}",
                    "raise one unexpected constraint",
                    "agree on a concrete next step",
                ],
                "target_tenses": ["past simple", "present perfect"],
                "target_lexis": ["deadline", "budget", "trade-off"],
                "difficulty": "A2" if index < 2 else ("B1" if index < 4 else "B2"),
            }
        )
    return {
        "title_zh": f"{domain}模拟情景"[:60],
        "title_en": f"{domain} role-play scene"[:80],
        "slug": f"fake-{uuid.uuid4().hex[:10]}",
        "topics": topics,
    }


def _json_payload(schema: Any, user: str) -> dict[str, Any]:
    fields = set(getattr(schema, "model_fields", {}) or {})
    if "topics" in fields:
        return _plan_payload(user)
    if "errors" in fields:
        return {"errors": [], "confidence": 0.9}
    if "gloss_zh" in fields:
        return {"gloss_zh": "谈判；洽谈", "pos": "v."}
    if "glossZh" in fields:
        return {"glossZh": "谈判；洽谈", "pos": "v."}
    if "rule_md" in fields:
        return {
            "title": "模拟知识卡",
            "rule_md": "**口诀**：先看时间标志词，再检查动词形式。\n\n易混：中文没有形态变化。",
            "examples": [{"wrong": "He go.", "right": "He goes.", "note": "第三人称单数"}],
        }
    if "summary" in fields:
        return {"summary": "（模拟摘要）"}
    if "established_facts" in fields or "setting" in fields:
        return {"setting": "mock", "established_facts": ["The meeting is on Friday."]}
    return {}


class FakeLLM:
    """最小可用的确定性 LLM（不联网）。"""

    name = "fake"
    mock = True

    def __init__(
        self,
        replies: list[str] | None = None,
        *,
        stream_error: Exception | None = None,
    ) -> None:
        self.replies = list(replies or [GOOD_REPLY])
        self.stream_error = stream_error
        self.stream_calls = 0
        self.json_calls: list[str] = []

    def stream(self, system: str = "", messages: list[dict] | None = None, max_tokens: int = 600):
        self.stream_calls += 1
        reply = self.replies[min(self.stream_calls - 1, len(self.replies) - 1)]
        return self._generate(reply)

    async def _generate(self, reply: str):
        if self.stream_error is not None:
            raise self.stream_error
        for start in range(0, len(reply), 8):
            yield reply[start : start + 8]

    async def json(self, system: str = "", user: str = "", schema: Any = None, max_tokens: int = 1200):
        self.json_calls.append(getattr(schema, "__name__", ""))
        payload = _json_payload(schema, user)
        return schema.model_validate(payload)


@pytest.fixture
def fake_llm(monkeypatch: pytest.MonkeyPatch) -> FakeLLM:
    """所有 english 模块都通过 ``llm.get_llm`` 取模型，替换这一处即可。"""
    fake = FakeLLM()
    monkeypatch.setattr(llm_module, "get_llm", lambda *args, **kwargs: fake)
    return fake


def _use_llm(monkeypatch: pytest.MonkeyPatch, fake: FakeLLM) -> FakeLLM:
    monkeypatch.setattr(llm_module, "get_llm", lambda *args, **kwargs: fake)
    return fake


# ================================================================ 请求助手


def _create_scenario(client: Any, cefr: str = "B1") -> dict:
    domain = f"接口测试-{uuid.uuid4().hex[:8]}"
    response = client.post(f"{BASE}/scenarios", json={"domain": domain, "cefr": cefr})
    assert response.status_code == 200, response.text
    return response.json()


def _read_events(response: Any) -> list[tuple[str, dict]]:
    """把 SSE 响应解析成 [(event, data)]。"""
    events: list[tuple[str, dict]] = []
    event: str | None = None
    data: list[str] = []
    for raw in response.iter_lines():
        line = raw.decode("utf-8") if isinstance(raw, bytes) else raw
        if line == "":
            if data:
                events.append((event or "message", json.loads("\n".join(data))))
            event, data = None, []
            continue
        if line.startswith(":"):
            continue
        if line.startswith("event:"):
            event = line[len("event:") :].strip()
        elif line.startswith("data:"):
            data.append(line[len("data:") :].lstrip())
    if data:
        events.append((event or "message", json.loads("\n".join(data))))
    return events


def _stream_chat(client: Any, payload: dict) -> list[tuple[str, dict]]:
    with client.stream("POST", f"{BASE}/chat", json=payload) as response:
        assert response.status_code == 200, response.read()
        assert response.headers["content-type"].startswith("text/event-stream")
        return _read_events(response)


def _chat(client: Any, scenario_id: str, message: str = "He go to work by bus.") -> list[tuple[str, dict]]:
    return _stream_chat(client, {"scenarioId": scenario_id, "message": message})


# ================================================================ 元信息 / 情景


def test_health(client: Any, fake_llm: FakeLLM) -> None:
    response = client.get(f"{BASE}/health")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["ok"] is True
    assert isinstance(body["scenarios"], int)
    assert body["provider"] == "fake"
    for key in ("degraded", "okCount", "failCount", "rates"):
        assert key in body


def test_scenarios_create_list_detail(client: Any, fake_llm: FakeLLM) -> None:
    plan = _create_scenario(client, cefr="B2")
    for key in ("id", "slug", "title_zh", "title_en", "topics", "provider"):
        assert key in plan, plan
    assert plan["provider"] == "fake"
    assert len(plan["topics"]) >= 6

    listing = client.get(f"{BASE}/scenarios")
    assert listing.status_code == 200
    items = listing.json()["items"]
    assert any(item["id"] == plan["id"] for item in items)
    row = next(item for item in items if item["id"] == plan["id"])
    assert row["cefr"] == "B2"
    assert row["topic_count"] >= 6
    assert row["domain"].startswith("接口测试-")

    detail = client.get(f"{BASE}/scenarios/{plan['id']}")
    assert detail.status_code == 200, detail.text
    body = detail.json()
    assert body["id"] == plan["id"]
    assert len(body["topics"]) >= 6
    topic = body["topics"][0]
    assert isinstance(topic["beats"], list) and len(topic["beats"]) >= 3
    assert isinstance(topic["target_lexis"], list) and topic["target_lexis"]
    assert topic["used_count"] == 0

    assert client.get(f"{BASE}/scenarios/does-not-exist").status_code == 404


def test_scenarios_bad_input(client: Any, fake_llm: FakeLLM) -> None:
    short = client.post(f"{BASE}/scenarios", json={"domain": "x"})
    assert short.status_code == 400
    assert short.json()["code"] == "BAD_INPUT"

    bad_cefr = client.post(f"{BASE}/scenarios", json={"domain": "商务谈判", "cefr": "Z9"})
    assert bad_cefr.status_code == 400
    assert bad_cefr.json()["code"] == "BAD_INPUT"


def test_scenarios_no_provider_409(client: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    def _boom(*args: Any, **kwargs: Any):
        raise ApiError("还没有配置模型供应商", code="no_provider", status=409)

    monkeypatch.setattr(llm_module, "get_llm", _boom)
    response = client.post(f"{BASE}/scenarios", json={"domain": "商务谈判"})
    assert response.status_code == 409
    assert response.json()["code"] == "no_provider"


# ================================================================ chat SSE


def test_chat_sse_event_order(client: Any, fake_llm: FakeLLM) -> None:
    scenario = _create_scenario(client)
    events = _chat(client, scenario["id"])
    names = [name for name, _ in events]

    assert "delta" in names
    assert names[-1] == "done"
    assert names[names.index("meta") :] == ["meta", "done"]
    # meta 之前只允许 delta / replace / annotations
    first_meta = names.index("meta")
    assert all(name in {"delta", "replace", "annotations"} for name in names[:first_meta])
    # 合格回复不需要重写
    assert "replace" not in names
    assert fake_llm.stream_calls == 1

    # 规则纠错（FakeLLM.mock → rule_analyze）抓到 "He go" → annotations 紧挨在 meta 之前
    assert "annotations" in names
    assert names.index("annotations") == first_meta - 1
    annotations = events[names.index("annotations")][1]
    assert annotations["provider"] == "rule-based"
    codes = [error["code"] for error in annotations["errors"]]
    assert "agreement.subject_verb" in codes
    for error in annotations["errors"]:
        assert {"code", "span", "correction", "explain_zh", "severity", "confidence"} <= set(error)

    meta = events[first_meta][1]
    done = events[names.index("done")][1]
    assert meta == done
    assert meta["provider"] == "fake"
    assert meta["conversationId"]
    assert meta["topicId"]
    assert meta["topicTitle"]
    assert meta["cefr"] == "B1"
    assert isinstance(meta["ttftMs"], int) and meta["ttftMs"] >= 0
    assert isinstance(meta["latencyMs"], int)
    assert meta["vocabTargets"] == []
    assert meta["vocabHits"] == []
    assert isinstance(meta["candidates"], list)
    assert meta["memoryRevision"] >= 1
    assert isinstance(meta["memoryFacts"], list)
    assert meta["sources"] == []
    assert meta["latencyMs"] >= meta["ttftMs"] >= 0

    # 空行分隔的 SSE 帧里不能有裸 \n 破坏 data
    assert all(isinstance(payload, dict) for _, payload in events)


def test_chat_persists_conversation_and_restores(client: Any, fake_llm: FakeLLM) -> None:
    scenario = _create_scenario(client)
    events = _chat(client, scenario["id"], message="She have two brothers.")
    meta = dict(events)["done"]
    conversation_id = meta["conversationId"]

    detail = client.get(f"{BASE}/conversations/{conversation_id}")
    assert detail.status_code == 200, detail.text
    body = detail.json()
    assert body["id"] == conversation_id
    assert body["user_id"]
    assert [message["role"] for message in body["messages"]] == ["user", "assistant"]
    assert body["messages"][0]["content_md"] == "She have two brothers."
    assert body["messages"][1]["content_md"].startswith("That makes sense")
    assert body["last_message_at"]

    # 刷新页面后纠错下划线不能丢：user 消息要带回 errors，assistant 不挂
    history_errors = body["messages"][0]["errors"]
    assert history_errors, "user 消息应带上历史纠错"
    assert {"code", "span", "correction", "explain_zh", "severity", "confidence"} <= set(history_errors[0])
    assert history_errors[0]["code"] == "agreement.subject_verb"
    assert history_errors[0]["span"] == "She have"
    assert "errors" not in body["messages"][1]

    history = client.get(f"{BASE}/scenarios/{scenario['id']}/conversations")
    assert history.status_code == 200
    items = history.json()["items"]
    assert any(item["id"] == conversation_id for item in items)
    item = next(item for item in items if item["id"] == conversation_id)
    assert item["turns"] == 1
    assert item["topic_title"]

    # 第二轮复用会话（conversationId），历史被带进上下文
    second = _stream_chat(
        client,
        {"scenarioId": scenario["id"], "conversationId": conversation_id, "message": "He go to work by bus."},
    )
    second_meta = dict(second)["done"]
    assert second_meta["conversationId"] == conversation_id
    detail2 = client.get(f"{BASE}/conversations/{conversation_id}").json()
    assert len(detail2["messages"]) == 4


def test_chat_repair_replace(client: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _use_llm(monkeypatch, FakeLLM(replies=[BAD_REPLY, GOOD_REPLY]))
    scenario = _create_scenario(client)
    events = _chat(client, scenario["id"])
    names = [name for name, _ in events]
    assert "replace" in names, names
    replaced = events[names.index("replace")][1]
    assert replaced["text"] == GOOD_REPLY
    assert names.index("replace") < names.index("meta")
    assert names[-1] == "done"
    assert fake.stream_calls == 2


def test_chat_upstream_error_event(client: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    _use_llm(monkeypatch, FakeLLM(stream_error=RuntimeError("upstream exploded")))
    scenario = _create_scenario(client)
    events = _chat(client, scenario["id"])
    names = [name for name, _ in events]
    assert names[-1] == "error", names
    payload = dict(events)["error"]
    assert payload["code"] == "UPSTREAM_ERROR"
    assert payload["retryable"] is True
    assert "meta" not in names and "done" not in names


def test_chat_quota_429(client: Any, fake_llm: FakeLLM, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        settings_module,
        "get_settings",
        lambda user_id: {**settings_module.DEFAULTS, "daily_quota": 0},
    )
    scenario = _create_scenario(client)
    response = client.post(f"{BASE}/chat", json={"scenarioId": scenario["id"], "message": "hello there"})
    assert response.status_code == 429
    body = response.json()
    assert body["code"] == "QUOTA_EXCEEDED"
    assert body["message"]


def test_chat_bad_input_400(client: Any, fake_llm: FakeLLM) -> None:
    scenario = _create_scenario(client)
    missing_scenario = client.post(f"{BASE}/chat", json={"message": "hi"})
    assert missing_scenario.status_code == 400
    assert missing_scenario.json()["code"] == "BAD_INPUT"

    empty_message = client.post(f"{BASE}/chat", json={"scenarioId": scenario["id"], "message": ""})
    assert empty_message.status_code == 400

    too_long = client.post(f"{BASE}/chat", json={"scenarioId": scenario["id"], "message": "x" * 801})
    assert too_long.status_code == 400

    unknown_scenario = client.post(f"{BASE}/chat", json={"scenarioId": "nope", "message": "hello"})
    assert unknown_scenario.status_code == 404
    assert unknown_scenario.json()["code"] == "NOT_FOUND"


def test_chat_with_topic_id(client: Any, fake_llm: FakeLLM) -> None:
    plan = _create_scenario(client)
    detail = client.get(f"{BASE}/scenarios/{plan['id']}").json()
    topic = detail["topics"][-1]
    events = _stream_chat(
        client,
        {"scenarioId": plan["id"], "topicId": topic["id"], "message": "He go to work by bus."},
    )
    meta = dict(events)["done"]
    assert meta["topicId"] == topic["id"]
    assert meta["topicTitle"] == topic["title"]

    refreshed = client.get(f"{BASE}/scenarios/{plan['id']}").json()
    used = next(item for item in refreshed["topics"] if item["id"] == topic["id"])
    assert used["used_count"] == 1


def test_chat_forbidden_conversation(
    client: Any, second_user_client: Any, fake_llm: FakeLLM
) -> None:
    scenario = _create_scenario(client)
    meta = dict(_chat(client, scenario["id"]))["done"]
    conversation_id = meta["conversationId"]

    other = second_user_client("apibob")
    forbidden = other.post(
        f"{BASE}/chat",
        json={"scenarioId": scenario["id"], "conversationId": conversation_id, "message": "hello"},
    )
    assert forbidden.status_code == 403
    assert forbidden.json()["code"] == "FORBIDDEN"

    hidden = other.get(f"{BASE}/conversations/{conversation_id}")
    assert hidden.status_code == 404
    assert not other.get(f"{BASE}/scenarios/{scenario['id']}/conversations").json()["items"]


# ================================================================ 学习闭环


def test_errors_archive(client: Any, fake_llm: FakeLLM) -> None:
    scenario = _create_scenario(client)
    _chat(client, scenario["id"], message="He go to work by bus.")
    body = client.get(f"{BASE}/errors").json()
    assert isinstance(body["items"], list)
    assert body["items"], "纠错分析应留下错误档案"
    assert body["active"] >= 1
    assert body["improved"] == 0
    codes = {item["code"] for item in body["items"]}
    assert "agreement.subject_verb" in codes
    item = next(item for item in body["items"] if item["code"] == "agreement.subject_verb")
    assert item["label"]
    assert item["occurrences"] >= 1
    assert item["trend"] in {"up", "down", "flat", "new"}
    assert item["improved"] is False


def test_memory_state(client: Any, fake_llm: FakeLLM) -> None:
    scenario = _create_scenario(client)
    empty = client.get(f"{BASE}/memory/{scenario['id']}")
    assert empty.status_code == 200
    assert empty.json()["counts"] == {"facts": 0, "threads": 0, "beats": 0}

    _chat(client, scenario["id"], message="We need 3 trucks by Friday.")
    memory = client.get(f"{BASE}/memory/{scenario['id']}").json()
    assert memory["revision"] >= 1
    assert memory["counts"]["beats"] >= 1


def test_knowledge_card(client: Any, fake_llm: FakeLLM) -> None:
    response = client.get(f"{BASE}/knowledge/agreement.subject_verb")
    assert response.status_code == 200, response.text
    card = response.json()
    assert card["code"] == "agreement.subject_verb"
    assert card["label"]
    assert len(card["title"]) >= 2
    assert len(card["rule_md"]) >= 10
    assert isinstance(card["examples"], list) and card["examples"]
    # 第二次命中 DB，不重复生成
    again = client.get(f"{BASE}/knowledge/agreement.subject_verb").json()
    assert again == card

    unknown = client.get(f"{BASE}/knowledge/not.a.real.code")
    assert unknown.status_code == 400
    assert unknown.json()["code"] == "BAD_CODE"


# ================================================================ 生词库


def test_vocab_flow(client: Any, fake_llm: FakeLLM) -> None:
    saved = client.post(
        f"{BASE}/vocab",
        json={"surface": "Negotiate", "context": "We need to negotiate the deadline."},
    )
    assert saved.status_code == 200, saved.text
    body = saved.json()
    assert body["lemma"] == "negotiate"
    for key in ("glossZh", "pos", "nextReviewAt", "intervalDays"):
        assert key in body
    assert body["intervalDays"] >= 1
    assert body["nextReviewAt"]

    listing = client.get(f"{BASE}/vocab").json()
    item = next(row for row in listing["items"] if row["lemma"] == "negotiate")
    assert item["surface"] == "Negotiate"
    assert item["context"] == "We need to negotiate the deadline."
    assert item["due"] is False  # 刚排程，还没到期
    assert item["nextReviewAt"] == body["nextReviewAt"]
    assert 0.0 <= item["mastery"] <= 1.0
    assert isinstance(listing["dueCount"], int)

    reviewed = client.post(f"{BASE}/vocab/review", json={"lemma": "negotiate", "rating": 3})
    assert reviewed.status_code == 200, reviewed.text
    review_body = reviewed.json()
    assert review_body["lemma"] == "negotiate"
    assert review_body["intervalDays"] >= 1
    assert review_body["nextReviewAt"] > item["nextReviewAt"]  # 排程向后推进
    assert 0.0 <= review_body["mastery"] <= 1.0


def test_vocab_bad_input_and_missing(client: Any, fake_llm: FakeLLM) -> None:
    assert client.post(f"{BASE}/vocab", json={"surface": "x"}).status_code == 400
    assert client.post(f"{BASE}/vocab", json={"surface": "quarantine", "context": "x" * 301}).status_code == 400
    missing = client.post(f"{BASE}/vocab/review", json={"lemma": "unknownword", "rating": 3})
    assert missing.status_code == 404
    assert missing.json()["code"] == "NOT_FOUND"
    assert client.post(f"{BASE}/vocab/review", json={"lemma": "unknownword", "rating": 9}).status_code == 400


# ================================================================ 偏好契约


def test_contract_get_put(client: Any) -> None:
    default = client.get(f"{BASE}/contract")
    assert default.status_code == 200
    base = default.json()
    assert base["must_use_words"] == []
    assert base["correction_intensity"] == "medium"
    assert base["difficulty_delta"] == 0
    assert base["max_reply_words"] == 90

    payload = {
        "must_use_words": ["budget", "deadline", "invoice", "shipment"],
        "grammar_focus": ["tense.past_simple", "not.a.code"],
        "correction_intensity": "strict",
        "difficulty_delta": 1,
        "max_reply_words": 120,
    }
    put = client.put(f"{BASE}/contract", json=payload)
    assert put.status_code == 200, put.text
    body = put.json()
    assert body["contract"]["must_use_words"] == ["budget", "deadline", "invoice"]
    assert body["contract"]["grammar_focus"] == ["tense.past_simple"]
    assert body["contract"]["correction_intensity"] == "strict"
    assert body["contract"]["difficulty_delta"] == 1
    assert body["contract"]["max_reply_words"] == 120
    assert any("3 个词" in warning for warning in body["warnings"])
    assert any("无法识别" in warning for warning in body["warnings"])

    again = client.get(f"{BASE}/contract").json()
    assert again == body["contract"]

    # 非法参数 → 回退默认值 + warning（不是 400）
    invalid = client.put(f"{BASE}/contract", json={"correction_intensity": "insane"})
    assert invalid.status_code == 200
    assert invalid.json()["contract"]["correction_intensity"] == "medium"
    assert invalid.json()["warnings"]


# ================================================================ 资料导入


TEXT_DOC = (
    "The northern terminal handles about forty containers a day.\n\n"
    "During the storm season it closes early, so shipments are rerouted to the western yard.\n\n"
    "Storage fees are charged per container per night, and the rate doubles after Friday."
)


def test_documents_text_import_and_delete(client: Any) -> None:
    created = client.post(f"{BASE}/documents", json={"filename": "notes.txt", "content": TEXT_DOC})
    assert created.status_code == 200, created.text
    body = created.json()
    assert body["filename"] == "notes.txt"
    assert body["chunks"] >= 1
    document_id = body["id"]

    listing = client.get(f"{BASE}/documents").json()
    assert any(item["id"] == document_id for item in listing["items"])

    deleted = client.delete(f"{BASE}/documents/{document_id}")
    assert deleted.status_code == 200
    assert deleted.json() == {"ok": True}
    listing2 = client.get(f"{BASE}/documents").json()
    assert all(item["id"] != document_id for item in listing2["items"])
    assert client.delete(f"{BASE}/documents/{document_id}").status_code == 404


def test_documents_text_import_rejects_pdf(client: Any) -> None:
    response = client.post(f"{BASE}/documents", json={"filename": "slides.pdf", "content": TEXT_DOC})
    assert response.status_code == 415
    assert response.json()["code"] == "UNSUPPORTED_TYPE"

    short = client.post(f"{BASE}/documents", json={"filename": "notes.txt", "content": "too short"})
    assert short.status_code == 400
    assert short.json()["code"] == "BAD_INPUT"


def test_documents_upload(client: Any) -> None:
    response = client.post(
        f"{BASE}/documents/upload",
        files={"file": ("guide.txt", TEXT_DOC.encode("utf-8"), "text/plain")},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["filename"] == "guide.txt"
    assert body["kind"], "解析出的格式类型不能为空（txt / text / docx …）"
    assert body["chars"] == len(TEXT_DOC)
    assert body["chunks"] >= 1
    assert body["id"]


def test_documents_upload_rejects_unsupported_and_empty(client: Any) -> None:
    unsupported = client.post(
        f"{BASE}/documents/upload",
        files={"file": ("scan.png", b"\x89PNG\r\n\x1a\n" + b"x" * 64, "image/png")},
    )
    assert unsupported.status_code == 422
    assert unsupported.json()["code"] == "EXTRACT_FAILED"

    empty_text = client.post(
        f"{BASE}/documents/upload",
        files={"file": ("tiny.txt", b"abc", "text/plain")},
    )
    assert empty_text.status_code == 422
    assert empty_text.json()["code"] in {"EMPTY_TEXT", "EXTRACT_FAILED"}


# ================================================================ 成本看板 / 已删接口


def test_stats_after_chat(client: Any, fake_llm: FakeLLM) -> None:
    scenario = _create_scenario(client)
    _chat(client, scenario["id"], message="He go to work by bus.")
    response = client.get(f"{BASE}/stats")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["turns24h"] >= 1
    assert body["tokens24h"] > 0
    assert body["costYuan24h"] >= 0
    assert 0 <= body["quality"]["pctEndsWithQuestion"] <= 100
    assert body["quality"]["measured"] >= 1
    assert isinstance(body["quality"]["topFlags"], list)
    budget = body["budget"]
    for key in ("used", "limit", "ratio", "degrade"):
        assert key in budget
    assert isinstance(budget["degrade"], bool)
    assert isinstance(body["health"], dict)


def test_payment_and_transfer_routes_removed(client: Any) -> None:
    for path in (
        f"{BASE}/plans",
        f"{BASE}/entitlement",
        f"{BASE}/orders",
        f"{BASE}/orders/abc",
        f"{BASE}/auth/transfer-code",
        f"{BASE}/auth/transfer",
    ):
        assert client.get(path).status_code == 404, path

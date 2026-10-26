"""教材库 API：上传解析、分类、双池权限、教材问答、异常降级。"""
from __future__ import annotations

import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.capabilities.library import ocr, service
from app.core.errors import ApiError
from app.main import app

SAMPLE = """第一章 弹性力学基础

应力张量描述一点的受力状态。在直角坐标系中，应力张量是一个二阶对称张量，
共有六个独立分量：三个正应力与三个剪应力。

1.2 平衡微分方程
应力张量必须满足平衡微分方程，否则物体无法保持静力平衡。
平衡方程的形式为应力分量对坐标的偏导数与体力之和为零。

1.3 本构关系
各向同性线弹性体的本构关系由广义胡克定律给出，需要两个独立弹性常数：
弹性模量 E 与泊松比 nu。
"""


class FakeLLM:
    """假模型：可复现、不联网。"""

    def __init__(self, reply: str = "应力张量需要满足平衡微分方程 [1]。"):
        self.reply = reply
        self.calls = 0

    async def stream(self, messages, **kwargs):  # noqa: ANN001, ANN003
        self.calls += 1
        for start in range(0, len(self.reply), 6):
            yield self.reply[start : start + 6]

    async def embed(self, texts, model=None):  # noqa: ANN001, ANN003
        return []


def _upload(client: TestClient, name: str, content: bytes, **data) -> dict:
    payload = {"visibility": "private", "ocr_mode": "auto"}
    payload.update(data)
    resp = client.post(
        "/api/c/library/documents/upload",
        files={"file": (name, content)},
        data=payload,
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def _wait(client: TestClient, document_id: int, timeout: float = 20.0) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        detail = client.get(f"/api/c/library/documents/{document_id}").json()
        if detail["status"] not in ("queued", "parsing", "indexing"):
            return detail
        time.sleep(0.15)
    raise AssertionError(f"教材 {document_id} 解析超时：{detail}")


def _sse(client: TestClient, payload: dict) -> list[tuple[str, str]]:
    events: list[tuple[str, str]] = []
    with client.stream("POST", "/api/c/library/qa", json=payload) as response:
        assert response.status_code == 200, response.read()
        event = ""
        for line in response.iter_lines():
            if line.startswith("event:"):
                event = line.split(":", 1)[1].strip()
            elif line.startswith("data:"):
                events.append((event, line.split(":", 1)[1].strip()))
    return events


def _json_events(events: list[tuple[str, str]]) -> dict[str, list]:
    import json

    grouped: dict[str, list] = {}
    for name, raw in events:
        grouped.setdefault(name, []).append(json.loads(raw))
    return grouped


# ---------------------------------------------------------------- 概览


def test_health_reports_formats_and_ocr(auth_client: TestClient):
    data = auth_client.get("/api/c/library/health").json()
    assert data["ok"] is True
    assert "pdf" in data["formats"]
    assert "docx" in data["formats"]
    assert "image" in data["formats"]
    assert data["max_upload_mb"] > 0
    assert "available" in data["ocr"]


# ---------------------------------------------------------------- 分类


def test_course_lifecycle(auth_client: TestClient):
    created = auth_client.post("/api/c/library/courses", json={"name": "弹性力学", "term": "2026 秋"})
    assert created.status_code == 200, created.text
    course = created.json()
    assert course["name"] == "弹性力学"
    assert course["document_count"] == 0

    patched = auth_client.patch(
        f"/api/c/library/courses/{course['id']}", json={"name": "弹性力学（改）"}
    )
    assert patched.json()["name"] == "弹性力学（改）"

    listing = auth_client.get("/api/c/library/courses").json()
    assert any(item["id"] == course["id"] for item in listing)

    removed = auth_client.delete(f"/api/c/library/courses/{course['id']}")
    assert removed.status_code == 200
    assert all(item["id"] != course["id"] for item in auth_client.get("/api/c/library/courses").json())


def test_upload_rejects_unsupported_extension(auth_client: TestClient):
    resp = auth_client.post(
        "/api/c/library/documents/upload",
        files={"file": ("讲义.doc", b"legacy")},
        data={"visibility": "private", "ocr_mode": "auto"},
    )
    assert resp.status_code == 415
    assert resp.json()["code"] == "unsupported_format"


# ---------------------------------------------------------------- 上传与解析


def test_upload_txt_becomes_searchable(auth_client: TestClient):
    data = _upload(auth_client, "弹性力学讲义.txt", SAMPLE.encode("utf-8"))
    document_id = data["document"]["id"]
    assert data["job_id"]

    detail = _wait(auth_client, document_id)
    assert detail["status"] in ("ready", "partial"), detail
    assert detail["chunk_count"] >= 1
    assert detail["char_count"] > 100

    chunks = auth_client.get(f"/api/c/library/documents/{document_id}/chunks").json()
    assert chunks["total"] >= 1
    assert any("应力" in item["text"] for item in chunks["items"])


def test_reparse_and_delete(auth_client: TestClient):
    data = _upload(auth_client, "可删除.txt", SAMPLE.encode("utf-8"))
    document_id = data["document"]["id"]
    _wait(auth_client, document_id)

    again = auth_client.post(f"/api/c/library/documents/{document_id}/reparse")
    assert again.status_code == 200
    assert again.json()["ok"] is True
    _wait(auth_client, document_id)

    assert auth_client.delete(f"/api/c/library/documents/{document_id}").status_code == 200
    assert auth_client.get(f"/api/c/library/documents/{document_id}").status_code == 404


# ---------------------------------------------------------------- 双池权限


def test_private_document_hidden_from_other_user(auth_client: TestClient, second_user_client):
    data = _upload(auth_client, "私有讲义.txt", SAMPLE.encode("utf-8"))
    document_id = data["document"]["id"]
    _wait(auth_client, document_id)

    other = second_user_client("lib_other_1")
    assert other.get(f"/api/c/library/documents/{document_id}").status_code == 404
    assert all(
        item["id"] != document_id for item in other.get("/api/c/library/documents").json()
    )


def test_shared_document_readable_but_not_editable(auth_client: TestClient, second_user_client):
    data = _upload(auth_client, "共享讲义.txt", SAMPLE.encode("utf-8"), visibility="shared")
    document_id = data["document"]["id"]
    _wait(auth_client, document_id)

    other = second_user_client("lib_other_2")
    readable = other.get(f"/api/c/library/documents/{document_id}")
    assert readable.status_code == 200
    assert readable.json()["is_owner"] is False

    patched = other.patch(
        f"/api/c/library/documents/{document_id}", json={"title": "偷偷改名"}
    )
    assert patched.status_code == 403
    assert other.delete(f"/api/c/library/documents/{document_id}").status_code == 403


def test_ask_rejects_foreign_document(auth_client: TestClient, second_user_client):
    data = _upload(auth_client, "别人的书.txt", SAMPLE.encode("utf-8"))
    document_id = data["document"]["id"]
    _wait(auth_client, document_id)

    other = second_user_client("lib_other_3")
    resp = other.post(
        "/api/c/library/qa",
        json={"question": "应力张量是什么", "document_ids": [document_id]},
    )
    assert resp.status_code == 403
    assert resp.json()["code"] == "forbidden"


# ---------------------------------------------------------------- 问答


def test_ask_streams_answer_with_citations(auth_client: TestClient, monkeypatch):
    data = _upload(auth_client, "问答用教材.txt", SAMPLE.encode("utf-8"))
    document_id = data["document"]["id"]
    _wait(auth_client, document_id)

    fake = FakeLLM("应力张量必须满足平衡微分方程 [1]。")
    monkeypatch.setattr("app.capabilities.library.router.load_llm", lambda user_id: fake)

    events = _json_events(
        _sse(auth_client, {"question": "应力张量要满足什么方程？", "document_ids": [document_id]})
    )
    assert fake.calls == 1
    assert "status" in events
    assert "delta" in events

    done = events["done"][0]
    assert done["answer"]
    assert done["citations"], "必须给出出处"
    assert done["citations"][0]["document_id"] == document_id
    assert done["citations"][0]["loc_label"]
    assert done["meta"]["citation_ok"] is True
    assert done["meta"]["retrieved"] >= 1


def test_ask_without_match_skips_model(auth_client: TestClient, monkeypatch):
    data = _upload(auth_client, "无关教材.txt", SAMPLE.encode("utf-8"))
    document_id = data["document"]["id"]
    _wait(auth_client, document_id)

    fake = FakeLLM()
    monkeypatch.setattr("app.capabilities.library.router.load_llm", lambda user_id: fake)

    events = _json_events(
        _sse(auth_client, {"question": "光合作用的光反应发生在哪里", "document_ids": [document_id]})
    )
    done = events["done"][0]
    assert fake.calls == 0, "检索不到就不该调用模型，避免编造"
    assert done["meta"]["empty"] is True
    assert done["citations"] == []
    assert "没有找到" in done["answer"]


def test_ask_marks_bad_citation_markers(auth_client: TestClient, monkeypatch):
    data = _upload(auth_client, "引用越界教材.txt", SAMPLE.encode("utf-8"))
    document_id = data["document"]["id"]
    _wait(auth_client, document_id)

    fake = FakeLLM("结论见 [1] 与 [99]。")
    monkeypatch.setattr("app.capabilities.library.router.load_llm", lambda user_id: fake)

    events = _json_events(
        _sse(auth_client, {"question": "应力张量有几个独立分量", "document_ids": [document_id]})
    )
    done = events["done"][0]
    assert done["meta"]["bad_markers"] == [99]
    assert [item["index"] for item in done["citations"]] == [1]


def test_ask_with_empty_scope_searches_all_visible(auth_client: TestClient, monkeypatch):
    """document_ids 为空 = 在全部可见教材里找，不应报 400。"""
    monkeypatch.setattr(
        "app.capabilities.library.router.load_llm", lambda user_id: FakeLLM("没有相关段落。")
    )
    resp = auth_client.post("/api/c/library/qa", json={"question": "随便问问", "document_ids": []})
    assert resp.status_code == 200


# ---------------------------------------------------------------- 解析异常


def _scanned_pdf(workdir: Path) -> bytes:
    """构造一份没有文本层的 PDF（整页是图片）。"""
    path = workdir / "scan.pdf"
    Image.new("RGB", (600, 800), "white").save(path, "PDF")
    return path.read_bytes()


def test_scanned_pdf_without_ocr_engine_is_error(auth_client: TestClient, workdir, monkeypatch):
    def boom(*args, **kwargs):  # noqa: ANN002, ANN003
        raise ApiError("没有可用的 OCR 引擎", code="ocr_unavailable", status=503)

    monkeypatch.setattr(ocr, "ocr_pdf", boom)
    data = _upload(auth_client, "扫描件.pdf", _scanned_pdf(workdir))
    detail = _wait(auth_client, data["document"]["id"])
    assert detail["status"] == "error"
    assert "OCR" in (detail["error"] or "")
    assert detail["chunk_count"] == 0


def test_scanned_pdf_ocr_success_becomes_ready(auth_client: TestClient, workdir, monkeypatch):
    def fake_ocr(path, pages, engine=None, dpi=200):  # noqa: ANN001, ANN003
        return ocr.OcrOutcome(
            pages=[
                ocr.OcrPage(
                    1,
                    "第一章 应力状态与应变\n应力张量必须满足平衡微分方程，否则无法保持静力平衡。",
                    0.88,
                ),
            ],
            engine="vision",
        )

    monkeypatch.setattr(ocr, "ocr_pdf", fake_ocr)
    data = _upload(auth_client, "扫描件2.pdf", _scanned_pdf(workdir))
    document_id = data["document"]["id"]
    detail = _wait(auth_client, document_id)

    assert detail["status"] == "ready", detail
    assert detail["ocr_engine"] == "vision"
    assert detail["ocr_confidence"] == pytest.approx(0.88)
    assert detail["chunk_count"] >= 1
    assert any("OCR" in warning["message"] for warning in detail["warnings"])

    # OCR 出来的文字必须可检索，并且定位到原页码
    hits = auth_client.get(
        f"/api/c/library/search?q=平衡微分方程&document_ids={document_id}"
    ).json()
    assert hits["hits"]
    assert hits["hits"][0]["loc_label"] == "第 1 页"


def test_ocr_off_on_scanned_pdf_reports_actionable_error(auth_client: TestClient, workdir):
    data = _upload(auth_client, "扫描件3.pdf", _scanned_pdf(workdir), ocr_mode="off")
    detail = _wait(auth_client, data["document"]["id"])
    assert detail["status"] == "error"
    assert "OCR" in (detail["error"] or "")


# ---------------------------------------------------------------- 解析失败不污染旧索引


def test_failed_reparse_clears_old_chunks(auth_client: TestClient, workdir, monkeypatch):
    data = _upload(auth_client, "先好后坏.txt", SAMPLE.encode("utf-8"))
    document_id = data["document"]["id"]
    _wait(auth_client, document_id)

    # 把已落盘的文件换成空内容，再重新解析
    for candidate in service.uploads_root().glob(f"{document_id}.*"):
        candidate.write_text("", encoding="utf-8")

    with pytest.raises(ApiError):
        service.ingest_document(document_id, 1, ocr_mode="auto")

    detail = auth_client.get(f"/api/c/library/documents/{document_id}").json()
    assert detail["status"] == "error"
    assert detail["chunk_count"] == 0
    chunks = auth_client.get(f"/api/c/library/documents/{document_id}/chunks").json()
    assert chunks["total"] == 0


# ---------------------------------------------------------------- 工具注册


def test_tools_are_registered(auth_client: TestClient):
    tools = auth_client.get("/api/tools").json()
    names = {item["name"] for item in tools}
    assert "library_search" in names
    assert "library_list_documents" in names


def test_capability_listed_in_nav(auth_client: TestClient):
    caps = auth_client.get("/api/capabilities").json()
    library = next(item for item in caps if item["id"] == "library")
    assert library["nav"]["path"] == "/cap/library"
    assert library["enabled"] is True

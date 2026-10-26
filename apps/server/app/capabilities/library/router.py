"""教材库 API（前缀 /api/c/library，全部要求登录）。

权限模型（双池）
- 读：`user_id = 我 or visibility = 'shared'`
- 写 / 删：owner 或管理员；别人的 shared 教材只能读，不能改
- 问答：检索范围先与「我能看到的教材」取交集，再与「我点名的教材」取交集——
  越权传别人的 private 教材 id 只会得到空结果，不会泄露内容
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from ...core.auth import current_user
from ...core.errors import ApiError
from ...core.jobs import jobs
from ...models import User
from . import ocr, qa, retrieval, service, store
from .llm import load_llm, try_load_llm
from .parsers import LIBRARY_EXTENSIONS, detect_kind
from .streaming import SSE_HEADERS, sse

log = logging.getLogger(__name__)
router = APIRouter(tags=["library"])

MAX_UPLOAD_BYTES = 60 * 1024 * 1024   # 与 nginx 的 64m 对齐，留一点余量
CHUNK_READ = 1024 * 1024
VISIBILITIES = {"private", "shared"}
OCR_MODES = {"off", "auto", "force"}


def _uid(user: User) -> int:
    return user.id or 0


def _is_admin(user: User) -> bool:
    return user.role == "admin"


def _require_edit(row: dict, user: User) -> None:
    if not store.can_edit(row, _uid(user), _is_admin(user)):
        raise ApiError("只有创建者或管理员可以修改这份教材", code="forbidden", status=403)


# ---------------------------------------------------------------- 序列化


def _warnings(row: dict) -> list[dict]:
    meta = store.json_load(row.get("meta_json"), {}) or {}
    return list(meta.get("warnings") or [])


def _doc_out(row: dict, viewer_id: int) -> dict:
    meta = store.json_load(row.get("meta_json"), {}) or {}
    return {
        "id": int(row["id"]),
        "title": row.get("title") or "",
        "kind": row.get("kind") or "",
        "filename": row.get("filename"),
        "size": int(row.get("size") or 0),
        "status": row.get("status") or "queued",
        "progress": int(row.get("progress") or 0),
        "message": row.get("message"),
        "error": row.get("error"),
        "visibility": row.get("visibility") or "private",
        "course_id": row.get("course_id"),
        "page_count": int(row.get("page_count") or 0),
        "char_count": int(row.get("char_count") or 0),
        "chunk_count": int(row.get("chunk_count") or 0),
        "ocr_mode": row.get("ocr_mode") or "auto",
        "ocr_engine": row.get("ocr_engine"),
        "ocr_pages": int(row.get("ocr_pages") or 0),
        "ocr_confidence": row.get("ocr_confidence"),
        "parse_warning": row.get("parse_warning"),
        "warnings": _warnings(row),
        "parse": meta.get("parse") or {},
        "ocr": meta.get("ocr") or {},
        "is_owner": int(row.get("user_id") or 0) == viewer_id,
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
    }


def _course_out(row: dict) -> dict:
    return {
        "id": int(row["id"]),
        "name": row.get("name") or "",
        "color": row.get("color") or "#14687b",
        "term": row.get("term") or "",
        "visibility": row.get("visibility") or "private",
        "document_count": int(row.get("document_count") or 0),
        "is_owner": bool(row.get("is_owner")),
        "created_at": row.get("created_at"),
    }


def _load_visible(document_id: int, user: User) -> dict:
    row = store.one(
        f"SELECT * FROM documents WHERE id = :id AND {store.scope_sql()}",
        id=document_id,
        uid=_uid(user),
    )
    if row is None:
        raise ApiError("教材不存在，或你没有访问权限", code="not_found", status=404)
    return row


# ---------------------------------------------------------------- 概览


@router.get("/health")
async def health(user: User = Depends(current_user)) -> dict:
    uid = _uid(user)
    counts = store.one(
        f"SELECT count(*) AS total, "
        "sum(CASE WHEN status = 'ready' THEN 1 ELSE 0 END) AS ready, "
        "sum(CASE WHEN status = 'partial' THEN 1 ELSE 0 END) AS partial, "
        "sum(CASE WHEN status = 'error' THEN 1 ELSE 0 END) AS errors "
        f"FROM documents WHERE {store.scope_sql()}",
        uid=uid,
    ) or {}
    chunks = store.one(
        "SELECT count(*) AS n FROM chunks c JOIN documents d ON d.id = c.document_id "
        f"WHERE {store.scope_sql('d')}",
        uid=uid,
    ) or {}
    return {
        "ok": True,
        "ocr": ocr.probe(),
        "formats": sorted({kind for kind in LIBRARY_EXTENSIONS.values()}),
        "documents": {
            "total": int(counts.get("total") or 0),
            "ready": int(counts.get("ready") or 0),
            "partial": int(counts.get("partial") or 0),
            "error": int(counts.get("errors") or 0),
        },
        "chunks": int(chunks.get("n") or 0),
        "max_upload_mb": MAX_UPLOAD_BYTES // (1024 * 1024),
    }


# ---------------------------------------------------------------- 课程（分类）


class CourseIn(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    color: str = "#14687b"
    term: str = ""
    visibility: str = "private"


class CoursePatch(BaseModel):
    name: str | None = None
    color: str | None = None
    term: str | None = None
    visibility: str | None = None


@router.get("/courses")
async def list_courses(user: User = Depends(current_user)) -> list[dict]:
    rows = store.q(
        "SELECT c.*, "
        "(SELECT count(*) FROM documents d WHERE d.course_id = c.id) AS document_count, "
        "CASE WHEN c.user_id = :uid THEN 1 ELSE 0 END AS is_owner "
        f"FROM courses c WHERE {store.scope_sql('c')} ORDER BY c.created_at",
        uid=_uid(user),
    )
    return [_course_out(row) for row in rows]


@router.post("/courses")
async def create_course(body: CourseIn, user: User = Depends(current_user)) -> dict:
    if body.visibility not in VISIBILITIES:
        raise ApiError("visibility 只能是 private 或 shared", code="invalid_visibility")
    name = body.name.strip()
    if not name:
        raise ApiError("分类名称不能为空", code="invalid_name")
    course_id = store.insert(
        "INSERT INTO courses (user_id, visibility, name, color, term, created_at) "
        "VALUES (:uid, :visibility, :name, :color, :term, :now)",
        uid=_uid(user),
        visibility=body.visibility,
        name=name,
        color=body.color,
        term=body.term.strip(),
        now=store.now_iso(),
    )
    row = store.one(
        "SELECT *, 0 AS document_count, 1 AS is_owner FROM courses WHERE id = :id", id=course_id
    )
    if row is None:  # pragma: no cover - 插入后必然能读到
        raise ApiError("分类创建失败", code="db_error", status=500)
    log.info("新建教材分类 %s by %s", name, _uid(user))
    return _course_out(row)


@router.patch("/courses/{course_id}")
async def update_course(
    course_id: int, body: CoursePatch, user: User = Depends(current_user)
) -> dict:
    row = store.one("SELECT * FROM courses WHERE id = :id", id=course_id)
    if row is None:
        raise ApiError("分类不存在", code="not_found", status=404)
    _require_edit(row, user)
    fields: dict[str, Any] = {}
    if body.name is not None:
        fields["name"] = body.name.strip()[:60]
    if body.color is not None:
        fields["color"] = body.color
    if body.term is not None:
        fields["term"] = body.term.strip()
    if body.visibility is not None:
        if body.visibility not in VISIBILITIES:
            raise ApiError("visibility 只能是 private 或 shared", code="invalid_visibility")
        fields["visibility"] = body.visibility
    if fields:
        assignments = ", ".join(f"{key} = :{key}" for key in fields)
        store.execute(
            f"UPDATE courses SET {assignments} WHERE id = :id", id=course_id, **fields
        )
    updated = store.one(
        "SELECT c.*, (SELECT count(*) FROM documents d WHERE d.course_id = c.id) AS document_count, "
        "CASE WHEN c.user_id = :uid THEN 1 ELSE 0 END AS is_owner FROM courses c WHERE c.id = :id",
        uid=_uid(user),
        id=course_id,
    )
    return _course_out(updated or row)


@router.delete("/courses/{course_id}")
async def delete_course(course_id: int, user: User = Depends(current_user)) -> dict:
    row = store.one("SELECT * FROM courses WHERE id = :id", id=course_id)
    if row is None:
        raise ApiError("分类不存在", code="not_found", status=404)
    _require_edit(row, user)
    moved = store.execute(
        "UPDATE documents SET course_id = NULL WHERE course_id = :id", id=course_id
    )
    store.execute("DELETE FROM courses WHERE id = :id", id=course_id)
    return {"ok": True, "documents_moved_to_uncategorized": moved}


# ---------------------------------------------------------------- 教材


@router.get("/documents")
async def list_documents(
    course: int | None = None,
    status: str = "",
    q: str = "",
    limit: int = Query(200, ge=1, le=500),
    user: User = Depends(current_user),
) -> list[dict]:
    clauses = [store.scope_sql("d")]
    params: dict[str, Any] = {"uid": _uid(user), "limit": limit}
    if course is not None:
        clauses.append("d.course_id = :course")
        params["course"] = course
    if status:
        clauses.append("d.status = :status")
        params["status"] = status
    if q.strip():
        clauses.append("d.title LIKE :like")
        params["like"] = f"%{q.strip()}%"
    rows = store.q(
        "SELECT d.* FROM documents d WHERE " + " AND ".join(clauses) + " ORDER BY d.created_at DESC LIMIT :limit",
        **params,
    )
    uid = _uid(user)
    return [_doc_out(row, uid) for row in rows]


@router.get("/documents/{document_id}")
async def get_document(document_id: int, user: User = Depends(current_user)) -> dict:
    row = _load_visible(document_id, user)
    return _doc_out(row, _uid(user))


@router.get("/documents/{document_id}/chunks")
async def preview_chunks(
    document_id: int,
    offset: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    q: str = "",
    user: User = Depends(current_user),
) -> dict:
    """预览解析结果——用来核对「解析对不对、OCR 准不准」，也是验收时要看的东西。"""
    row = _load_visible(document_id, user)
    if q.strip():
        result = await retrieval.search(
            _uid(user), q, document_ids=[document_id], limit=limit
        )
        return {
            "total": row.get("chunk_count") or 0,
            "items": [hit.as_citation(index) for index, hit in enumerate(result.hits, 1)],
            "mode": result.mode,
            "note": result.note,
        }
    items = store.q(
        "SELECT id, ord, text, heading_path, loc_label, loc_index, n_chars FROM chunks "
        "WHERE document_id = :doc ORDER BY ord LIMIT :limit OFFSET :offset",
        doc=document_id,
        limit=limit,
        offset=offset,
    )
    return {
        "total": int(row.get("chunk_count") or 0),
        "items": [
            {
                "chunk_id": int(item["id"]),
                "ord": int(item["ord"]),
                "text": item["text"],
                "heading_path": item["heading_path"],
                "loc_label": item["loc_label"],
                "loc_index": int(item["loc_index"]),
                "n_chars": int(item["n_chars"]),
            }
            for item in items
        ],
        "mode": "list",
    }


@router.post("/documents/upload")
async def upload_document(
    file: UploadFile = File(...),
    course_id: int | None = Form(None),
    visibility: str = Form("private"),
    ocr_mode: str = Form("auto"),
    title: str = Form(""),
    user: User = Depends(current_user),
) -> dict:
    filename = (file.filename or "").strip()
    if not filename:
        raise ApiError("没有收到文件名", code="invalid_file", status=400)
    kind = detect_kind(filename, allow_images=True)
    if visibility not in VISIBILITIES:
        raise ApiError("visibility 只能是 private 或 shared", code="invalid_visibility")
    if ocr_mode not in OCR_MODES:
        ocr_mode = "auto"

    uid = _uid(user)
    if course_id is not None:
        course = store.one("SELECT * FROM courses WHERE id = :id", id=course_id)
        if course is None:
            raise ApiError("分类不存在", code="not_found", status=404)
        if not store.can_edit(course, uid, _is_admin(user)):
            raise ApiError("不能用别人的分类归档", code="forbidden", status=403)

    now = store.now_iso()
    document_id = store.insert(
        "INSERT INTO documents (user_id, visibility, course_id, title, kind, filename, size, "
        "status, progress, message, page_count, char_count, chunk_count, ocr_mode, meta_json, "
        "created_at, updated_at) VALUES (:uid, :visibility, :course_id, :title, :kind, :filename, "
        "0, 'queued', 0, '等待解析', 0, 0, 0, :ocr_mode, '{}', :now, :now)",
        uid=uid,
        visibility=visibility,
        course_id=course_id,
        title=(title.strip() or Path(filename).stem)[:120],
        kind=kind,
        filename=filename[:200],
        ocr_mode=ocr_mode,
        now=now,
    )
    row = store.one("SELECT * FROM documents WHERE id = :id", id=document_id)
    if row is None:  # pragma: no cover
        raise ApiError("创建教材记录失败", code="db_error", status=500)

    # 分块写入，避免 60MB 文件一次性进内存
    suffix = Path(filename).suffix.lower()
    target = service.uploads_root() / f"{document_id}{suffix}"
    size = 0
    try:
        with target.open("wb") as handle:
            while True:
                block = await file.read(CHUNK_READ)
                if not block:
                    break
                size += len(block)
                if size > MAX_UPLOAD_BYTES:
                    raise ApiError(
                        f"文件超过 {MAX_UPLOAD_BYTES // (1024 * 1024)}MB 上限",
                        code="file_too_large",
                        status=413,
                    )
                handle.write(block)
    except ApiError:
        target.unlink(missing_ok=True)
        store.execute("DELETE FROM documents WHERE id = :id", id=document_id)
        raise
    except OSError as exc:
        target.unlink(missing_ok=True)
        store.execute("DELETE FROM documents WHERE id = :id", id=document_id)
        raise ApiError(f"保存文件失败：{exc}", code="io_error", status=500) from exc

    if size == 0:
        target.unlink(missing_ok=True)
        store.execute("DELETE FROM documents WHERE id = :id", id=document_id)
        raise ApiError("上传的是空文件", code="empty_file", status=400)

    store.execute(
        "UPDATE documents SET size = :size WHERE id = :id", size=size, id=document_id
    )
    job_id = jobs.submit(
        "library.ingest",
        f"解析教材：{row['title']}",
        {"document_id": document_id, "ocr_mode": ocr_mode},
        user_id=uid,
    )
    refreshed = store.one("SELECT * FROM documents WHERE id = :id", id=document_id)
    return {"document": _doc_out(refreshed or row, uid), "job_id": job_id}


class DocumentPatch(BaseModel):
    title: str | None = None
    course_id: int | None = None
    visibility: str | None = None
    ocr_mode: str | None = None


@router.patch("/documents/{document_id}")
async def update_document(
    document_id: int, body: DocumentPatch, user: User = Depends(current_user)
) -> dict:
    row = _load_visible(document_id, user)
    _require_edit(row, user)
    fields: dict[str, Any] = {}
    if body.title is not None:
        fields["title"] = body.title.strip()[:120] or row.get("title") or ""
    if body.course_id is not None:
        course = store.one("SELECT * FROM courses WHERE id = :id", id=body.course_id)
        if course is None:
            raise ApiError("分类不存在", code="not_found", status=404)
        if not store.can_edit(course, _uid(user), _is_admin(user)):
            raise ApiError("不能用别人的分类归档", code="forbidden", status=403)
        fields["course_id"] = body.course_id
    if body.visibility is not None:
        if body.visibility not in VISIBILITIES:
            raise ApiError("visibility 只能是 private 或 shared", code="invalid_visibility")
        fields["visibility"] = body.visibility
    if body.ocr_mode is not None:
        if body.ocr_mode not in OCR_MODES:
            raise ApiError("ocr_mode 只能是 off / auto / force", code="invalid_ocr_mode")
        fields["ocr_mode"] = body.ocr_mode
    if fields:
        assignments = ", ".join(f"{key} = :{key}" for key in fields)
        store.execute(
            f"UPDATE documents SET {assignments}, updated_at = :now WHERE id = :id",
            id=document_id,
            now=store.now_iso(),
            **fields,
        )
    return _doc_out(_load_visible(document_id, user), _uid(user))


@router.post("/documents/{document_id}/reparse")
async def reparse_document(
    document_id: int,
    ocr_mode: str = Form(""),
    user: User = Depends(current_user),
) -> dict:
    """重新解析：用于「先没开 OCR，发现是扫描件」或「换了更好的 OCR 引擎」。"""
    row = _load_visible(document_id, user)
    _require_edit(row, user)
    mode = ocr_mode or row.get("ocr_mode") or "auto"
    if mode not in OCR_MODES:
        raise ApiError("ocr_mode 只能是 off / auto / force", code="invalid_ocr_mode")
    service._set_status(document_id, "queued", 0, "排队重新解析", None)
    job_id = jobs.submit(
        "library.ingest",
        f"重新解析：{row.get('title') or document_id}",
        {"document_id": document_id, "ocr_mode": mode},
        user_id=_uid(user),
    )
    return {"ok": True, "job_id": job_id, "ocr_mode": mode}


@router.delete("/documents/{document_id}")
async def delete_document(document_id: int, user: User = Depends(current_user)) -> dict:
    row = _load_visible(document_id, user)
    _require_edit(row, user)
    retrieval.delete_chunks(document_id)
    store.execute("DELETE FROM documents WHERE id = :id", id=document_id)
    service.remove_document_files(document_id)
    return {"ok": True}


# ---------------------------------------------------------------- 问答


class QaIn(BaseModel):
    question: str
    document_ids: list[int] = Field(default_factory=list)
    thread_id: str | None = None
    limit: int = Field(default=6, ge=1, le=12)


@router.post("/qa")
async def ask(body: QaIn, user: User = Depends(current_user)):
    """SSE：status → delta* → citations → done / error。"""
    uid = _uid(user)
    question = (body.question or "").strip()
    if len(question) < 2:
        raise ApiError("问题太短了", code="empty_question", status=400)

    scope = body.document_ids or None
    if scope is not None:
        for document_id in scope:
            row = store.one("SELECT id, status FROM documents WHERE id = :id", id=document_id)
            if row is None:
                raise ApiError(f"教材 {document_id} 不存在", code="not_found", status=404)
            visible = store.one(
                f"SELECT id FROM documents WHERE id = :id AND {store.scope_sql()}",
                id=document_id,
                uid=uid,
            )
            if visible is None:
                raise ApiError(f"教材 {document_id} 不属于你，无法提问", code="forbidden", status=403)
            if row.get("status") not in ("ready", "partial"):
                raise ApiError(
                    f"《{row.get('title') or document_id}》还没解析完成（状态：{row.get('status')}）",
                    code="document_not_ready",
                    status=409,
                )

    thread_id = qa.ensure_thread(
        uid, body.thread_id, body.document_ids, question[:60] or "教材问答"
    )
    history = _thread_history(thread_id, uid) if body.thread_id else []
    llm = load_llm(uid)

    async def generator():
        answer = ""
        citations: list[dict] = []
        meta: dict[str, Any] = {}
        try:
            async for event, payload in qa.stream_answer(
                uid, question, scope, llm=llm, history=history, limit=body.limit
            ):
                if event == "delta":
                    answer += payload.get("text") or ""
                elif event == "citations":
                    citations = payload.get("citations") or []
                elif event == "done":
                    answer = payload.get("answer") or answer
                    citations = payload.get("citations") or citations
                    meta = payload.get("meta") or {}
                yield sse(event, payload)
        except ApiError as exc:
            yield sse("error", {"code": exc.code, "message": exc.message})
            return
        except Exception as exc:  # noqa: BLE001 - 流内异常必须变成事件，否则前端只看到断流
            log.exception("教材问答流异常")
            yield sse("error", {"code": "internal_error", "message": str(exc)})
            return
        finally:
            if answer.strip():
                try:
                    qa.save_turn(thread_id, uid, question, answer, citations, meta)
                except Exception:  # noqa: BLE001 - 落库失败不该影响已经发出的回答
                    log.exception("问答落库失败")

    return StreamingResponse(generator(), media_type="text/event-stream", headers=SSE_HEADERS)


def _thread_history(thread_id: str, user_id: int) -> list[dict]:
    rows = store.q(
        "SELECT role, content_md FROM qa_messages WHERE thread_id = :thread AND user_id = :uid "
        "ORDER BY created_at DESC LIMIT 8",
        thread=thread_id,
        uid=user_id,
    )
    rows.reverse()
    return [{"role": row["role"], "content": row["content_md"]} for row in rows]


@router.get("/qa/threads")
async def list_threads(user: User = Depends(current_user)) -> list[dict]:
    rows = store.q(
        "SELECT * FROM qa_threads WHERE user_id = :uid ORDER BY updated_at DESC LIMIT 50",
        uid=_uid(user),
    )
    return [
        {
            "id": row["id"],
            "title": row["title"],
            "document_ids": store.json_load(row["document_ids"], []),
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }
        for row in rows
    ]


@router.get("/qa/threads/{thread_id}")
async def get_thread(thread_id: str, user: User = Depends(current_user)) -> dict:
    thread = store.one(
        "SELECT * FROM qa_threads WHERE id = :id AND user_id = :uid", id=thread_id, uid=_uid(user)
    )
    if thread is None:
        raise ApiError("会话不存在", code="not_found", status=404)
    messages = store.q(
        "SELECT * FROM qa_messages WHERE thread_id = :id ORDER BY created_at",
        id=thread_id,
    )
    return {
        "id": thread["id"],
        "title": thread["title"],
        "document_ids": store.json_load(thread["document_ids"], []),
        "messages": [
            {
                "id": row["id"],
                "role": row["role"],
                "content": row["content_md"],
                "citations": store.json_load(row["citations_json"], []),
                "meta": store.json_load(row["meta_json"], {}),
                "created_at": row["created_at"],
            }
            for row in messages
        ],
    }


# ---------------------------------------------------------------- 检索（给前端调试用）


@router.get("/search")
async def search(
    q: str,
    document_ids: str = "",
    limit: int = Query(8, ge=1, le=30),
    user: User = Depends(current_user),
) -> dict:
    if not q.strip():
        raise ApiError("请输入检索词", code="empty_query", status=400)
    scope = [int(item) for item in document_ids.split(",") if item.strip().isdigit()] or None
    result = await retrieval.search(
        _uid(user), q, document_ids=scope, limit=limit, llm=try_load_llm(_uid(user))
    )
    return {
        "mode": result.mode,
        "terms": result.query_terms,
        "degraded": result.degraded,
        "note": result.note,
        "hits": [hit.as_citation(index) for index, hit in enumerate(result.hits, 1)],
    }

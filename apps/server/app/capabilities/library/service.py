"""教材接入管道：落盘 → 解析 → OCR 回填 → 分块 → 建索引 → 写诊断。

异常处理的统一约定
------------------
解析失败分两类，绝不混为一谈：

1. **致命（status=error）**：整份文件没有一个字可用。例如加密 PDF、损坏的 docx、
   扫描件但没有可用 OCR 引擎。此时 `documents.error` 存「人能看懂的原因 + 下一步动作」，
   `chunks` 为空，问答会明确拒绝在它上面提问。
2. **非致命（status=partial）**：文本可用但不完整。例如 300 页里 3 页 OCR 失败、
   整份扫描件识别置信度偏低。文本照样入库、照样可检索，但诊断里标出来，
   `/health` 与前端都会提示「请核对第 N 页」。

所有告警用闭合枚举（`WARN` 表），理由同英语能力的错误码：不闭合的话一年后会攒出
几百个近似标签，既没法聚合也没法给用户稳定的解释。
"""
from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ...config import settings
from ...core.errors import ApiError
from . import ocr, retrieval, store
from .chunking import build_chunks
from .parsers import ParsedBlock, ParsedDoc, detect_kind, parse_document

log = logging.getLogger(__name__)

# 一页文本层少于这么多字，就认为「大概率是图」，需要 OCR
MIN_PAGE_CHARS = 30
# OCR 之后判定「这页到底有没有识别出东西」的门槛。比 MIN_PAGE_CHARS 低得多，
# 因为识别出两三行字就算成功，不能反过来又要求 30 字。
OCR_OK_CHARS = 10
# 分块数少于这个值，多半是解析出了空壳
MIN_OK_CHUNKS = 1
EMBED_BATCH = 32

# 闭合告警表：code → (等级, 给用户看的话)
WARN: dict[str, tuple[str, str]] = {
    "pdf_no_text_layer": ("warn", "这份 PDF 缺少可检索的文本层"),
    "ocr_used": ("info", "已对部分页面做 OCR"),
    "ocr_all": ("info", "整份文件都是 OCR 识别的"),
    "ocr_partial": ("warn", "有页面 OCR 失败，这些页无法检索"),
    "ocr_low_quality": ("warn", "OCR 识别置信度偏低，引用前请核对原文"),
    "ocr_unavailable": ("error", "没有可用的 OCR 引擎，扫描件无法提取文字"),
    "ocr_render_failed": ("warn", "PDF 页面渲染失败，这些页未做 OCR"),
    "text_layer_low": ("warn", "文本层偏少，可能是图文混排"),
    "encrypted": ("error", "文件已加密，无法读取内容"),
    "empty_document": ("error", "没有解析出任何文本"),
    "corrupt_file": ("error", "文件损坏或格式与扩展名不符"),
    "no_chunks": ("warn", "解析成功但切分不出可检索的段落（内容过短）"),
    "embedding_skipped": ("info", "没有配置向量模型，本次只建立关键词索引"),
    "embedding_failed": ("warn", "向量索引建立失败，已退化为关键词检索"),
}


@dataclass
class Diagnostics:
    warnings: list[dict[str, Any]] = field(default_factory=list)
    parse: dict[str, Any] = field(default_factory=dict)
    ocr_info: dict[str, Any] = field(default_factory=dict)

    def add(self, code: str, detail: str = "") -> None:
        level, message = WARN.get(code, ("info", code))
        if any(item["code"] == code for item in self.warnings):
            return
        self.warnings.append({"code": code, "level": level, "message": message, "detail": detail})

    @property
    def worst(self) -> str:
        levels = [item["level"] for item in self.warnings]
        if "error" in levels:
            return "error"
        if "warn" in levels:
            return "warn"
        return "info"

    @property
    def summary(self) -> str:
        """给用户看的一句话：只收 warn / error，带上具体细节。"""
        parts: list[str] = []
        for item in self.warnings:
            if item["level"] == "info":
                continue
            detail = str(item.get("detail") or "").strip()
            parts.append(f"{item['message']}（{detail}）" if detail else item["message"])
        return "；".join(parts)

    def as_dict(self) -> dict[str, Any]:
        return {"warnings": self.warnings, "parse": self.parse, "ocr": self.ocr_info}


class IngestCancelled(Exception):
    pass


def uploads_root() -> Path:
    root = settings.uploads_dir / "library"
    root.mkdir(parents=True, exist_ok=True)
    return root


def save_upload(document_id: int, filename: str, content: bytes) -> tuple[Path, str]:
    """把上传内容落盘，返回 (路径, 格式)。文件名不参与路径，避免穿越与重名。"""
    kind = detect_kind(filename, allow_images=True)
    suffix = Path(filename).suffix.lower()
    target = uploads_root() / f"{document_id}{suffix}"
    target.write_bytes(content)
    return target, kind


# ---------------------------------------------------------------- 单步实现


def _set_status(
    document_id: int,
    status: str,
    progress: int,
    message: str | None = None,
    error: str | None = None,
) -> None:
    store.execute(
        "UPDATE documents SET status = :status, progress = :progress, message = :message, "
        "error = :error, updated_at = :now WHERE id = :id",
        status=status,
        progress=progress,
        message=message,
        error=error,
        now=store.now_iso(),
        id=document_id,
    )


def _thin_pages(doc: ParsedDoc, threshold: int = MIN_PAGE_CHARS) -> list[int]:
    """找出「几乎没有文本」的页。OCR 前后用不同阈值，见 OCR_OK_CHARS 的注释。"""
    lengths: dict[int, int] = {}
    for block in doc.blocks:
        lengths[block.loc_index] = lengths.get(block.loc_index, 0) + len(block.text)
    total = max(doc.page_count, max(lengths, default=0))
    return [number for number in range(1, total + 1) if lengths.get(number, 0) < threshold]


def _merge_ocr(doc: ParsedDoc, pages: list[ocr.OcrPage]) -> tuple[ParsedDoc, list[int]]:
    """把 OCR 结果回填成 page 块；返回 (新文档, 失败页码)。"""
    by_page = {page.page_index: page for page in pages}
    blocks = [block for block in doc.blocks if block.loc_index not in by_page]
    failed: list[int] = []
    for number, page in sorted(by_page.items()):
        text = page.text.strip()
        if not text:
            failed.append(number)
            continue
        blocks.append(ParsedBlock(text=text, loc_label=f"第 {number} 页", loc_index=number))
    blocks.sort(key=lambda block: block.loc_index)
    merged = ParsedDoc(
        blocks=blocks,
        title=doc.title,
        page_count=max(doc.page_count, max(by_page, default=0)),
        kind=doc.kind,
        warning=doc.warning,
    )
    return merged, failed


def _ocr_document(path: Path, doc: ParsedDoc, mode: str, diag: Diagnostics) -> ParsedDoc:
    """按 ocr_mode 决定 OCR 范围，并把结果合并进文档。"""
    if mode == "off":
        if doc.kind == "pdf" and _thin_pages(doc):
            diag.add("pdf_no_text_layer", "已按设置跳过 OCR，这些页将无法检索")
        return doc

    if doc.kind == "image":
        targets = [1]
    elif doc.kind == "pdf":
        if mode == "force":
            targets = list(range(1, max(doc.page_count, 1) + 1))
        else:
            targets = _thin_pages(doc)
    else:
        return doc

    if not targets:
        return doc

    try:
        outcome = ocr.ocr_pdf(path, targets) if doc.kind == "pdf" else ocr.ocr_image_files([path])
    except ApiError as exc:
        diag.add("ocr_unavailable", str(exc))
        diag.ocr_info = {"engine": None, "requested_pages": len(targets), "used": False}
        return doc
    except Exception as exc:  # noqa: BLE001 - 渲染/子进程异常都要能被吸收
        log.warning("OCR 执行异常: %s", exc)
        diag.add("ocr_render_failed", str(exc))
        return doc

    diag.ocr_info = {
        "engine": outcome.engine,
        "used": True,
        "requested_pages": len(targets),
        "returned_pages": len(outcome.pages),
        "avg_confidence": outcome.avg_confidence,
        "low_confidence_pages": outcome.low_confidence_pages,
        "failed_pages": outcome.failed_pages,
    }
    merged, failed = _merge_ocr(doc, outcome.pages)
    covered = max(doc.page_count, len(targets))
    if doc.kind == "image":
        diag.add("ocr_all")
    elif len(targets) >= covered:
        diag.add("ocr_all")
    else:
        diag.add("ocr_used", f"共 {len(targets)} 页")
    if failed or outcome.failed_pages:
        diag.add("ocr_partial", f"失败页码：{sorted(set(failed) | set(outcome.failed_pages))}")
    if outcome.avg_confidence is not None and outcome.avg_confidence < ocr.LOW_CONFIDENCE:
        diag.add("ocr_low_quality", f"平均置信度 {outcome.avg_confidence:.2f}")
    # OCR 之后仍有无文本的页，才算「这份 PDF 文本层缺失」——OCR 成功就不该再报这条
    if doc.kind == "pdf" and _thin_pages(merged, OCR_OK_CHARS):
        diag.add("pdf_no_text_layer", "OCR 后仍有页面没有识别出文本")
    return merged


def _build_embeddings(user_id: int, document_id: int, drafts, diag: Diagnostics) -> None:
    """可选步骤：配置了 embed_model 才建向量索引。"""
    try:
        from ...core.llm import LLMClient, load_provider
        from ...db import engine
        from sqlmodel import Session

        with Session(engine) as session:
            runtime = load_provider(session, user_id=user_id)
        if not runtime.embed_model:
            diag.add("embedding_skipped")
            return
        client = LLMClient(runtime)

        async def run() -> dict[int, list[float]]:
            rows = store.q(
                "SELECT id, text FROM chunks WHERE document_id = :doc ORDER BY ord",
                doc=document_id,
            )
            vectors: dict[int, list[float]] = {}
            for start in range(0, len(rows), EMBED_BATCH):
                batch = rows[start : start + EMBED_BATCH]
                result = await client.embed([row["text"] for row in batch])
                for row, vector in zip(batch, result):
                    vectors[int(row["id"])] = vector
            return vectors

        vectors = asyncio.run(run())
        retrieval.store_embeddings(vectors)
    except ApiError as exc:
        diag.add("embedding_skipped", str(exc))
    except Exception as exc:  # noqa: BLE001 - 向量失败不影响关键词检索
        log.warning("向量索引失败: %s", exc)
        diag.add("embedding_failed", str(exc))


# ---------------------------------------------------------------- 主流程


def ingest_document(
    document_id: int,
    user_id: int,
    ocr_mode: str = "auto",
    ctx: Any = None,
) -> dict[str, Any]:
    """解析并索引一份教材。可被任务中心调用，也可被「重新解析」直接调用。"""
    row = store.one("SELECT * FROM documents WHERE id = :id", id=document_id)
    if row is None:
        raise ApiError("教材不存在", code="not_found", status=404)

    diag = Diagnostics()
    kind = str(row.get("kind") or "")
    path = uploads_root() / f"{document_id}{Path(str(row.get('filename') or '')).suffix.lower()}"
    if not path.is_file():
        _set_status(document_id, "error", 0, "原始文件已丢失", "找不到上传的文件，请重新上传")
        raise ApiError("原始文件已丢失", code="file_missing", status=410)

    def tick(percent: int, message: str) -> None:
        if ctx is not None:
            ctx.progress(percent, message)
        _set_status(document_id, "parsing" if percent < 55 else "indexing", percent, message)

    try:
        tick(5, "读取文件")
        if ocr_mode not in {"off", "auto", "force"}:
            ocr_mode = "auto"
        if ctx is not None and getattr(ctx, "_cancelled", None) is not None:
            if ctx._cancelled.is_set():
                raise IngestCancelled()

        tick(15, "解析文本")
        try:
            parsed = parse_document(path, kind)
        except ApiError as exc:
            code = "encrypted" if "encrypt" in str(exc).lower() or "密码" in str(exc) else "empty_document"
            diag.add(code, str(exc))
            _finish_error(document_id, diag, str(exc))
            raise
        except Exception as exc:  # noqa: BLE001 - 第三方库会抛各种异常
            log.warning("解析失败 %s: %s", document_id, exc)
            diag.add("corrupt_file", str(exc))
            _finish_error(document_id, diag, f"解析失败：{exc}")
            raise ApiError(f"解析失败：{exc}", code="parse_failed", status=422) from exc

        tick(35, "检查是否需要 OCR")
        parsed = _ocr_document(path, parsed, ocr_mode, diag)

        if not parsed.blocks:
            codes = {item["code"] for item in diag.warnings}
            base = diag.summary or "没有解析出任何文本"
            if "ocr_unavailable" in codes:
                base += "。扫描件需要 OCR 引擎：macOS 装 Xcode Command Line Tools 即可。"
            elif ocr_mode == "off" and parsed.kind in ("pdf", "image"):
                base += "。这是扫描件，可以开启 OCR 后重新解析。"
            _finish_error(document_id, diag, base)
            raise ApiError(base, code="empty_document", status=422)

        tick(65, "切分段落")
        drafts = build_chunks(parsed)

        tick(78, "建立关键词索引")
        chunk_count = retrieval.replace_chunks(document_id, user_id, drafts)

        tick(88, "建立向量索引")
        if chunk_count:
            _build_embeddings(user_id, document_id, drafts, diag)

        if chunk_count < MIN_OK_CHUNKS:
            diag.add("no_chunks")
        if parsed.warning and not diag.ocr_info.get("used"):
            diag.add("text_layer_low", parsed.warning)

        status = "partial" if diag.worst == "warn" else "ready"
        if diag.worst == "error":
            status = "partial" if chunk_count else "error"

        ocr_info = diag.ocr_info or {}
        ocr_page_count = int(ocr_info.get("returned_pages") or ocr_info.get("requested_pages") or 0)
        diag.parse = {
            "kind": parsed.kind,
            "blocks": len(parsed.blocks),
            "pages": parsed.page_count,
            "chars": parsed.char_count,
            "chunks": chunk_count,
            "ocr_mode": ocr_mode,
        }
        store.execute(
            "UPDATE documents SET status = :status, progress = 100, message = :message, "
            "error = NULL, page_count = :pages, char_count = :chars, chunk_count = :chunks, "
            "ocr_mode = :ocr_mode, ocr_engine = :engine, ocr_pages = :ocr_pages, "
            "ocr_confidence = :confidence, parse_warning = :warning, meta_json = :meta, "
            "updated_at = :now WHERE id = :id",
            status=status,
            message=f"{chunk_count} 段可检索，共 {parsed.char_count} 字",
            pages=parsed.page_count,
            chars=parsed.char_count,
            chunks=chunk_count,
            ocr_mode=ocr_mode,
            engine=ocr_info.get("engine"),
            ocr_pages=ocr_page_count,
            confidence=ocr_info.get("avg_confidence"),
            warning=diag.summary or None,
            meta=json.dumps(diag.as_dict(), ensure_ascii=False),
            now=store.now_iso(),
            id=document_id,
        )
        return {
            "document_id": document_id,
            "status": status,
            "chunks": chunk_count,
            "chars": parsed.char_count,
            "pages": parsed.page_count,
            "warnings": [item["code"] for item in diag.warnings],
        }
    except IngestCancelled:
        _set_status(document_id, "error", 0, "已取消", "解析被取消")
        raise


def _finish_error(document_id: int, diag: Diagnostics, message: str) -> None:
    """解析彻底失败：清掉旧索引，避免「状态是 error 但还能搜到旧内容」的自相矛盾。"""
    diag.parse = diag.parse or {}
    retrieval.delete_chunks(document_id)
    store.execute(
        "UPDATE documents SET status = 'error', progress = 100, message = :message, "
        "error = :message, chunk_count = 0, parse_warning = :warning, meta_json = :meta, "
        "updated_at = :now WHERE id = :id",
        message=message[:300],
        warning=diag.summary or None,
        meta=json.dumps(diag.as_dict(), ensure_ascii=False),
        now=store.now_iso(),
        id=document_id,
    )


def remove_document_files(document_id: int) -> None:
    for candidate in uploads_root().glob(f"{document_id}.*"):
        try:
            candidate.unlink()
        except OSError:
            log.warning("删除上传文件失败: %s", candidate)


def mark_failed(document_id: int, message: str) -> None:
    """兜底：任何没被预期到的异常都要落到文档状态上。

    否则任务线程挂了、文档还停在 `queued`，前端会永远转圈。
    """
    try:
        store.execute(
            "UPDATE documents SET status = 'error', progress = 100, message = :message, "
            "error = :message, updated_at = :now WHERE id = :id",
            message=message[:300],
            now=store.now_iso(),
            id=document_id,
        )
    except Exception:  # noqa: BLE001 - 兜底本身不能再抛
        log.exception("写入失败状态时出错: document=%s", document_id)

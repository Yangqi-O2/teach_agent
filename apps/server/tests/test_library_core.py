"""教材库核心逻辑：分块、切词、解析回验、OCR 降级、引用校验。"""
from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from docx import Document as DocxDocument

from app.capabilities.library import ocr, qa, retrieval
from app.capabilities.library.chunking import _sentences, build_chunks
from app.capabilities.library.parsers import ParsedBlock, ParsedDoc, parse_document
from app.core.errors import ApiError


# ---------------------------------------------------------------- 分块


def test_sentences_split_chinese():
    assert _sentences("第一句。第二句！第三句?") == ["第一句。", "第二句！", "第三句?"]


def test_sentences_do_not_split_decimals_or_abbreviations():
    assert _sentences("圆周率是 3.14 左右。下一句。") == ["圆周率是 3.14 左右。", "下一句。"]
    # A.B.C 中间的点不是句末
    assert len(_sentences("缩写 A.B.C 出现在句中")) == 1


def test_short_pages_are_kept():
    """曾经的 bug：不足 30 字的页会被整段丢掉，扫描件短页直接消失。"""
    doc = ParsedDoc(
        blocks=[
            ParsedBlock(text="第一章 应力状态与应变", loc_label="第 1 页", loc_index=1),
            ParsedBlock(text="应力张量是一个二阶对称张量", loc_label="第 2 页", loc_index=2),
        ],
        kind="pdf",
        page_count=2,
    )
    chunks = build_chunks(doc)
    assert len(chunks) == 2
    assert [chunk.loc_index for chunk in chunks] == [1, 2]


def test_pure_page_number_is_noise():
    doc = ParsedDoc(
        blocks=[ParsedBlock(text="- 12 -", loc_label="第 1 页", loc_index=1)],
        kind="pdf",
        page_count=1,
    )
    assert build_chunks(doc) == []


def test_pdf_pages_never_merge_across_pages():
    """跨页合并会让引用指向错误的页码。"""
    doc = ParsedDoc(
        blocks=[
            ParsedBlock(text="甲" * 60, loc_label="第 1 页", loc_index=1),
            ParsedBlock(text="乙" * 60, loc_label="第 2 页", loc_index=2),
        ],
        kind="pdf",
        page_count=2,
    )
    chunks = build_chunks(doc)
    assert len(chunks) == 2
    assert all("乙" not in chunk.text for chunk in chunks if chunk.loc_index == 1)


# ---------------------------------------------------------------- 切词


def test_tokenize_drops_stopwords_and_short_tokens():
    terms = retrieval.tokenize("请问这本书里的应力张量是什么")
    assert "应力" in terms
    assert "张量" in terms
    assert "请问" not in terms
    assert "的" not in terms


def test_segments_of_keeps_chinese_tokens_apart():
    assert " " in retrieval.segments_of("应力张量")


# ---------------------------------------------------------------- 解析


def test_parse_txt_gives_paragraph_positions(workdir: Path):
    path = workdir / "a.txt"
    path.write_text("第一段内容，足够长以通过噪声过滤。\n\n第二段内容，同样足够长一点。", encoding="utf-8")
    doc = parse_document(path, "txt")
    assert len(doc.blocks) == 2
    assert doc.blocks[0].loc_label == "第 1 段"


def test_parse_docx_keeps_heading_path(workdir: Path):
    path = workdir / "b.docx"
    document = DocxDocument()
    document.add_heading("第二章 本构关系", level=1)
    document.add_paragraph("各向同性线弹性体需要两个独立弹性常数。")
    document.save(str(path))

    parsed = parse_document(path, "docx")
    assert parsed.blocks
    assert parsed.blocks[0].heading_path == ["第二章 本构关系"]
    assert "弹性常数" in parsed.blocks[0].text


def test_unsupported_extension_is_rejected(workdir: Path):
    with pytest.raises(ApiError) as exc:
        parse_document(workdir / "c.doc", "doc")
    assert exc.value.code == "unsupported_format"


def test_image_is_left_for_ocr(workdir: Path):
    """图片没有文本层，不应在解析阶段被判死，而应交给 OCR。"""
    from PIL import Image

    path = workdir / "scan.png"
    Image.new("RGB", (40, 40), "white").save(path)
    parsed = parse_document(path, "image")
    assert parsed.blocks == []
    assert "OCR" in parsed.warning


# ---------------------------------------------------------------- OCR


def test_ocr_probe_has_stable_shape():
    info = ocr.probe()
    for key in ("available", "pdf_ready", "preferred", "vision", "tesseract", "hint"):
        assert key in info
    assert isinstance(info["vision"]["supported"], bool)


def test_ocr_unavailable_raises_structured_error(monkeypatch):
    monkeypatch.setattr(ocr, "probe", lambda: {"available": False, "preferred": None, "hint": "没有引擎"})
    with pytest.raises(ApiError) as exc:
        ocr.ocr_pdf(Path("/tmp/whatever.pdf"), [1])
    assert exc.value.code == "ocr_unavailable"


def test_ocr_outcome_confidence_stats():
    outcome = ocr.OcrOutcome(
        pages=[
            ocr.OcrPage(1, "清晰的一页", 0.92),
            ocr.OcrPage(2, "糊掉的一页", 0.31),
        ],
        engine="vision",
    )
    assert outcome.avg_confidence == pytest.approx(0.615)
    assert outcome.low_confidence_pages == [2]


# ---------------------------------------------------------------- 引用校验


def _hit(chunk_id: int, text: str = "内容") -> retrieval.Hit:
    return retrieval.Hit(
        chunk_id=chunk_id,
        document_id=1,
        document_title="教材",
        ord=chunk_id,
        text=text,
        heading_path="",
        loc_label=f"第 {chunk_id} 页",
        loc_index=chunk_id,
    )


def test_citations_over_range_are_dropped():
    hits = [_hit(1), _hit(2)]
    citations, unused, bad = qa.collect_citations("结论一 [1]，结论二 [7]，重复 [1]", hits)
    assert [item["index"] for item in citations] == [1]
    assert bad == [7]
    assert [item["index"] for item in unused] == [2]


def test_no_citation_marks_not_ok():
    hits = [_hit(1)]
    citations, _, _ = qa.collect_citations("教材里没有提到这一点。", hits)
    assert citations == []


# ---------------------------------------------------------------- 检索（RRF）


def test_rrf_rewards_items_in_both_lists():
    a = [_hit(1), _hit(2)]
    b = [_hit(2), _hit(3)]
    fused = retrieval._rrf([a, b], limit=3)
    assert fused[0].chunk_id == 2        # 两路都出现，排第一
    assert {hit.chunk_id for hit in fused} == {1, 2, 3}


def test_build_context_numbers_sources():
    hits = [_hit(1, "甲" * 50), _hit(2, "乙" * 50)]
    context, used = retrieval.build_context(hits)
    assert context.startswith("[1] 《教材》第 1 页")
    assert "[2]" in context
    assert len(used) == 2


def test_build_context_truncates_without_dropping_first():
    hits = [_hit(index, "字" * 400) for index in range(1, 6)]
    context, used = retrieval.build_context(hits, max_chars=500)
    assert used, "至少保留第一段"
    assert len(used) < len(hits)
    assert context.startswith("[1]")


def test_search_without_terms_returns_empty():
    result = asyncio.run(retrieval.search(1, "的", document_ids=[1], limit=3))
    assert result.mode == "empty"

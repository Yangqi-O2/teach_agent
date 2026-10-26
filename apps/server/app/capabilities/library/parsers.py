"""教材文件解析：docx / pptx / pdf / epub / md / txt / html / url / image。

统一输出 ParsedBlock：文本 + 标题路径 + 位置标签（第 N 页 / 第 N 张 / 章节）。
位置信息是「引用可回溯」的基础，所有格式都要尽量给出。

图片（png/jpg/webp）不在这里解析出文本——它们只能靠 OCR，由 ingestion 层接管。
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

from ...core.errors import ApiError

log = logging.getLogger(__name__)

SUPPORTED_EXTENSIONS = {
    ".docx": "docx",
    ".pptx": "pptx",
    ".pdf": "pdf",
    ".epub": "epub",
    ".md": "md",
    ".markdown": "md",
    ".txt": "txt",
    ".html": "html",
    ".htm": "html",
}

# 图片只能靠 OCR。**故意不并入 SUPPORTED_EXTENSIONS**：那是各能力共用的「可解析文本格式」表，
# english 的资料导入依赖它的语义（遇到 png 应当明确拒绝），所以需要 OCR 的调用方显式开启。
IMAGE_EXTENSIONS = {
    ".png": "image",
    ".jpg": "image",
    ".jpeg": "image",
    ".webp": "image",
    ".bmp": "image",
}

# 教材库对外声称支持的格式（健康检查用）
LIBRARY_EXTENSIONS = {**SUPPORTED_EXTENSIONS, **IMAGE_EXTENSIONS}

# 只能靠 OCR 的格式
OCR_ONLY_KINDS = {"image"}
# 解析出空文本时不能直接判死，要留给 OCR 层抢救的格式
OCR_RESCUE_KINDS = {"pdf", "image"}


@dataclass
class ParsedBlock:
    text: str
    heading_path: list[str] = field(default_factory=list)
    loc_label: str = ""
    loc_index: int = 0


@dataclass
class ParsedDoc:
    blocks: list[ParsedBlock]
    title: str = ""
    page_count: int = 0
    kind: str = ""
    warning: str = ""

    @property
    def char_count(self) -> int:
        return sum(len(block.text) for block in self.blocks)


def detect_kind(filename: str, allow_images: bool = False) -> str:
    suffix = Path(filename).suffix.lower()
    kind = SUPPORTED_EXTENSIONS.get(suffix)
    if kind is None and allow_images:
        kind = IMAGE_EXTENSIONS.get(suffix)
    if not kind:
        extra = " / 图片(.png/.jpg/.webp)" if allow_images else ""
        raise ApiError(
            f"暂不支持 {suffix or '该'} 格式。支持：Word(.docx) / PPT(.pptx) / PDF / EPUB / "
            f"Markdown / TXT / HTML{extra}",
            code="unsupported_format",
            status=415,
        )
    return kind


# ---------------------------------------------------------------- DOCX


def parse_docx(path: Path) -> ParsedDoc:
    from docx import Document
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    doc = Document(str(path))
    heads: list[str] = []
    blocks: list[ParsedBlock] = []
    for element in doc.element.body.iterchildren():
        if element.tag.endswith("}p"):
            paragraph = Paragraph(element, doc)
            text = paragraph.text.strip()
            if not text:
                continue
            style = (paragraph.style.name or "").lower()
            match = re.match(r"heading (\d)", style)
            if match:
                level = int(match.group(1))
                heads = heads[: level - 1] + [text]
                continue
            blocks.append(ParsedBlock(text=text, heading_path=list(heads)))
        elif element.tag.endswith("}tbl"):
            rows = []
            for row in Table(element, doc).rows:
                cells = [cell.text.strip().replace("\n", " ") for cell in row.cells]
                rows.append(" | ".join(cells))
            table_text = "\n".join(r for r in rows if r.strip(" |"))
            if table_text:
                blocks.append(ParsedBlock(text=table_text, heading_path=list(heads)))
    return ParsedDoc(blocks=blocks, title=Path(path).stem, kind="docx")


# ---------------------------------------------------------------- PPTX


def parse_pptx(path: Path) -> ParsedDoc:
    from pptx import Presentation

    presentation = Presentation(str(path))
    blocks: list[ParsedBlock] = []
    for index, slide in enumerate(presentation.slides, 1):
        texts = [
            shape.text_frame.text.strip()
            for shape in slide.shapes
            if getattr(shape, "has_text_frame", False) and shape.text_frame.text.strip()
        ]
        notes = ""
        if slide.has_notes_slide:
            notes = (slide.notes_slide.notes_text_frame.text or "").strip()
        body = "\n".join(texts)
        if notes:
            body = f"{body}\n\n[备注] {notes}" if body else f"[备注] {notes}"
        if body:
            blocks.append(
                ParsedBlock(
                    text=body,
                    heading_path=[texts[0][:40]] if texts else [],
                    loc_label=f"第 {index} 张",
                    loc_index=index,
                )
            )
    return ParsedDoc(
        blocks=blocks,
        title=Path(path).stem,
        page_count=len(presentation.slides),
        kind="pptx",
    )


# ---------------------------------------------------------------- PDF


def _pdf_pages_pypdf(path: Path) -> list[str]:
    from pypdf import PdfReader

    reader = PdfReader(str(path))
    return [((page.extract_text() or "").strip()) for page in reader.pages]


def _pdf_pages_plumber(path: Path) -> list[str]:
    import pdfplumber

    pages: list[str] = []
    with pdfplumber.open(str(path)) as pdf:
        for page in pdf.pages:
            pages.append((page.extract_text() or "").strip())
    return pages


def parse_pdf(path: Path) -> ParsedDoc:
    pages: list[str] = []
    warning = ""
    try:
        pages = _pdf_pages_pypdf(path)
    except Exception as exc:  # noqa: BLE001
        log.warning("pypdf 解析失败，改用 pdfplumber: %s", exc)
        pages = []
    if not pages or sum(len(page) for page in pages) < max(40, 20 * len(pages)):
        try:
            pages = _pdf_pages_plumber(path)
        except Exception as exc:  # noqa: BLE001
            log.warning("pdfplumber 解析失败: %s", exc)
    total_chars = sum(len(page) for page in pages)
    if total_chars < max(50, 15 * max(1, len(pages))):
        warning = "这份 PDF 几乎没有文本层，可能是扫描件，需要 OCR 才能检索"
    blocks = [
        ParsedBlock(text=page, loc_label=f"第 {index} 页", loc_index=index)
        for index, page in enumerate(pages, 1)
        if page
    ]
    return ParsedDoc(
        blocks=blocks,
        title=Path(path).stem,
        page_count=len(pages),
        kind="pdf",
        warning=warning,
    )


# ---------------------------------------------------------------- EPUB


def parse_epub(path: Path) -> ParsedDoc:
    from bs4 import BeautifulSoup
    from ebooklib import ITEM_DOCUMENT, epub

    book = epub.read_epub(str(path))
    blocks: list[ParsedBlock] = []
    index = 0
    for item_id, _ in book.spine:
        item = book.get_item_with_id(item_id)
        if item is None or item.get_type() != ITEM_DOCUMENT:
            continue
        if item.get_name() in ("nav.xhtml", "toc.xhtml"):
            continue
        soup = BeautifulSoup(item.get_content(), "xml")
        heading = ""
        heading_tag = soup.find(["h1", "h2", "h3"])
        if heading_tag is not None:
            heading = heading_tag.get_text(" ", strip=True)
        title = heading or (getattr(item, "title", "") or "").strip()
        paragraphs = [
            node.get_text(" ", strip=True)
            for node in soup.find_all(["p", "li", "h1", "h2", "h3", "h4"])
        ]
        text = ""
        text = "\n".join(part for part in paragraphs if part)
        if not text:
            text = soup.get_text(" ", strip=True)
        if text.strip():
            index += 1
            blocks.append(
                ParsedBlock(
                    text=text.strip(),
                    heading_path=[title] if title else [],
                    loc_label=f"第 {index} 章" + (f" {title}" if title else ""),
                    loc_index=index,
                )
            )
    return ParsedDoc(blocks=blocks, title=Path(path).stem, page_count=index, kind="epub")


# ---------------------------------------------------------------- Markdown / 纯文本


def parse_markdown(path: Path) -> ParsedDoc:
    raw = path.read_text(encoding="utf-8", errors="ignore")
    heads: list[str] = []
    blocks: list[ParsedBlock] = []
    buffer: list[str] = []
    for line in raw.splitlines():
        match = re.match(r"^(#{1,4})\s+(.*)$", line)
        if match:
            if buffer:
                blocks.append(ParsedBlock(text="\n".join(buffer).strip(), heading_path=list(heads)))
                buffer = []
            level = len(match.group(1))
            heads = heads[: level - 1] + [match.group(2).strip()]
            continue
        buffer.append(line)
    if buffer:
        blocks.append(ParsedBlock(text="\n".join(buffer).strip(), heading_path=list(heads)))
    blocks = [block for block in blocks if block.text]
    return ParsedDoc(blocks=blocks, title=Path(path).stem, kind="md")


def parse_txt(path: Path) -> ParsedDoc:
    raw = path.read_text(encoding="utf-8", errors="ignore")
    blocks = [
        ParsedBlock(text=chunk.strip(), loc_label=f"第 {index} 段", loc_index=index)
        for index, chunk in enumerate(re.split(r"\n\s*\n", raw), 1)
        if chunk.strip()
    ]
    return ParsedDoc(blocks=blocks, title=Path(path).stem, kind="txt")


# ---------------------------------------------------------------- HTML / URL


def _blocks_from_html(html: str) -> tuple[list[ParsedBlock], str]:
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "lxml")
    for tag in soup(["script", "style", "nav", "footer", "header"]):
        tag.decompose()
    title = ""
    if soup.title and soup.title.string:
        title = soup.title.string.strip()
    heading = soup.find(["h1", "h2"])
    if heading is not None:
        title = title or heading.get_text(" ", strip=True)
    heads: list[str] = []
    blocks: list[ParsedBlock] = []
    counter = 0
    for node in soup.find_all(["h1", "h2", "h3", "h4", "p", "li"]):
        text = node.get_text(" ", strip=True)
        if not text:
            continue
        if node.name in ("h1", "h2", "h3", "h4"):
            level = int(node.name[1])
            heads = heads[: level - 1] + [text]
            continue
        counter += 1
        blocks.append(
            ParsedBlock(text=text, heading_path=list(heads), loc_label=f"第 {counter} 段", loc_index=counter)
        )
    if not blocks:
        pass
    return blocks, title


def parse_html_file(path: Path) -> ParsedDoc:
    html = path.read_text(encoding="utf-8", errors="ignore")
    blocks, title = _blocks_from_html(html)
    return ParsedDoc(blocks=blocks, title=title or Path(path).stem, kind="html")


def parse_url(url: str) -> ParsedDoc:
    import httpx

    try:
        response = httpx.get(url, timeout=20, follow_redirects=True, headers={"User-Agent": "Mozilla/5.0 Tianjianhu/0.2"})
        response.raise_for_status()
    except Exception as exc:  # noqa: BLE001
        raise ApiError(f"抓取网页失败：{exc}", code="fetch_failed", status=502) from exc
    html = response.text
    blocks, title = _blocks_from_html(html)
    if not blocks:
        raise ApiError("这个网页没有可读正文", code="empty_page", status=422)
    return ParsedDoc(blocks=blocks, title=title or url, kind="url")


# ---------------------------------------------------------------- 统一入口


def parse_image(path: Path) -> ParsedDoc:
    """图片本身没有文本层，返回空文档交给 OCR 层处理。"""
    return ParsedDoc(
        blocks=[],
        title=Path(path).stem,
        page_count=1,
        kind="image",
        warning="图片需要 OCR 才能提取文字",
    )


def parse_document(path: Path, kind: str) -> ParsedDoc:
    """按格式分发解析；返回带位置信息的 ParsedDoc。"""
    handlers = {
        "docx": parse_docx,
        "pptx": parse_pptx,
        "pdf": parse_pdf,
        "epub": parse_epub,
        "md": parse_markdown,
        "txt": parse_txt,
        "html": parse_html_file,
        "image": parse_image,
    }
    handler = handlers.get(kind)
    if handler is None:
        raise ApiError(f"不支持的文件类型：{kind}", code="unsupported_format", status=415)
    result = handler(path)
    result.kind = kind
    # PDF 与图片可能整份都是扫描件：此处不判死，交给 ingestion 层决定是否 OCR
    if kind not in OCR_RESCUE_KINDS and not result.blocks:
        raise ApiError(
            "没有解析出任何文本（可能是空文件、加密文件，或格式与扩展名不符）",
            code="empty_document",
            status=422,
        )
    return result

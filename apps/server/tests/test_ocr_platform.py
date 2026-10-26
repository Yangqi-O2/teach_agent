"""OCR 跨平台后端：栅格化选择与 PDF 渲染。

这些用例锁住「非 macOS 也能 OCR」的关键一环——PDF 栅格化。
渲染本身与操作系统无关，所以在 macOS 上跑也等价于验证 Linux/Windows 那条路径。
"""
from __future__ import annotations

import sys

import pytest

from app.capabilities.library import ocr


def _make_pdf(path, pages: int = 1):
    from pypdf import PdfWriter

    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=595, height=842)
    with open(path, "wb") as handle:
        writer.write(handle)
    return path


def test_rasterizer_is_available():
    backend = ocr._rasterizer()
    assert backend is not None, "requirements.txt 里应当已包含 pypdfium2"
    name, _module = backend
    assert name in ("pypdfium2", "pymupdf")


def test_render_pdf_pages_writes_png(workdir):
    pdf = _make_pdf(workdir / "sample.pdf", pages=2)
    rendered = ocr.render_pdf_pages(pdf, [1, 2], workdir)
    assert [number for number, _ in rendered] == [1, 2]
    for _number, target in rendered:
        assert target.exists() and target.stat().st_size > 1000
        # PNG magic number，确认写出来的是真图片而不是空文件
        assert target.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"


def test_render_skips_out_of_range_pages(workdir):
    pdf = _make_pdf(workdir / "one.pdf", pages=1)
    assert ocr.render_pdf_pages(pdf, [1, 9], workdir) == [(1, workdir / "page-0001.png")]


def test_probe_reports_platform_and_hint():
    info = ocr.probe()
    assert info["platform"] == sys.platform
    assert info["rasterizer"] in {"vision-pdfkit", "pypdfium2", "pymupdf", None}
    # 要么有可用引擎，要么给出可执行的安装提示——不能两者都没有
    assert info["available"] or info["hint"]


def test_tesseract_override_env(monkeypatch, tmp_path):
    """Windows 上 tesseract 常不在 PATH，必须能用环境变量指过去。"""
    fake = tmp_path / "tesseract.exe"
    fake.write_text("", encoding="utf-8")
    monkeypatch.setenv("TJH_TESSERACT_CMD", str(fake))
    assert ocr._tesseract_path() == str(fake)


def test_tesseract_override_ignored_when_missing(monkeypatch):
    monkeypatch.setenv("TJH_TESSERACT_CMD", "/nonexistent/tesseract")
    # 指错了不应该抛异常，只是回到 PATH 查找（找不到返回 None）
    assert ocr._tesseract_path() in (None, ocr.shutil.which("tesseract"))


def test_install_hint_matches_platform(monkeypatch):
    monkeypatch.setattr(ocr.sys, "platform", "linux")
    assert "apt" in ocr._install_hint()
    monkeypatch.setattr(ocr.sys, "platform", "win32")
    assert "TJH_TESSERACT_CMD" in ocr._install_hint()
    monkeypatch.setattr(ocr.sys, "platform", "darwin")
    assert "Xcode" in ocr._install_hint()

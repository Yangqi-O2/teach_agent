"""扫描件 OCR：优先 macOS Vision，其次 tesseract，都没有就明确报错。

平台矩阵（三端都能跑，只是后端不同）
------------------------------------
| 平台 | 识别 | PDF 栅格化 | 额外依赖 |
|---|---|---|---|
| macOS | Vision（内嵌 Swift + swiftc） | PDFKit（同一个二进制） | Xcode Command Line Tools |
| Linux | tesseract + chi_sim | pypdfium2 | apt/dnf 装 tesseract |
| Windows | tesseract + chi_sim | pypdfium2 | 安装包 + TJH_TESSERACT_CMD |

macOS 走 Vision 是最省事的：识别质量好，且不需要装任何 Python 包。但如果机器上没有
swiftc，会**自动退回 tesseract**（前端显示实际用的是哪个引擎），不会因为缺工具就整条链路不可用。

为什么自己管一个 Swift 二进制
------------------------------
`swift script.swift` 是解释执行，首次编译 40 秒以上；用 `swiftc -O` 预编译只要几秒，
之后按页计费。所以把 Swift 源码内嵌成字符串，首次使用时编译到 `data/cache/ocr/` 并缓存复用。

同一个二进制兼做两件事：
- `ocr_tool pdf <file> <pages>` —— PDFKit 栅格化 + 识别，**不需要 PyMuPDF**；
- `ocr_tool image <file...>`    —— 直接识别图片。

质量与降级
----------
- 每页返回「文本 + 平均置信度」；置信度过低会进 warnings，但**文本仍然保留**——
  低质量文本能检索到，总比整页丢失好。
- 没有任何可用引擎时抛 `ocr_unavailable`，由上层把文档标成 `partial` 或 `error`，
  并按当前平台给出可照抄的安装命令。
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import sys
import tempfile
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

from ...config import settings
from ...core.errors import ApiError

log = logging.getLogger(__name__)

# 低于这个置信度就认为「识别质量可疑」，需要提示用户人工核对
LOW_CONFIDENCE = 0.55
# 每页最多渲染到多少像素宽（避免超大图纸吃穿内存）
MAX_RENDER_PX = 2600
DEFAULT_DPI = 200
PAGE_TIMEOUT = 90

_COMPILE_LOCK = threading.Lock()


@dataclass
class OcrPage:
    page_index: int            # 1-based
    text: str
    confidence: float | None   # 0~1；拿不到时为 None
    engine: str = ""
    error: str = ""


@dataclass
class OcrOutcome:
    pages: list[OcrPage] = field(default_factory=list)
    engine: str = ""
    failed_pages: list[int] = field(default_factory=list)

    @property
    def avg_confidence(self) -> float | None:
        values = [page.confidence for page in self.pages if page.confidence is not None]
        return round(sum(values) / len(values), 4) if values else None

    @property
    def low_confidence_pages(self) -> list[int]:
        return [
            page.page_index
            for page in self.pages
            if page.confidence is not None and page.confidence < LOW_CONFIDENCE
        ]

    @property
    def text(self) -> str:
        return "\n".join(page.text for page in self.pages if page.text.strip())


# ---------------------------------------------------------------- Swift 源码

_TOOL_SWIFT = r"""
import Foundation
import Vision
import AppKit
import PDFKit
import CoreGraphics

// ocr_tool image <图片路径>...
// ocr_tool pdf   <PDF 路径> <页码逗号分隔|all>
// 每行输出一个 JSON：{"page": n, "text": "...", "confidence": 0.93}

func recognize(_ cgImage: CGImage) -> (String, Double) {
    let request = VNRecognizeTextRequest()
    request.recognitionLevel = .accurate
    request.usesLanguageCorrection = true
    request.recognitionLanguages = ["zh-Hans", "en-US"]
    let handler = VNImageRequestHandler(cgImage: cgImage, options: [:])
    do { try handler.perform([request]) } catch { return ("", 0.0) }
    guard let observations = request.results else { return ("", 0.0) }
    var lines: [String] = []
    var total: Float = 0
    var count: Float = 0
    for observation in observations {
        guard let candidate = observation.topCandidates(1).first else { continue }
        lines.append(candidate.string)
        total += candidate.confidence
        count += 1
    }
    return (lines.joined(separator: "\n"), count > 0 ? Double(total / count) : 0.0)
}

func imageFromFile(_ path: String) -> CGImage? {
    guard let image = NSImage(contentsOfFile: path),
          let tiff = image.tiffRepresentation,
          let bitmap = NSBitmapImageRep(data: tiff) else { return nil }
    return bitmap.cgImage
}

func renderPage(_ page: PDFPage, scale: CGFloat) -> CGImage? {
    let bounds = page.bounds(for: .mediaBox)
    let width = max(1, Int(bounds.width * scale))
    let height = max(1, Int(bounds.height * scale))
    guard let context = CGContext(
        data: nil, width: width, height: height,
        bitsPerComponent: 8, bytesPerRow: 0,
        space: CGColorSpaceCreateDeviceRGB(),
        bitmapInfo: CGImageAlphaInfo.noneSkipLast.rawValue
    ) else { return nil }
    context.setFillColor(CGColor(red: 1, green: 1, blue: 1, alpha: 1))
    context.fill(CGRect(x: 0, y: 0, width: width, height: height))
    context.scaleBy(x: scale, y: scale)
    page.draw(with: .mediaBox, to: context)
    return context.makeImage()
}

func emit(page: Int, text: String, confidence: Double) {
    let payload: [String: Any] = ["page": page, "text": text, "confidence": confidence]
    if let data = try? JSONSerialization.data(withJSONObject: payload, options: []),
       let line = String(data: data, encoding: .utf8) {
        print(line)
    }
}

let args = Array(CommandLine.arguments.dropFirst())
guard let mode = args.first else { exit(2) }

if mode == "image" {
    for (offset, path) in args.dropFirst().enumerated() {
        guard let cgImage = imageFromFile(path) else {
            emit(page: offset + 1, text: "", confidence: 0)
            continue
        }
        let (text, confidence) = recognize(cgImage)
        emit(page: offset + 1, text: text, confidence: confidence)
    }
} else if mode == "pdf" {
    guard args.count >= 3, let document = PDFDocument(url: URL(fileURLWithPath: args[1])) else {
        exit(3)
    }
    let total = document.pageCount
    var targets: [Int] = []
    if args[2] == "all" {
        targets = Array(1...max(1, total))
    } else {
        targets = args[2].split(separator: ",").compactMap { Int($0.trimmingCharacters(in: .whitespaces)) }
    }
    for number in targets {
        guard number >= 1, number <= total, let page = document.page(at: number - 1) else { continue }
        let bounds = page.bounds(for: .mediaBox)
        var scale: CGFloat = 200.0 / 72.0
        if bounds.width > 0 { scale = min(scale, 2600.0 / bounds.width) }
        guard let cgImage = renderPage(page, scale: scale) else {
            emit(page: number, text: "", confidence: 0)
            continue
        }
        let (text, confidence) = recognize(cgImage)
        emit(page: number, text: text, confidence: confidence)
    }
} else {
    exit(2)
}
"""


def _tool_path() -> Path:
    return settings.cache_dir / "ocr" / "ocr_tool"


def _has_swiftc() -> bool:
    return shutil.which("swiftc") is not None


def vision_supported() -> bool:
    """Vision 只在 macOS 上存在；Linux 上就算有 swift 也没有这个框架。"""
    return sys.platform == "darwin"


def ensure_tool_binary() -> Path | None:
    """编译并缓存 Swift OCR 工具；不可用时返回 None。"""
    if not (vision_supported() and _has_swiftc()):
        return None
    target = _tool_path()
    if target.is_file() and os.access(target, os.X_OK):
        return target
    with _COMPILE_LOCK:
        if target.is_file() and os.access(target, os.X_OK):
            return target
        target.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="tjh-ocr-") as tmp:
            source = Path(tmp) / "ocr_tool.swift"
            source.write_text(_TOOL_SWIFT, encoding="utf-8")
            compiled = Path(tmp) / "ocr_tool"
            try:
                proc = subprocess.run(
                    [shutil.which("swiftc") or "swiftc", "-O", "-o", str(compiled), str(source)],
                    capture_output=True,
                    timeout=240,
                )
            except (subprocess.SubprocessError, OSError) as exc:
                log.warning("OCR 工具编译失败: %s", exc)
                return None
            if proc.returncode != 0 or not compiled.is_file():
                log.warning("OCR 工具编译失败: %s", proc.stderr.decode("utf-8", "ignore")[:400])
                return None
            shutil.move(str(compiled), str(target))
            target.chmod(0o755)
    log.info("OCR 工具（Vision）已编译并缓存：%s", target)
    return target


def _tesseract_path() -> str | None:
    """tesseract 可执行文件位置。

    Windows 安装包默认不进 PATH，所以允许用 `TJH_TESSERACT_CMD` 显式指定
    （指向 tesseract.exe 即可），免得让用户去改系统环境变量。
    """
    for key in ("TJH_TESSERACT_CMD", "TESSERACT_CMD"):
        override = os.environ.get(key)
        if not override:
            continue
        candidate = Path(override).expanduser()
        if candidate.is_file():
            return str(candidate)
        found = shutil.which(override)
        if found:
            return found
    return shutil.which("tesseract") or shutil.which("tesseract.exe")


def _rasterizer() -> tuple[str, object] | None:
    """PDF 栅格化后端：(名字, 模块)。

    pypdfium2 优先——它是纯 wheel，macOS / Linux / Windows 都能直接 pip 装，
    不依赖系统的 poppler 或编译工具链；PyMuPDF 作为老环境的兜底。
    """
    try:
        import pypdfium2  # noqa: PLC0415 - 可选依赖，按需导入

        return "pypdfium2", pypdfium2
    except Exception:  # noqa: BLE001 - 缺库或加载失败都不该让能力起不来
        pass
    for name in ("pymupdf", "fitz"):
        try:
            return "pymupdf", __import__(name)
        except ImportError:
            continue
    return None


def _install_hint() -> str:
    """按平台给出能直接照抄的安装命令。"""
    if sys.platform == "darwin":
        return (
            "没有可用的 OCR 引擎。macOS 推荐安装 Xcode Command Line Tools"
            "（xcode-select --install，用系统 Vision 识别，中文效果最好）；"
            "也可以 brew install tesseract tesseract-lang 使用 tesseract。"
        )
    if sys.platform.startswith("win"):
        return (
            "没有可用的 OCR 引擎。请安装 Tesseract-OCR（含 chi_sim 中文包），"
            "安装时勾选加入 PATH；若未加入，可设置环境变量 TJH_TESSERACT_CMD 指向 tesseract.exe。"
        )
    return (
        "没有可用的 OCR 引擎。请安装 tesseract 与中文语言包："
        "Debian/Ubuntu `sudo apt install tesseract-ocr tesseract-ocr-chi-sim`；"
        "Fedora/RHEL `sudo dnf install tesseract tesseract-langpack-chi_sim`；"
        "Arch `sudo pacman -S tesseract tesseract-data-chi_sim`。"
    )


def _tesseract_langs() -> list[str]:
    binary = _tesseract_path()
    if not binary:
        return []
    try:
        out = subprocess.run([binary, "--list-langs"], capture_output=True, timeout=20).stdout.decode(
            "utf-8", "ignore"
        )
    except (subprocess.SubprocessError, OSError):
        return []
    return [line.strip() for line in out.splitlines()[1:] if line.strip()]


def probe() -> dict:
    """探测可用后端；供 /health 与设置页展示。"""
    vision_ready = vision_supported() and _has_swiftc()
    tesseract = _tesseract_path()
    raster = _rasterizer()
    rasterizer = "vision-pdfkit" if vision_ready else (raster[0] if raster else None)
    # 能识别 PDF 的条件：要么 Vision（自带栅格化），要么有栅格化器 + tesseract
    pdf_ready = vision_ready or bool(raster and tesseract)
    if vision_ready:
        preferred = "vision"
    elif tesseract:
        preferred = "tesseract"
    else:
        preferred = None

    hint = ""
    if preferred is None:
        hint = _install_hint()
    elif not pdf_ready:
        hint = "OCR 引擎可用，但缺少 PDF 栅格化能力：pip install pypdfium2"
    return {
        "available": preferred is not None,
        "pdf_ready": pdf_ready,
        "preferred": preferred,
        "rasterizer": rasterizer,
        "platform": sys.platform,
        "vision": {"supported": vision_supported(), "compiled": _tool_path().is_file()},
        "tesseract": {"installed": bool(tesseract), "languages": _tesseract_langs()},
        "hint": hint,
    }


# ---------------------------------------------------------------- 引擎实现


def _parse_lines(raw: str) -> dict[int, tuple[str, float | None]]:
    mapping: dict[int, tuple[str, float | None]] = {}
    for line in raw.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        page = payload.get("page")
        if not isinstance(page, int):
            continue
        confidence = payload.get("confidence")
        mapping[page] = (
            str(payload.get("text") or "").strip(),
            float(confidence) if isinstance(confidence, (int, float)) else None,
        )
    return mapping


def _run_tool(args: list[str], expected: int) -> list[OcrPage]:
    binary = ensure_tool_binary()
    if binary is None:
        raise ApiError(
            probe()["hint"] or "Vision OCR 不可用",
            code="ocr_unavailable",
            status=503,
        )
    try:
        proc = subprocess.run(
            [str(binary), *args],
            capture_output=True,
            timeout=max(60, PAGE_TIMEOUT * max(1, expected)),
        )
    except subprocess.TimeoutExpired as exc:
        raise ApiError(f"OCR 超时（{expected} 页）", code="ocr_timeout", status=504) from exc
    except (subprocess.SubprocessError, OSError) as exc:
        raise ApiError(f"OCR 执行失败：{exc}", code="ocr_failed", status=503) from exc
    mapping = _parse_lines(proc.stdout.decode("utf-8", "ignore"))
    return [
        OcrPage(page_index=page, text=text, confidence=confidence, engine="vision")
        for page, (text, confidence) in sorted(mapping.items())
    ]


def _run_vision_images(paths: list[Path]) -> list[OcrPage]:
    pages: list[OcrPage] = []
    batch = 20  # 一次传太多会撞 ARG_MAX
    for start in range(0, len(paths), batch):
        chunk = paths[start : start + batch]
        result = _run_tool(["image", *[str(path) for path in chunk]], len(chunk))
        for page in result:
            page.page_index = start + page.page_index
        pages.extend(result)
        if len(result) < len(chunk):
            for offset in range(len(result), len(chunk)):
                pages.append(OcrPage(start + offset + 1, "", None, "vision", "未返回结果"))
    return pages


def _tesseract_lang() -> str:
    langs = set(_tesseract_langs())
    wanted = [lang for lang in ("chi_sim", "eng") if lang in langs]
    return "+".join(wanted) or ("eng" if "eng" in langs else "")


def _run_tesseract(images: list[tuple[int, Path]]) -> list[OcrPage]:
    binary = _tesseract_path()
    if not binary:
        raise ApiError(_install_hint(), code="ocr_unavailable", status=503)
    lang = _tesseract_lang()
    pages: list[OcrPage] = []
    for number, path in images:
        command = [binary, str(path), "stdout"]
        if lang:
            command += ["-l", lang]
        command += ["--psm", "3", "tsv"]
        try:
            proc = subprocess.run(command, capture_output=True, timeout=PAGE_TIMEOUT)
        except (subprocess.SubprocessError, OSError) as exc:
            pages.append(OcrPage(number, "", None, "tesseract", str(exc)))
            continue
        text, confidence = _parse_tesseract_tsv(proc.stdout.decode("utf-8", "ignore"))
        pages.append(OcrPage(number, text, confidence, "tesseract"))
    return pages


def _parse_tesseract_tsv(raw: str) -> tuple[str, float | None]:
    """把 TSV 输出还原成按行聚合的文本，并算平均词置信度。"""
    lines: dict[tuple[str, str, str, str], list[str]] = {}
    scores: list[float] = []
    for index, row in enumerate(raw.splitlines()):
        if index == 0 or not row.strip():
            continue
        cells = row.split("\t")
        if len(cells) < 12:
            continue
        word = cells[11].strip()
        if not word:
            continue
        lines.setdefault((cells[1], cells[2], cells[3], cells[4]), []).append(word)
        try:
            value = float(cells[10])
        except ValueError:
            continue
        if value >= 0:
            scores.append(value / 100.0)
    text = "\n".join(" ".join(words) for words in lines.values())
    return text, (sum(scores) / len(scores) if scores else None)


# ---------------------------------------------------------------- 栅格化（非 macOS）


def _render_with_pdfium(
    pdfium: object,
    path: Path,
    page_numbers: Iterable[int],
    workdir: Path,
    dpi: int,
) -> list[tuple[int, Path]]:
    """pypdfium2 栅格化：纯 wheel，无需系统库，三大平台通用。"""
    rendered: list[tuple[int, Path]] = []
    document = pdfium.PdfDocument(str(path))  # type: ignore[attr-defined]
    try:
        total = len(document)
        for number in page_numbers:
            if number < 1 or number > total:
                continue
            page = document[number - 1]
            width_pt = float(page.get_width()) or 1.0
            scale = min(dpi / 72.0, MAX_RENDER_PX / width_pt)
            image = page.render(scale=scale).to_pil()
            target = workdir / f"page-{number:04d}.png"
            image.save(str(target), format="PNG")
            rendered.append((number, target))
    finally:
        document.close()
    return rendered


def _render_with_pymupdf(
    fitz: object,
    path: Path,
    page_numbers: Iterable[int],
    workdir: Path,
    dpi: int,
) -> list[tuple[int, Path]]:
    rendered: list[tuple[int, Path]] = []
    document = fitz.open(str(path))  # type: ignore[attr-defined]
    try:
        for number in page_numbers:
            if number < 1 or number > document.page_count:
                continue
            page = document.load_page(number - 1)
            zoom = dpi / 72.0
            width_pt = float(page.rect.width) or 1.0
            zoom = min(zoom, MAX_RENDER_PX / width_pt)
            pixmap = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)  # type: ignore[attr-defined]
            target = workdir / f"page-{number:04d}.png"
            pixmap.save(str(target))
            rendered.append((number, target))
    finally:
        document.close()
    return rendered


def render_pdf_pages(
    path: Path, page_numbers: Iterable[int], workdir: Path, dpi: int = DEFAULT_DPI
) -> list[tuple[int, Path]]:
    """把指定页渲染成 PNG。页码 1-based。

    后端优先级：pypdfium2 > PyMuPDF。两者都没有时给出可执行的安装提示，
    而不是抛一个看不清原因的错误。
    """
    backend = _rasterizer()
    if backend is None:
        raise ApiError(
            "缺少 PDF 栅格化依赖，无法把页面渲染成图片。请执行 pip install pypdfium2",
            code="ocr_renderer_missing",
            status=503,
        )
    workdir.mkdir(parents=True, exist_ok=True)
    name, module = backend
    if name == "pypdfium2":
        return _render_with_pdfium(module, path, page_numbers, workdir, dpi)
    return _render_with_pymupdf(module, path, page_numbers, workdir, dpi)


# ---------------------------------------------------------------- 对外接口


def ocr_image_files(paths: list[Path], engine: str | None = None) -> OcrOutcome:
    """对一组图片做 OCR，页序即列表顺序。"""
    if not paths:
        return OcrOutcome()
    chosen = engine or probe().get("preferred")
    if not chosen:
        raise ApiError(probe()["hint"], code="ocr_unavailable", status=503)
    if chosen == "vision":
        pages = _run_vision_images(paths)
    else:
        pages = _run_tesseract(list(enumerate(paths, start=1)))
    return OcrOutcome(
        pages=pages, engine=chosen, failed_pages=[page.page_index for page in pages if page.error]
    )


def ocr_pdf(
    path: Path,
    page_numbers: Iterable[int],
    engine: str | None = None,
    dpi: int = DEFAULT_DPI,
) -> OcrOutcome:
    """对 PDF 的指定页做 OCR。macOS 走 Vision 一站式，其它平台走 pypdfium2 栅格化 + tesseract。"""
    chosen = engine or probe().get("preferred")
    if not chosen:
        raise ApiError(probe()["hint"], code="ocr_unavailable", status=503)
    numbers = sorted({int(number) for number in page_numbers})
    if not numbers:
        return OcrOutcome()

    if chosen == "vision":
        pages = _run_tool(["pdf", str(path), ",".join(str(number) for number in numbers)], len(numbers))
        missing = [number for number in numbers if number not in {page.page_index for page in pages}]
        for number in missing:
            pages.append(OcrPage(number, "", None, "vision", "该页渲染或识别失败"))
        pages.sort(key=lambda page: page.page_index)
        return OcrOutcome(
            pages=pages,
            engine="vision",
            failed_pages=[page.page_index for page in pages if page.error],
        )

    with tempfile.TemporaryDirectory(prefix="tjh-ocr-pages-") as tmp:
        rendered = render_pdf_pages(path, numbers, Path(tmp), dpi=dpi)
        if not rendered:
            return OcrOutcome(engine=chosen)
        pages = _run_tesseract(rendered)
    return OcrOutcome(
        pages=pages, engine=chosen, failed_pages=[page.page_index for page in pages if page.error]
    )

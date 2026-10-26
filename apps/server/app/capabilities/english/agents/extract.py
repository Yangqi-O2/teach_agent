"""文件文本抽取：复用主站教材解析器（docx / pptx / pdf / epub / md / txt / html）。

原项目自己接 unpdf / mammoth；并入主站后统一走 `app.capabilities.library.parsers`，
这样格式支持、扫描件告警、位置标签都与「资料库」能力保持一致。

失败时不抛原始异常（解析库的报错对用户毫无意义），只给可行动的一句话；
按路由约定统一转成 422 `EXTRACT_FAILED`。
"""
from __future__ import annotations

import re
import tempfile
from pathlib import Path

from ....core.errors import ApiError
from ...library import parsers

MAX_BYTES = 12 * 1024 * 1024


def clean(raw: str) -> str:
    """去页眉页脚噪声、合并断行、压缩空行——不做这一步，切块质量会很差。"""
    lines = (raw or "").replace("\r\n", "\n").replace("\r", "\n").split("\n")
    lines = [line.strip() for line in lines]
    # 页码行
    lines = [line for line in lines if not re.fullmatch(r"[-–—\s]*\d{1,4}[-–—\s]*", line)]
    lines = [line for line in lines if not re.fullmatch(r"page\s+\d+(\s+of\s+\d+)?", line, re.IGNORECASE)]

    # 段落内被硬换行切断的句子接回来（行尾没有标点就拼接）
    merged: list[str] = []
    for line in lines:
        if not line:
            merged.append("")
            continue
        prev = merged[-1] if merged else ""
        if prev and not re.search(r"[.!?。！？:：;；]$", prev) and not re.match(r"^[A-Z0-9\-•*]", line):
            merged[-1] = f"{prev} {line}"
        else:
            merged.append(line)

    return re.sub(r"\n{3,}", "\n\n", "\n".join(merged)).strip()


def extract_text(data: bytes, filename: str) -> dict:
    """从上传的字节流抽取纯文本，返回 `{text, kind}`。

    - 空文件 / 超过 12MB / 不支持的格式 / 解析失败 → `ApiError(status=422)`
    - kind 为主站解析器的格式名：`txt` / `md` / `html` / `docx` / `pdf` / `pptx` / `epub`
    """
    if not data:
        raise ApiError("文件为空", code="EXTRACT_FAILED", status=422)
    if len(data) > MAX_BYTES:
        raise ApiError("文件超过 12MB，请拆分后再传", code="EXTRACT_FAILED", status=422)

    name = (filename or "").strip() or "upload.txt"
    kind = _detect_kind(name)

    suffix = Path(name).suffix.lower()
    handle = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    temp_path = Path(handle.name)
    try:
        handle.write(data)
        handle.close()
        parsed = parsers.parse_document(temp_path, kind)
    except ApiError as exc:
        raise ApiError(exc.message, code="EXTRACT_FAILED", status=422) from exc
    except Exception as exc:  # noqa: BLE001 - 解析库异常对用户没有意义
        raise ApiError(f"无法解析该文件：{exc}", code="EXTRACT_FAILED", status=422) from exc
    finally:
        if not handle.closed:
            handle.close()
        try:
            temp_path.unlink()
        except OSError:  # pragma: no cover - 临时文件清理失败不影响业务
            pass

    raw = "\n\n".join(block.text for block in parsed.blocks if block.text)
    text = clean(raw)
    return {"text": text, "kind": kind}


def _detect_kind(filename: str) -> str:
    """先由主站解析器判定格式；不支持的格式统一映射为 422。"""
    try:
        return parsers.detect_kind(filename)
    except ApiError as exc:
        raise ApiError(exc.message, code="EXTRACT_FAILED", status=422) from exc

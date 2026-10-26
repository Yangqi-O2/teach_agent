"""标题感知分块：400-600 字/块，块内保留位置与标题路径。

切分策略：
- 先按「标题路径变化」断开，保证一个块的引用位置是唯一的；
- 再按目标字数累积，超过 MAX_CHARS 用句子边界切成多片（带 OVERLAP_CHARS 重叠）；
- PDF / PPT 每个物理页独立成块，避免跨页引用指向错误的页码。
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from .parsers import ParsedBlock, ParsedDoc

TARGET_CHARS = 520
OVERLAP_CHARS = 80
MAX_CHARS = 900
# 低于这个长度才当作噪声丢弃。早期版本设成 30，结果扫描件里的短页（一页就两三行字）
# 会被整段静默丢掉——宁可留一条短块，也不能让内容凭空消失。
MIN_KEEP_CHARS = 10

@dataclass
class ChunkDraft:
    text: str
    heading_path: str
    loc_label: str
    loc_index: int
    n_chars: int


def _sentences(text: str) -> list[str]:
    """按句末标点切句。

    英文句号只在「后面是空白或结尾」时才认作句末，因此 3.14 / U.S.A / e.g. 不会被切断。
    """
    pieces: list[str] = []
    start = 0
    for index, char in enumerate(text):
        if char in "。！？；!?":
            pass
        elif char == ".":
            nxt = text[index + 1] if index + 1 < len(text) else ""
            if nxt and not nxt.isspace():
                continue
        else:
            continue
        pieces.append(text[start : index + 1])
        start = index + 1
    tail = text[start:]
    if tail:
        pieces.append(tail)
    return [piece for piece in pieces if piece]


def _split_long(text: str) -> list[str]:
    """把超长块按句子边界切开，并保留少量重叠上下文。"""
    pieces: list[str] = []
    current = ""
    for sentence in _sentences(text):
        if len(current) + len(sentence) > MAX_CHARS and current:
            pieces.append(current)
            current = current[-OVERLAP_CHARS:] + sentence
        else:
            current += sentence
    if current.strip():
        pieces.append(current)
    return [piece.strip() for piece in pieces if piece.strip()]


def _heading_of(block: ParsedBlock) -> str:
    return " > ".join(block.heading_path) if block.heading_path else ""


_NOISE = re.compile(r"^[\s\d\-—–_.·•第页页码/第共Cchapter]*$", re.IGNORECASE)


def _keep(text: str) -> bool:
    """过滤纯页码 / 页眉点线这类噪声，但保留一切有实义的短文本。"""
    stripped = text.strip()
    if len(stripped) < MIN_KEEP_CHARS:
        return False
    return not _NOISE.match(stripped)


def build_chunks(doc: ParsedDoc) -> list[ChunkDraft]:
    chunks: list[ChunkDraft] = []
    buffer: list[ParsedBlock] = []
    current_heading = ""

    def flush() -> None:
        nonlocal buffer
        if not buffer:
            return
        head = buffer[0]
        text = "\n".join(block.text for block in buffer).strip()
        if text:
            heading = _heading_of(head)
            if len(text) > MAX_CHARS:
                for piece in _split_long(text):
                    if _keep(piece):
                        chunks.append(
                            ChunkDraft(piece, heading, head.loc_label, head.loc_index, len(piece))
                        )
            elif _keep(text):
                chunks.append(ChunkDraft(text, heading, head.loc_label, head.loc_index, len(text)))
        buffer = []

    for block in doc.blocks:
        heading = _heading_of(block)
        if heading != current_heading:
            flush()
            current_heading = heading
        buffer.append(block)
        if sum(len(item.text) for item in buffer) >= TARGET_CHARS:
            flush()
        # 物理分页的格式：每个页/每张幻灯片必须独立成块，否则引用定位会错页
        if doc.kind in ("pptx", "pdf") and block is not doc.blocks[-1]:
            flush()

    flush()
    return chunks

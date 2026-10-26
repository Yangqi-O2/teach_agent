"""资料检索（BM25 词法检索）。

说明：当前没有向量模型 Key，用 BM25 作离线实现——确定性、可测，而且对
「专有名词/数字/术语」这类问题效果不差。接上 embedding 后把 rank_bm25 换成
向量召回即可，接口不变。

照搬 etutor-cn `api/src/agents/rag.ts`：切块按段落、尽量不劈开句子；BM25 k1=1.5、
b=0.75；注入时要求模型只依据资料、不越界编造。
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass

MAX_CHARS = 600
OVERLAP = 80
MIN_CHUNK_CHARS = 20

_STOP = set(
    "the a an and or but if then of to in on at for with by from as is are was were "
    "be been it this that these those".split()
)

_TOKEN_RE = re.compile(r"[a-z][a-z'-]{1,}|\d+")


@dataclass
class Chunk:
    """一段可检索的资料块。"""

    id: str
    document_id: str
    idx: int
    content: str


def chunk_text(text: str, max_chars: int = MAX_CHARS, overlap: int = OVERLAP) -> list[str]:
    """按段落切块，尽量不把句子劈开；超长段落再硬切（带 overlap）。"""
    if max_chars <= 0:
        return []
    overlap = max(0, min(int(overlap), max_chars - 1))
    step = max_chars - overlap

    clean = re.sub(r"[ \t]+", " ", (text or "").replace("\r\n", "\n")).strip()
    if not clean:
        return []

    paras = [para.strip() for para in re.split(r"\n{2,}", clean) if para.strip()]
    chunks: list[str] = []
    buf = ""

    def flush() -> None:
        nonlocal buf
        if buf.strip():
            chunks.append(buf.strip())
        buf = ""

    for para in paras:
        if len(para) > max_chars:
            flush()
            for start in range(0, len(para), step):
                chunks.append(para[start : start + max_chars].strip())
            continue
        candidate = f"{buf}\n\n{para}" if buf else para
        if len(candidate) > max_chars:
            flush()
            # 保留一点上下文，避免跨块丢指代
            buf = para
        else:
            buf = candidate
    flush()
    return [chunk for chunk in chunks if len(chunk) >= MIN_CHUNK_CHARS]


def tokenize(text: str) -> list[str]:
    """小写、只保留英文词与数字，并去掉检索无意义的停用词。"""
    return [term for term in _TOKEN_RE.findall((text or "").lower()) if term not in _STOP]


def rank_bm25(query: str, chunks: list[Chunk], top_k: int = 3) -> list[tuple[Chunk, float]]:
    """BM25：k1=1.5 b=0.75。语料是单个情景 / 用户资料下的全部块。"""
    if not chunks:
        return []
    query_terms = tokenize(query)
    if not query_terms:
        return []

    docs = [(chunk, tokenize(chunk.content)) for chunk in chunks]
    avg_len = sum(len(terms) for _, terms in docs) / len(docs)
    if avg_len <= 0:
        return []

    doc_freq: dict[str, int] = {}
    for _, terms in docs:
        for term in set(terms):
            doc_freq[term] = doc_freq.get(term, 0) + 1

    k1 = 1.5
    b = 0.75
    total_docs = len(docs)
    unique_query_terms = set(query_terms)

    scored: list[tuple[Chunk, float]] = []
    for chunk, terms in docs:
        term_freq: dict[str, int] = {}
        for term in terms:
            term_freq[term] = term_freq.get(term, 0) + 1
        score = 0.0
        for term in unique_query_terms:
            freq = term_freq.get(term, 0)
            if not freq:
                continue
            n = doc_freq.get(term, 0)
            idf = math.log(1 + (total_docs - n + 0.5) / (n + 0.5))
            denom = freq + k1 * (1 - b + (b * len(terms)) / avg_len)
            if denom <= 0:
                continue
            score += idf * ((freq * (k1 + 1)) / denom)
        if score > 0:
            scored.append((chunk, score))

    scored.sort(key=lambda item: item[1], reverse=True)
    return scored[: max(0, int(top_k))]


def render_reference(hits: list[tuple[Chunk, float]], doc_titles: dict[str, str]) -> str:
    """注入文档的事实块，要求模型只依据它、不越界编造。"""
    if not hits:
        return ""
    lines = [
        "Reference material from the learner's own documents (base factual claims on this; "
        "if it does not cover something, say you are not sure instead of inventing):"
    ]
    for index, (chunk, _score) in enumerate(hits, 1):
        title = doc_titles.get(chunk.document_id) or "document"
        lines.append(f"[{index}] {title} · part {chunk.idx + 1}: {chunk.content[:400]}")
    return "\n".join(lines)

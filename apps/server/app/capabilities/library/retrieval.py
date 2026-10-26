"""混合检索：FTS5(jieba 预切词) + numpy 余弦 + RRF 融合，按用户 / 双池过滤。

设计取舍
--------
1. **中文必须预切词**。SQLite 内置的 unicode61 分词不理解中文，`应力张量` 会被当作
   一个 token，用户搜「张量」就命中不了。所以入库时用 jieba 把正文切成空格分隔的
   token 再进 FTS5；查询时同样切词，用 `OR` 连接。
2. **向量是可选增强，不是前提**。没配 embed_model 时自动退化为纯 BM25；有向量时用
   RRF 融合两路排名——RRF 只看名次不看分数，省掉「BM25 分与余弦相似度不可比」的麻烦。
3. **必须有兜底**。OCR 文本常有奇怪断行，FTS token 可能整句对不上；命中为空时退回
   LIKE 逐词扫描，「能搜到」优先于「排得好」。
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any, Iterable, Sequence

import jieba
from sqlalchemy import text

from . import store
from .chunking import ChunkDraft

log = logging.getLogger(__name__)

jieba.setLogLevel(logging.WARNING)

RRF_K = 60
BM25_POOL = 50
VECTOR_POOL = 2000
MAX_CONTEXT_CHARS = 5200

_TOKEN_RE = re.compile(r"[0-9A-Za-z\u4e00-\u9fff]+")

STOPWORDS = {
    "的", "了", "是", "在", "和", "与", "就", "都", "而", "及", "或", "一个", "什么",
    "怎么", "如何", "为什么", "哪些", "这个", "那个", "请问", "一下", "可以",
    "the", "a", "an", "of", "is", "are", "to", "and", "or", "in", "on", "for",
    "what", "how", "why", "please", "does", "did",
}


@dataclass
class Hit:
    chunk_id: int
    document_id: int
    document_title: str
    ord: int
    text: str
    heading_path: str
    loc_label: str
    loc_index: int
    score: float = 0.0
    source: str = "bm25"

    def as_citation(self, index: int) -> dict[str, Any]:
        return {
            "index": index,
            "chunk_id": self.chunk_id,
            "document_id": self.document_id,
            "document_title": self.document_title,
            "loc_label": self.loc_label,
            "loc_index": self.loc_index,
            "heading_path": self.heading_path,
            "snippet": self.text[:220],
            "text": self.text,
            "score": round(self.score, 4),
            "retriever": self.source,
        }


@dataclass
class SearchResult:
    hits: list[Hit] = field(default_factory=list)
    mode: str = "bm25"          # bm25 | hybrid | like | empty
    query_terms: list[str] = field(default_factory=list)
    degraded: bool = False
    note: str = ""


# ---------------------------------------------------------------- 分词


def tokenize(query: str) -> list[str]:
    """查询切词：jieba 切分 + 去停用词 + 去重（保留出现顺序）。"""
    terms: list[str] = []
    for raw in jieba.lcut((query or "").strip()):
        token = raw.strip().lower()
        if not token or token in STOPWORDS:
            continue
        if len(token) < 2 and not token.isdigit():
            continue
        if not _TOKEN_RE.fullmatch(token):
            continue
        if token not in terms:
            terms.append(token)
    return terms


def segments_of(text_value: str) -> str:
    """把正文切成空格分隔的 token 串，供 FTS5 建索引。"""
    return " ".join(token for token in jieba.lcut(text_value or "") if token.strip())


# ---------------------------------------------------------------- 写入


def replace_chunks(document_id: int, user_id: int, drafts: Sequence[ChunkDraft]) -> int:
    """重建一份教材的分块与全文索引，返回块数。"""
    delete_chunks(document_id)
    if not drafts:
        return 0
    inserted = 0
    with store.engine.begin() as conn:
        for ordinal, draft in enumerate(drafts):
            result = conn.execute(
                text(
                    "INSERT INTO chunks (user_id, document_id, ord, text, heading_path, "
                    "loc_label, loc_index, n_chars, embedded) "
                    "VALUES (:user_id, :document_id, :ord, :text, :heading_path, "
                    ":loc_label, :loc_index, :n_chars, 0)"
                ),
                {
                    "user_id": user_id,
                    "document_id": document_id,
                    "ord": ordinal,
                    "text": draft.text,
                    "heading_path": draft.heading_path,
                    "loc_label": draft.loc_label,
                    "loc_index": draft.loc_index,
                    "n_chars": draft.n_chars,
                },
            )
            chunk_id = int(result.lastrowid or 0)
            conn.execute(
                text(
                    "INSERT INTO chunks_fts (rowid, text_seg, heading_seg) "
                    "VALUES (:rowid, :text_seg, :heading_seg)"
                ),
                {
                    "rowid": chunk_id,
                    "text_seg": segments_of(draft.text),
                    "heading_seg": segments_of(draft.heading_path),
                },
            )
            inserted += 1
    return inserted


def delete_chunks(document_id: int) -> None:
    rows = store.q("SELECT id FROM chunks WHERE document_id = :doc", doc=document_id)
    if not rows:
        return
    with store.engine.begin() as conn:
        for row in rows:
            conn.execute(text("DELETE FROM chunks_fts WHERE rowid = :rid"), {"rid": row["id"]})
        conn.execute(text("DELETE FROM chunks WHERE document_id = :doc"), {"doc": document_id})


def store_embeddings(vectors: dict[int, list[float]]) -> int:
    """把向量写成 float32 BLOB；没有 numpy 时静默跳过。"""
    try:
        import numpy as np
    except ImportError:  # pragma: no cover
        return 0
    count = 0
    with store.engine.begin() as conn:
        for chunk_id, vector in vectors.items():
            conn.execute(
                text("UPDATE chunks SET embedding = :blob, embedded = 1 WHERE id = :id"),
                {"blob": np.asarray(vector, dtype="float32").tobytes(), "id": chunk_id},
            )
            count += 1
    return count


# ---------------------------------------------------------------- 读取


def _resolve_scope(user_id: int, document_ids: Iterable[int] | None) -> list[int]:
    """把「用户点名的教材」与「用户能看到的教材」取交集——权限永远优先。"""
    rows = store.q(f"SELECT id FROM documents WHERE {store.scope_sql()}", uid=user_id)
    visible = {int(row["id"]) for row in rows}
    if document_ids is None:
        return sorted(visible)
    return sorted(visible & {int(item) for item in document_ids})


_SELECT_COLUMNS = (
    "c.id, c.document_id, c.ord, c.text, c.heading_path, c.loc_label, c.loc_index, d.title"
)


def _rows_to_hits(rows: list[dict], scores: dict[int, float], source: str) -> list[Hit]:
    return [
        Hit(
            chunk_id=int(row["id"]),
            document_id=int(row["document_id"]),
            document_title=str(row.get("title") or ""),
            ord=int(row.get("ord") or 0),
            text=str(row.get("text") or ""),
            heading_path=str(row.get("heading_path") or ""),
            loc_label=str(row.get("loc_label") or ""),
            loc_index=int(row.get("loc_index") or 0),
            score=scores.get(int(row["id"]), 0.0),
            source=source,
        )
        for row in rows
    ]


def _bm25(scope: list[int], terms: list[str], limit: int) -> list[Hit]:
    if not scope or not terms:
        return []
    match = " OR ".join('"' + term.replace('"', '""') + '"' for term in terms)
    sql = (
        f"SELECT {_SELECT_COLUMNS}, bm25(chunks_fts) AS rank "
        "FROM chunks_fts JOIN chunks c ON c.id = chunks_fts.rowid "
        "JOIN documents d ON d.id = c.document_id "
        "WHERE chunks_fts MATCH :match AND c.document_id IN :scope "
        "ORDER BY rank LIMIT :limit"
    )
    try:
        rows = store.q(sql, expanding=("scope",), match=match, scope=scope, limit=limit)
    except Exception as exc:  # noqa: BLE001 - FTS 语法问题不该让问答整体失败
        log.warning("BM25 检索失败，已降级：%s", exc)
        return []
    scores = {int(row["id"]): -float(row["rank"] or 0.0) for row in rows}
    return _rows_to_hits(rows, scores, "bm25")


def _vector(scope: list[int], query_vector: list[float], limit: int) -> list[Hit]:
    if not scope or not query_vector:
        return []
    try:
        import numpy as np
    except ImportError:  # pragma: no cover
        return []
    rows = store.q(
        f"SELECT {_SELECT_COLUMNS}, c.embedding FROM chunks c "
        "JOIN documents d ON d.id = c.document_id "
        "WHERE c.document_id IN :scope AND c.embedded = 1 AND c.embedding IS NOT NULL "
        "LIMIT :limit",
        expanding=("scope",),
        scope=scope,
        limit=VECTOR_POOL,
    )
    if not rows:
        return []
    query = np.asarray(query_vector, dtype="float32")
    query_norm = float(np.linalg.norm(query)) or 1.0
    scored: list[tuple[float, dict]] = []
    for row in rows:
        raw = row.get("embedding")
        if not raw:
            continue
        vector = np.frombuffer(raw, dtype="float32")
        if vector.shape != query.shape:
            continue
        denominator = (float(np.linalg.norm(vector)) or 1.0) * query_norm
        scored.append((float(np.dot(query, vector) / denominator), row))
    scored.sort(key=lambda item: item[0], reverse=True)
    top = scored[:limit]
    scores = {int(row["id"]): score for score, row in top}
    return _rows_to_hits([row for _, row in top], scores, "vector")


def _like(scope: list[int], terms: list[str], limit: int) -> list[Hit]:
    """兜底：FTS 无命中时逐词 LIKE，按命中词数排序。"""
    if not scope or not terms:
        return []
    conditions = " OR ".join(f"c.text LIKE :p{index}" for index in range(len(terms)))
    params: dict[str, Any] = {"scope": scope, "limit": limit * 4}
    for index, term in enumerate(terms):
        params[f"p{index}"] = f"%{term}%"
    sql = (
        f"SELECT {_SELECT_COLUMNS} FROM chunks c JOIN documents d ON d.id = c.document_id "
        f"WHERE c.document_id IN :scope AND ({conditions}) LIMIT :limit"
    )
    try:
        rows = store.q(sql, expanding=("scope",), **params)
    except Exception as exc:  # noqa: BLE001
        log.warning("LIKE 兜底检索失败: %s", exc)
        return []
    scores: dict[int, float] = {}
    for row in rows:
        body = str(row.get("text") or "").lower()
        scores[int(row["id"])] = float(sum(1 for term in terms if term in body))
    rows.sort(key=lambda row: scores.get(int(row["id"]), 0.0), reverse=True)
    return _rows_to_hits(rows[:limit], scores, "like")


def _rrf(ranked_lists: list[list[Hit]], limit: int) -> list[Hit]:
    """Reciprocal Rank Fusion：只看名次，规避两路分数量纲不一致。"""
    merged: dict[int, Hit] = {}
    total: dict[int, float] = {}
    for hits in ranked_lists:
        for rank, hit in enumerate(hits, start=1):
            merged.setdefault(hit.chunk_id, hit)
            total[hit.chunk_id] = total.get(hit.chunk_id, 0.0) + 1.0 / (RRF_K + rank)
    fused = list(merged.values())
    for hit in fused:
        hit.score = total[hit.chunk_id]
        hit.source = "fused"
    fused.sort(key=lambda hit: hit.score, reverse=True)
    return fused[:limit]


async def search(
    user_id: int,
    query: str,
    document_ids: Iterable[int] | None = None,
    limit: int = 8,
    llm: Any = None,
) -> SearchResult:
    """在「可见」或「指定」的教材里检索。

    `llm` 传 None、或供应商没配向量模型时，自动退化为纯 BM25。
    """
    terms = tokenize(query)
    scope = _resolve_scope(user_id, document_ids)
    if not scope:
        return SearchResult(mode="empty", query_terms=terms, note="没有可检索的教材")
    if not terms:
        return SearchResult(mode="empty", query_terms=terms, note="问题里没有可检索的关键词")

    lists: list[list[Hit]] = [_bm25(scope, terms, BM25_POOL)]
    mode = "bm25"
    degraded = False
    note = ""

    if llm is not None:
        try:
            vectors = await llm.embed([query])
            vector_hits = _vector(scope, vectors[0], BM25_POOL) if vectors else []
            if vector_hits:
                lists.append(vector_hits)
                mode = "hybrid"
        except Exception as exc:  # noqa: BLE001 - 向量不可用不影响主流程
            degraded = True
            note = f"向量检索不可用，已退化为关键词检索（{exc}）"
            log.info("向量检索降级: %s", exc)

    hits = _rrf(lists, limit) if mode == "hybrid" else lists[0][:limit]
    if not hits:
        hits = _like(scope, terms, limit)
        if hits:
            mode = "like"
            note = note or "关键词索引未命中，已改用模糊匹配"
    return SearchResult(hits=hits, mode=mode, query_terms=terms, degraded=degraded, note=note)


# ---------------------------------------------------------------- 拼上下文


def build_context(hits: Sequence[Hit], max_chars: int = MAX_CONTEXT_CHARS) -> tuple[str, list[Hit]]:
    """把命中块拼成带编号的参考资料；超长时截断并丢弃未使用的块。"""
    blocks: list[str] = []
    used: list[Hit] = []
    total = 0
    for hit in hits:
        label = hit.loc_label or f"第 {hit.ord + 1} 块"
        heading = f" · {hit.heading_path}" if hit.heading_path else ""
        piece = f"[{len(used) + 1}] 《{hit.document_title}》{label}{heading}\n{hit.text.strip()}"
        if total + len(piece) > max_chars and used:
            break
        blocks.append(piece)
        used.append(hit)
        total += len(piece)
    return "\n\n".join(blocks), used

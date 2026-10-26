"""生词：候选词抽取、每轮必用词、命中统计。

纯规则、零模型调用（照搬 etutor-cn `api/src/agents/vocab.ts`）：

- `candidates` 从 AI 回复里做确定性预筛：跳过句首/专有名词（大写开头）、停用词、重复词，
  再按长度降序取前 N 个（长词更可能是难点）；
- `must_use_words` 先取到期复习词，不够再补最近存的新词；
- `count_hits` 统计这一轮回复里真正用上了哪些目标词（\b 词边界，避免误报）。
"""
from __future__ import annotations

import re

from ..store import now_iso, q

# 高频功能词 / 太简单的词：不适合当生词推荐
STOP: set[str] = set(
    """
    the a an and or but if then than that this these those there here what when where which who whom why how
    i you he she it we they me him her us them my your his its our their mine yours
    am is are was were be been being do does did have has had will would shall should can could may might must
    not no nor so as at by for from in into of on onto out over to up with within without about after before
    because while during through between among against around across along behind beyond
    very too also just only even still yet again more most much many some any all both each few other another
    said says say go goes went gone going get gets got gotten make makes made take takes took taken
    know knows knew known think thinks thought want wants wanted need needs needed like likes liked
    good better best bad worse worst big small long short new old same different
    one two three four five six seven eight nine ten first second next last
    time day week month year today tomorrow yesterday now soon later
    people person thing things way part place work life world case point fact
    really quite rather pretty lot bit kind sort thing something anything nothing everything
    okay ok yes yeah well right sure maybe perhaps actually basically literally
    """.split()
)

_WORD_RE = re.compile(r"\b[A-Za-z][A-Za-z'-]{4,}\b")


def candidates(text: str, limit: int = 6) -> list[str]:
    """从 AI 回复里抽候选生词（确定性，保留出现顺序稳定性后按长度排序）。"""
    seen: set[str] = set()
    found: list[str] = []
    for match in _WORD_RE.finditer(text or ""):
        raw = match.group(0)
        # 大写开头的多半是专有名词或句首词，跳过
        if raw[0].isupper():
            continue
        word = raw.lower()
        if word in STOP or word in seen:
            continue
        seen.add(word)
        found.append(word)
    # 长词更可能是难点，但不做绝对排序，保留出现顺序的稳定性（sorted 是稳定排序）
    return sorted(found, key=len, reverse=True)[: max(0, int(limit))]


def must_use_words(user_id: int, limit: int = 3) -> list[str]:
    """下一轮要自然复用的词：先取到期的，不够再取最近新存的。"""
    if limit <= 0:
        return []
    due = q(
        "SELECT lemma FROM english_vocab_states "
        "WHERE user_id = :user_id AND next_review_at IS NOT NULL AND next_review_at <= :now "
        "ORDER BY next_review_at ASC LIMIT :limit",
        user_id=user_id,
        now=now_iso(),
        limit=limit,
    )
    picked = [str(row["lemma"]) for row in due]
    if len(picked) >= limit:
        return picked[:limit]

    params: dict = {"user_id": user_id, "limit": limit - len(picked)}
    skip = ""
    if picked:
        placeholders = []
        for index, lemma in enumerate(picked):
            key = f"skip_{index}"
            params[key] = lemma
            placeholders.append(f":{key}")
        skip = f"AND lemma NOT IN ({', '.join(placeholders)})"

    fresh = q(
        f"SELECT lemma FROM english_vocab_items WHERE user_id = :user_id {skip} "
        "ORDER BY created_at DESC LIMIT :limit",
        **params,
    )
    return picked + [str(row["lemma"]) for row in fresh]


def count_hits(text: str, words: list[str]) -> list[str]:
    """回复里用到了哪些目标词，用于统计「复用命中率」。"""
    lowered = (text or "").lower()
    hits: list[str] = []
    for word in words:
        if not word:
            continue
        pattern = re.compile(r"\b" + re.escape(str(word).lower()) + r"\b")
        if pattern.search(lowered):
            hits.append(word)
    return hits

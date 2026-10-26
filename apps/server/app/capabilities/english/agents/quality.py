"""回复质量测量（2a：只记录，不拦截）。

移植自 `.tmp/etutor-src/api/src/agents/quality.ts`。为什么先测量再拦截：
阈值应该由真实模型的数据分布决定，现在拍脑袋定一个「超纲词 >15% 就拦」，
很可能把好回复也拦掉。

metrics 的字段名保持 TS 版 camelCase（SSE meta / messages.metrics JSON 原样落库，
前端成本看板按这些字段读）。
"""
from __future__ import annotations

import re
from typing import Any

# 提示词里明令禁止的表达。这里只做检测，不做纠正。
BANNED: list[str] = [
    "it is important to",
    "in conclusion",
    "furthermore",
    "moreover",
    "delve",
    "tapestry",
    "in today's world",
    "as an ai",
]

# 极简分级词表：够用来观察分布，不够用来做判定。wordBasis 字段会如实标出。
LEVEL_WORDS: dict[str, list[str]] = {
    "A2": [
        "go", "get", "take", "make", "work", "need", "want", "help", "find", "give",
        "tell", "think", "know", "come", "look", "day", "week", "time", "place", "people",
    ],
    "B1": [
        "decision", "company", "market", "report", "process", "require", "provide",
        "increase", "reduce", "consider", "suggest", "explain", "compare", "manage", "arrange",
    ],
    "B2": [
        "negotiate", "assess", "implement", "allocate", "constraint", "compliance",
        "leverage", "mitigate", "substantial", "inevitable",
    ],
    "C1": [
        "notwithstanding", "paradigm", "ubiquitous", "proliferation", "reconcile",
        "substantiate", "ostensibly",
    ],
}

LEVEL_ORDER: list[str] = ["A2", "B1", "B2", "C1"]

# 硬违规：截断 / 格式 / 禁用词 / 过短。软违规（缺问句等）也重写一次。
HARD: set[str] = {"unfinished", "list_format", "has_heading", "too_short", "banned"}

_WORD_RE = re.compile(r"[a-z][a-z'-]*")
_SENT_SPLIT_RE = re.compile(r"[.!?]+\s*")
_ENDS_QUESTION_RE = re.compile(r"""\?["')\]]*\s*$""")
_UNFINISHED_RE = re.compile(r"""[.!?"')\]]\s*$""")
_LIST_RE = re.compile(r"^\s*(\d+[.)]|[-*•])\s+", re.MULTILINE)
_HEADING_RE = re.compile(r"^\s*#{1,6}\s", re.MULTILINE)
_FENCE_RE = re.compile(r"```[\s\S]*?```")
_MARK_RE = re.compile(r"[*_`>#]")

_ALL_LEVEL_WORDS: set[str] = {w for words in LEVEL_WORDS.values() for w in words}


def _tokenize(text: str) -> list[str]:
    """等价 TS 的 `s.toLowerCase().match(/[a-z][a-z'-]*/g) ?? []`。"""
    return _WORD_RE.findall(text.lower())


def measure_reply(text: str, cefr: str) -> dict[str, Any]:
    """测量一条回复。返回 `{flags: [...], metrics: {...}}`（照搬 TS 的 Verdict）。"""
    raw = (text or "").strip()
    plain = _MARK_RE.sub(" ", _FENCE_RE.sub(" ", raw)).strip()

    words = _tokenize(plain)
    sentences = [s for s in _SENT_SPLIT_RE.split(plain) if s.strip()]
    avg = len(words) / len(sentences) if sentences else float(len(words))

    # 提示词要求「结尾必须是一个具体问题」，这是可测的
    ends_with_question = bool(_ENDS_QUESTION_RE.search(raw))

    lower = plain.lower()
    banned_hits = [b for b in BANNED if b in lower]

    list_like = bool(_LIST_RE.search(raw))
    has_heading = bool(_HEADING_RE.search(raw))

    # cefr 未知时按 A2 处理（TS: Math.max(0, LEVEL_ORDER.indexOf(cefr))）
    idx = LEVEL_ORDER.index(cefr) if cefr in LEVEL_ORDER else -1
    idx = max(0, idx)
    allowed = {w for level in LEVEL_ORDER[: idx + 1] for w in LEVEL_WORDS[level]}
    known = [w for w in words if w in _ALL_LEVEL_WORDS]
    over = sum(1 for w in known if w not in allowed)
    over_level_ratio = (over / len(known)) if known else 0.0

    # 连续两句同开头，是最典型的「机器味」
    openers = [tokens[0] for s in sentences if (tokens := _tokenize(s))]
    repeated_opener = any(openers[i] == openers[i - 1] for i in range(1, len(openers)))

    # 被截断的回复末尾不是句末标点。只看词数会漏掉「57 个词但断在半个单词」
    unfinished = not bool(_UNFINISHED_RE.search(raw))

    metrics: dict[str, Any] = {
        "words": len(words),
        "sentences": len(sentences),
        "avgSentenceWords": round(avg, 1),
        "endsWithQuestion": ends_with_question,
        "bannedHits": banned_hits,
        "listLike": list_like,
        "hasHeading": has_heading,
        "overLevelRatio": round(over_level_ratio, 3),
        "repeatedOpener": repeated_opener,
        "unfinished": unfinished,
        "wordBasis": f"builtin:{len(_ALL_LEVEL_WORDS)}words",
    }

    flags: list[str] = []
    if not ends_with_question:
        flags.append("no_question")
    if unfinished:
        flags.append("unfinished")
    if banned_hits:
        flags.append("banned:" + ",".join(banned_hits))
    if list_like:
        flags.append("list_format")
    if has_heading:
        flags.append("has_heading")
    if repeated_opener:
        flags.append("repeated_opener")
    if metrics["words"] < 40:
        flags.append("too_short")
    if metrics["words"] > 160:
        flags.append("too_long")
    if metrics["avgSentenceWords"] > 24:
        flags.append("long_sentences")
    if over_level_ratio > 0.3:
        flags.append("over_level")

    return {"metrics": metrics, "flags": flags}


def _flag_key(flag: str) -> str:
    return flag.split(":")[0]


def needs_repair(verdict: dict[str, Any]) -> bool:
    """2b 判定：硬违规 + 缺问句才重写；阈值来自真机 20 轮数据。"""
    flags = verdict.get("flags") or []
    if not flags:
        return False
    return any(_flag_key(f) in HARD or _flag_key(f) == "no_question" for f in flags)


def penalty_of(verdict: dict[str, Any]) -> int:
    """越小越好：硬违规每条扣 10，软违规每条扣 1。"""
    return sum(-10 if _flag_key(f) in HARD else -1 for f in (verdict.get("flags") or []))


def repair_hint(verdict: dict[str, Any]) -> str:
    """把 flags 翻译成给模型的「重写指令」。"""
    flags: list[str] = verdict.get("flags") or []
    metrics: dict[str, Any] = verdict.get("metrics") or {}
    banned_hits: list[str] = metrics.get("bannedHits") or []

    problems: list[str] = []
    if "unfinished" in flags:
        problems.append("your last reply was cut off mid-sentence")
    if "no_question" in flags:
        problems.append("you did not end with a question")
    if "list_format" in flags:
        problems.append("you used a list instead of talking")
    if "has_heading" in flags:
        problems.append("you used markdown headings")
    if any(f.startswith("banned:") for f in flags):
        problems.append("you used phrases the learner should not see")
    if "too_short" in flags:
        problems.append("your reply was too short")
    if any(f.startswith("banned:") for f in flags):
        problems.append(f"avoid: {', '.join(banned_hits)}")
    return (
        f"Rewrite your previous reply. Problems: {'; '.join(problems)}. "
        "Stay in character, 50–90 words, finish the sentence, end with one concrete question, "
        "no lists, no headings."
    )

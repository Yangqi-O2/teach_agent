"""语法纠错（analyst）。

移植自 `.tmp/etutor-src/api/src/agents/analyst.ts`：
- 严格类型是「我们内部」的契约；模型输出则必须宽容（会漏 severity、span 写成空串、
  confidence 写成字符串），所以先收进来再归一化；
- 模型算错下标是常态：必须回验 span 是否真的出现在原文里，否则前端会标到错误的字符上；
- `llm.mock=True` 或调用失败时用规则兜底（不代表模型能力，只保证链路可跑通）。
"""
from __future__ import annotations

import logging
import math
import re
from collections.abc import Mapping
from typing import Any

from pydantic import BaseModel, Field

from .taxonomy import ERROR_CODES, TAXONOMY, default_severity

log = logging.getLogger(__name__)


class GrammarError(BaseModel):
    """一条确定的语法错误（喂给前端 annotations / error_events 表）。"""

    code: str
    span: str
    correction: str
    explain_zh: str
    severity: str
    confidence: float


class Analysis(BaseModel):
    """一次纠错的结果。"""

    errors: list[GrammarError] = Field(default_factory=list)
    confidence: float = 0.8


class RawError(BaseModel):
    """模型输出的单条错误：全部可选，归一化时再收敛。"""

    span: str | None = None
    code: str | None = None
    severity: str | None = None
    correction: str | None = None
    explain_zh: str | None = None


class AnalysisSchema(BaseModel):
    """模型输出的结构（宽容版；start/end 等多余字段直接忽略）。"""

    errors: list[RawError] = Field(default_factory=list, max_length=8)
    confidence: float | str | None = None


SYSTEM = f"""你是英语学习者的语法审校器。分析学生写的一句话，只标出确定的错误。

规则：
1. 宁漏不误报。不确定的不要标；母语者会这么说的，不算错。
2. 最多 5 条。拼写、大小写只在明显错误时标。
3. code 必须从给定枚举里选，不得自创。
4. correction 只给改法（替换片段），不要整句重写。
5. explain_zh 用中文，30 字以内，说清"为什么错"。
6. start/end 是该片段在原文中的字符下标，span 必须与原文完全一致。

枚举：{', '.join(ERROR_CODES)}

只输出一个 JSON 对象（不是 markdown 代码块、不是解释文字），字段为 errors 与 confidence。"""

_SEVERITIES = ("low", "medium", "high")


# ---------------------------------------------------------------- 归一化


def _js_number(value: Any) -> float | None:
    """模拟 JS `Number(x)`：无法转成有限数时返回 None（对应 NaN）。"""
    if value is None:
        return None
    if isinstance(value, bool):
        return 1.0 if value else 0.0
    if isinstance(value, (int, float)):
        number = float(value)
        return number if math.isfinite(number) else None
    if isinstance(value, str):
        text = value.strip()
        if text == "":
            return 0.0
        try:
            number = float(text)
        except ValueError:
            return None
        return number if math.isfinite(number) else None
    return None


def _as_mapping(item: Any) -> Mapping[str, Any]:
    if isinstance(item, BaseModel):
        return item.model_dump()
    if isinstance(item, Mapping):
        return item
    return {}


def normalize_analysis(raw: dict | BaseModel | None) -> Analysis:
    """把模型输出收敛成内部严格类型：丢弃不可用的条目，而不是整批失败。"""
    data = _as_mapping(raw)

    confidence = _js_number(data.get("confidence"))
    if confidence is None:
        confidence = 0.8
    confidence = min(1.0, max(0.0, confidence))

    errors: list[GrammarError] = []
    raw_errors = data.get("errors") or []
    if not isinstance(raw_errors, (list, tuple)):
        raw_errors = []
    for item in raw_errors[:8]:
        entry = _as_mapping(item)
        span = str(entry.get("span") or "").strip()
        if not span:
            continue
        code = str(entry.get("code") or "").strip()
        if code not in TAXONOMY:
            continue
        severity = entry.get("severity")
        if severity not in _SEVERITIES:
            severity = default_severity(code)
        correction = str(entry.get("correction") or span)[:120]
        explain = str(entry.get("explain_zh") or "用法有误")[:120]
        errors.append(
            GrammarError(
                code=code,
                span=span,
                correction=correction,
                explain_zh=explain,
                severity=severity,
                confidence=confidence,
            )
        )
    return Analysis(errors=errors, confidence=confidence)


def validate_spans(text: str, analysis: Analysis) -> Analysis:
    """回验 span：原文里找不到的丢弃；重复的 (位置, code) 只留一条。

    模型输出的 start/end 不可信——这里按 `text.find(span)` 重新定位，
    同一个 span 在一句里出现多次时按第一次出现的位置算（TS 版同语义）。
    """
    source = text or ""
    seen: set[tuple[int, int, str]] = set()
    errors: list[GrammarError] = []
    for error in analysis.errors:
        span = (error.span or "").strip()
        if not span:
            continue
        start = source.find(span)
        if start < 0:
            continue
        key = (start, start + len(span), error.code)
        if key in seen:
            continue
        seen.add(key)
        severity = error.severity if error.severity in _SEVERITIES else default_severity(error.code)
        errors.append(error.model_copy(update={"severity": severity}))
    return Analysis(errors=errors, confidence=analysis.confidence)


# ---------------------------------------------------------------- LLM 入口


async def analyze(text: str, llm) -> tuple[Analysis, str]:
    """纠错主入口，返回 `(analysis, provider)`；失败 / mock 时用规则兜底。"""
    if getattr(llm, "mock", False):
        return rule_analyze(text), "rule-based"
    try:
        raw = await llm.json(
            system=SYSTEM,
            user=f"原文：{text}",
            schema=AnalysisSchema,
            max_tokens=700,
        )
        cleaned = validate_spans(text, normalize_analysis(raw))
        log.info("analyst.done errors=%d confidence=%.2f", len(cleaned.errors), cleaned.confidence)
        provider = str(getattr(llm, "name", "") or "unknown")
        return cleaned, provider
    except Exception as exc:  # noqa: BLE001 - 纠错失败不能拖垮对话
        log.warning("analyst.failed，改用规则兜底: %s", exc)
        return rule_analyze(text), "rule-based"


# ---------------------------------------------------------------- 离线规则版
# 仅供 mock 模式 / 模型失败时跑通链路与评估管线，不代表模型能力。

PAST_PARTICIPLE: dict[str, str] = {
    "went": "gone",
    "did": "done",
    "saw": "seen",
    "took": "taken",
    "made": "made",
    "got": "gotten",
    "came": "come",
    "spoke": "spoken",
    "wrote": "written",
    "ate": "eaten",
    "gave": "given",
}

THIRD_PERSON: dict[str, str] = {
    "go": "goes",
    "do": "does",
    "have": "has",
    "make": "makes",
    "take": "takes",
    "like": "likes",
    "want": "wants",
    "need": "needs",
    "work": "works",
    "live": "lives",
}

BAD_PARTICIPLES = list(PAST_PARTICIPLE)
STATIVE = ["know", "knows", "like", "likes", "want", "wants", "need", "needs", "believe", "understand"]
MISSPELL: dict[str, str] = {
    "recieve": "receive",
    "seperate": "separate",
    "definately": "definitely",
    "enviroment": "environment",
    "goverment": "government",
}

_PERF_RE = re.compile(rf"\b(has|have)\s+({'|'.join(BAD_PARTICIPLES)})\b", re.IGNORECASE)
_STATIVE_RE = re.compile(rf"\b(am|is|are)\s+({'|'.join(STATIVE)})\b", re.IGNORECASE)
_AGREE_RE = re.compile(r"\b(he|she|it)\s+(go|do|have|make|take|like|want|need|work|live)\b", re.IGNORECASE)
_A_VOWEL_RE = re.compile(r"\ba\s+[aeiou]\w+", re.IGNORECASE)
_AN_CONSONANT_RE = re.compile(r"\ban\s+[bcdfgjklmnpqrstvwxyz]\w+", re.IGNORECASE)
_IN_DAY_RE = re.compile(
    r"\bin\s+(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)\b", re.IGNORECASE
)
_MORE_COMPARATIVE_RE = re.compile(r"\bmore\s+(better|worse|easier|bigger|faster|cheaper)\b", re.IGNORECASE)
_MISSPELL_RES = [(re.compile(rf"\b{bad}\b", re.IGNORECASE), bad, good) for bad, good in MISSPELL.items()]

_RULE_CONFIDENCE = 0.9


def rule_analyze(text: str) -> Analysis:
    """离线规则版纠错：只覆盖几条最典型的错误，用于跑通链路。"""
    source = text or ""
    errors: list[GrammarError] = []

    def push(match: re.Match[str], code: str, correction: str, explain: str, severity: str = "medium") -> None:
        errors.append(
            GrammarError(
                code=code,
                span=match.group(0),
                correction=correction,
                explain_zh=explain,
                severity=severity,
                confidence=_RULE_CONFIDENCE,
            )
        )

    match = _PERF_RE.search(source)
    if match:
        fixed = f"{match.group(1)} {PAST_PARTICIPLE.get(match.group(2).lower(), match.group(2))}"
        push(match, "tense.present_perfect", fixed, "现在完成时要用过去分词", "high")

    match = _STATIVE_RE.search(source)
    if match:
        push(match, "tense.present_continuous", match.group(2), "状态动词一般不用进行时", "high")

    match = _AGREE_RE.search(source)
    if match:
        fixed = f"{match.group(1)} {THIRD_PERSON.get(match.group(2).lower(), match.group(2) + 's')}"
        push(match, "agreement.subject_verb", fixed, "第三人称单数动词要加 -s", "high")

    match = _A_VOWEL_RE.search(source)
    if match:
        push(match, "article.a_an_the", re.sub(r"\ba\b", "an", match.group(0), count=1, flags=re.IGNORECASE), "元音音素前用 an")

    match = _AN_CONSONANT_RE.search(source)
    if match:
        push(match, "article.a_an_the", re.sub(r"\ban\b", "a", match.group(0), count=1, flags=re.IGNORECASE), "辅音音素前用 a")

    match = _IN_DAY_RE.search(source)
    if match:
        push(match, "prep.time", re.sub(r"\bin\b", "on", match.group(0), count=1, flags=re.IGNORECASE), "具体某天用 on")

    match = _MORE_COMPARATIVE_RE.search(source)
    if match:
        push(match, "word_form", match.group(1), "比较级不能叠加 more")

    for regex, _bad, good in _MISSPELL_RES:
        match = regex.search(source)
        if match:
            push(match, "spelling", good, "拼写错误", "low")

    return Analysis(errors=errors[:5], confidence=_RULE_CONFIDENCE)

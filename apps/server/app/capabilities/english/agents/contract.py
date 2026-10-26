"""学习契约：学生在「要求窗口」里提的偏好。

移植自 `.tmp/etutor-src/api/src/agents/contract.ts`。关键在于**服务端要做可行性校验**——
学生说「多用这 8 个词」，模型只能硬塞，写出来一定不自然；契约层负责拦截这种要求，
并把「你的要求我改成了这样，原因是……」作为 warnings 返回给前端（不是错误）。
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .taxonomy import ERROR_CODES

# CEFR 阶梯：难度偏移只能在这个阶梯内移动
LADDER: tuple[str, ...] = ("A2", "B1", "B2", "C1")

INTENSITIES: tuple[str, ...] = ("light", "medium", "strict")


@dataclass
class Contract:
    """学生偏好契约（对应 TS 的 ContractSchema）。"""

    must_use_words: list[str] = field(default_factory=list)
    grammar_focus: list[str] = field(default_factory=list)
    correction_intensity: str = "medium"
    difficulty_delta: int = 0
    max_reply_words: int = 90


DEFAULT_CONTRACT = Contract()


# ---------------------------------------------------------------- 内部校验


def _is_int(value: object) -> bool:
    """严格整数：bool 是 int 的子类，这里要排除。"""
    return isinstance(value, int) and not isinstance(value, bool)


def _str_list(value: object, *, item_min: int = 0, item_max: int, max_items: int) -> list[str] | None:
    """校验 `string[]` 字段：不合法返回 None（整体回退默认值，与 zod 一致）。"""
    if not isinstance(value, list) or len(value) > max_items:
        return None
    out: list[str] = []
    for item in value:
        if not isinstance(item, str) or len(item) < item_min or len(item) > item_max:
            return None
        out.append(item)
    return out


def _parse(payload: dict | None) -> Contract | None:
    """按 ContractSchema 校验；任何一项不合法都返回 None（整份回退默认值）。"""
    if payload is None:
        payload = {}
    if not isinstance(payload, dict):
        return None

    words = _str_list(payload.get("must_use_words", []), item_min=2, item_max=40, max_items=6)
    if words is None:
        return None
    focus = _str_list(payload.get("grammar_focus", []), item_min=0, item_max=60, max_items=5)
    if focus is None:
        return None

    intensity = payload.get("correction_intensity", "medium")
    if intensity not in INTENSITIES:
        return None

    delta = payload.get("difficulty_delta", 0)
    if not _is_int(delta) or delta < -1 or delta > 1:
        return None

    max_words = payload.get("max_reply_words", 90)
    if not _is_int(max_words) or max_words < 40 or max_words > 160:
        return None

    return Contract(
        must_use_words=words,
        grammar_focus=focus,
        correction_intensity=intensity,
        difficulty_delta=delta,
        max_reply_words=max_words,
    )


# ---------------------------------------------------------------- 公开接口


def apply_delta(cefr: str, delta: int) -> tuple[str, bool]:
    """难度偏移：只能在阶梯内移动，越界就停住并提示。

    返回 `(cefr, clamped)`；cefr 不在阶梯内时原样返回、不算越界（照搬 TS）。
    """
    try:
        index = LADDER.index(cefr)
    except ValueError:
        return cefr, False
    if not _is_int(delta):
        try:
            delta = int(delta)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            delta = 0
    target = index + int(delta)
    next_index = min(len(LADDER) - 1, max(0, target))
    return LADDER[next_index], next_index != target


def normalize_contract(payload: dict | None) -> tuple[Contract, list[str]]:
    """校验并归一化。返回 warnings 给前端展示——不是错误，是「我替你改成这样了」。"""
    contract = _parse(payload)
    if contract is None:
        # 返回默认值的独立副本，避免调用方改坏模块级常量
        return Contract(), ["参数不合法，已回退到默认设置"]

    warnings: list[str] = []
    if len(contract.must_use_words) > 3:
        warnings.append("一次最多自然复用 3 个词，已保留前 3 个")
        contract.must_use_words = contract.must_use_words[:3]

    unknown = [g for g in contract.grammar_focus if g not in ERROR_CODES]
    if unknown:
        warnings.append(f"忽略了无法识别的语法点：{', '.join(unknown)}")
        contract.grammar_focus = [g for g in contract.grammar_focus if g in ERROR_CODES]

    return contract, warnings


def allowed_severity(intensity: str) -> list[str]:
    """纠错强度直接决定报哪些错：轻=只报硬错，严=全报。"""
    if intensity == "light":
        return ["high"]
    if intensity == "strict":
        return ["low", "medium", "high"]
    return ["high", "medium"]


def severity_allowed(intensity: str, severity: str) -> bool:
    return severity in allowed_severity(intensity)


def contract_hints(c: Contract) -> str:
    """契约里学生点名要练的语法点，直接并进回流提示。"""
    parts: list[str] = []
    if c.must_use_words:
        parts.append(f"naturally use: {', '.join(c.must_use_words)}")
    if c.grammar_focus:
        parts.append(f"the learner asked to practise: {', '.join(c.grammar_focus)}")
    if not parts:
        return ""
    return f"Learner request — {'; '.join(parts)}. Work them in only where the scene allows; never force them."

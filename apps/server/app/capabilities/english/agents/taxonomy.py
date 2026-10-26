"""闭合错误分类。模型只能从这里选，不能自由生成——

否则一年后会攒出几百个近似重复的标签，无法聚合。

移植自 `.tmp/etutor-src/api/src/agents/taxonomy.ts`：
- `TAXONOMY` 是 19 类闭合错误码 → 中文名（严格照搬，不增不减）；
- TS 版每个错误码还带一个默认 severity，这里放在 `DEFAULT_SEVERITY`，
  用于归一化模型输出时兜底（模型经常漏 severity）。
"""
from __future__ import annotations

# 19 类闭合错误码 → 中文名
TAXONOMY: dict[str, str] = {
    "tense.present_simple": "一般现在时",
    "tense.present_continuous": "现在进行时",
    "tense.past_simple": "一般过去时",
    "tense.present_perfect": "现在完成时",
    "tense.past_perfect": "过去完成时",
    "tense.future": "将来时",
    "agreement.subject_verb": "主谓一致",
    "article.a_an_the": "冠词",
    "prep.time": "时间介词",
    "prep.place": "地点介词",
    "prep.other": "介词搭配",
    "word_order": "语序",
    "word_form": "词形变化",
    "collocation": "固定搭配",
    "lexical_choice": "用词选择",
    "spelling": "拼写",
    "punctuation": "标点",
    "register": "语域（正式度）",
    "other": "其他",
}

# 闭合枚举（顺序与 TAXONOMY 一致；tuple 防误改）
ERROR_CODES: tuple[str, ...] = tuple(TAXONOMY)

# 每条错误码的默认严重度（来自 taxonomy.ts 的 severity 字段）
DEFAULT_SEVERITY: dict[str, str] = {
    "tense.present_simple": "medium",
    "tense.present_continuous": "medium",
    "tense.past_simple": "high",
    "tense.present_perfect": "high",
    "tense.past_perfect": "high",
    "tense.future": "medium",
    "agreement.subject_verb": "high",
    "article.a_an_the": "medium",
    "prep.time": "medium",
    "prep.place": "medium",
    "prep.other": "medium",
    "word_order": "medium",
    "word_form": "high",
    "collocation": "low",
    "lexical_choice": "low",
    "spelling": "low",
    "punctuation": "low",
    "register": "low",
    "other": "low",
}

SEVERITIES: tuple[str, ...] = ("low", "medium", "high")


def code_label(code: str) -> str:
    """错误码的中文名；未知 code 原样返回（TS 版同语义）。"""
    return TAXONOMY.get(code, code)


def default_severity(code: str) -> str:
    """错误码的默认严重度；未知 code 按 medium 处理。"""
    return DEFAULT_SEVERITY.get(code, "medium")

"""错误档案聚合层：出现几次、最近变多还是变少、有没有改好。

单个错误没有价值，模式才有。语义照搬 etutor-cn `api/src/agents/errors.ts`：

- 写路径 `record_analysis` 一条消息只算一次（同一句里 3 个时态错不该记 3 次）；
- 「已改正」= 标记过 resolved，或最近 5 次分析都没再犯（读路径 `refresh_resolved` 判定）；
- 趋势按「近 7 天 vs 前 7 天」：prev=0 且有新增 → new；只剩旧数据 → down。
"""
from __future__ import annotations

from typing import Any

from ..store import execute, iso_ago, new_id, now_iso, q

try:  # taxonomy 由 agents-core 提供；并行开发期缺文件也不影响本模块单独使用
    from .taxonomy import code_label
except ImportError:  # pragma: no cover - 仅在模块独立存在时触发

    def code_label(code: str) -> str:  # type: ignore[misc]
        return code


Trend = str  # 'up' | 'down' | 'flat' | 'new'

# 把代码翻成「给模型看的行为提示」，而不是语法术语
NUDGE: dict[str, str] = {
    "tense.present_perfect": "create a situation comparing past and present results",
    "tense.past_simple": "ask for a short account of what happened",
    "agreement.subject_verb": "keep the subject clearly third-person singular",
    "article.a_an_the": "talk about specific objects rather than general ones",
    "prep.time": "mention days, dates and times",
    "word_form": "ask about completed actions",
}


# ---------------------------------------------------------------- 纯判定


def trend_of(recent: int, prev: int) -> Trend:
    """近 7 天 vs 前 7 天。prev=0 且有新增 → new；只剩旧数据 → down。"""
    if recent > 0 and prev == 0:
        return "new"
    if recent == 0 and prev > 0:
        return "down"
    if recent > prev:
        return "up"
    if recent < prev:
        return "down"
    return "flat"


def is_improved(resolved_at: str | None, clean_runs: int) -> bool:
    """已改正 = 标记过 resolved，或最近 5 次分析都没再犯。"""
    return resolved_at is not None or clean_runs >= 5


# ---------------------------------------------------------------- 写路径


def record_analysis(user_id: int, message_id: str, codes: list[str]) -> None:
    """记录一次纠错分析：先落 runs，再按 code 聚合到 patterns（codes 先去重）。"""
    unique: list[str] = []
    seen: set[str] = set()
    for code in codes or []:
        code = str(code).strip()
        if not code or code in seen:
            continue
        seen.add(code)
        unique.append(code)

    now = now_iso()
    execute(
        "INSERT INTO english_analysis_runs (id, user_id, message_id, error_count, created_at) "
        "VALUES (:id, :user_id, :message_id, :error_count, :created_at)",
        id=new_id(),
        user_id=user_id,
        message_id=message_id,
        error_count=len(unique),
        created_at=now,
    )
    for code in unique:
        execute(
            "INSERT INTO english_error_patterns (user_id, code, occurrences, first_seen, last_seen) "
            "VALUES (:user_id, :code, 1, :now, :now) "
            "ON CONFLICT (user_id, code) DO UPDATE SET "
            "occurrences = english_error_patterns.occurrences + 1, "
            "last_seen = excluded.last_seen",
            user_id=user_id,
            code=code,
            now=now,
        )


def refresh_resolved(user_id: int) -> None:
    """判定「已改正」：某个模式最后一次出现之后，该用户又做了 ≥5 次分析且没再犯。

    只在读路径跑，写路径不受影响。
    """
    execute(
        "UPDATE english_error_patterns SET resolved_at = :now "
        "WHERE user_id = :user_id AND resolved_at IS NULL "
        "AND (SELECT count(*) FROM english_analysis_runs r "
        "     WHERE r.user_id = :user_id "
        "       AND r.created_at > english_error_patterns.last_seen) >= 5",
        user_id=user_id,
        now=now_iso(),
    )


# ---------------------------------------------------------------- 读路径


def list_patterns(user_id: int) -> list[dict[str, Any]]:
    """错误档案（按累计次数降序，最多 30 条）。"""
    rows = q(
        "SELECT p.code, p.occurrences, p.resolved_at, "
        "  (SELECT count(*) FROM english_error_events e "
        "    WHERE e.user_id = p.user_id AND e.code = p.code AND e.created_at > :week_ago) AS recent7, "
        "  (SELECT count(*) FROM english_error_events e "
        "    WHERE e.user_id = p.user_id AND e.code = p.code "
        "      AND e.created_at <= :week_ago AND e.created_at > :two_weeks_ago) AS prev7, "
        "  (SELECT count(*) FROM english_analysis_runs r "
        "    WHERE r.user_id = p.user_id AND r.created_at > p.last_seen) AS clean_runs "
        "FROM english_error_patterns p WHERE p.user_id = :user_id "
        "ORDER BY p.occurrences DESC LIMIT 30",
        user_id=user_id,
        week_ago=iso_ago(days=7),
        two_weeks_ago=iso_ago(days=14),
    )
    items: list[dict[str, Any]] = []
    for row in rows:
        recent7 = int(row.get("recent7") or 0)
        prev7 = int(row.get("prev7") or 0)
        clean_runs = int(row.get("clean_runs") or 0)
        resolved_at = row.get("resolved_at")
        items.append(
            {
                "code": row.get("code"),
                "label": code_label(str(row.get("code") or "")),
                "occurrences": int(row.get("occurrences") or 0),
                "recent7": recent7,
                "prev7": prev7,
                "trend": trend_of(recent7, prev7),
                "improved": is_improved(resolved_at, clean_runs),
                "evidence": [],
            }
        )
    return items


def weak_codes(user_id: int, limit: int = 3) -> list[str]:
    """回流：还没改好的 Top N，喂给角色扮演当「该造的语境」。"""
    rows = q(
        "SELECT code FROM english_error_patterns "
        "WHERE user_id = :user_id AND resolved_at IS NULL AND occurrences >= 2 "
        "ORDER BY occurrences DESC LIMIT :limit",
        user_id=user_id,
        limit=max(0, int(limit)),
    )
    return [str(row["code"]) for row in rows]


def weak_prompt_hints(codes: list[str]) -> str:
    """把错误码翻成给模型看的行为提示（不暴露语法术语）。"""
    hints = [NUDGE[code] for code in codes if code in NUDGE]
    if not hints:
        return ""
    return (
        "The learner still struggles with these structures. Where the scene allows, "
        f"{'; '.join(hints)}. Do not point this out explicitly."
    )

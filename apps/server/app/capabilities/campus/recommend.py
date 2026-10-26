"""个性化排序与推荐理由。

只用可解释的信号：兴趣标签命中、专业/院系命中、年级匹配、时间新旧、截止临近。
每一条加分都要能说清「为什么推荐给你」，说不清就不加分——
推荐理由会直接展示给用户，编一个理由比不给理由更糟。
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

from .classify import CATEGORY_LABELS

# 类别的基础权重：考试类最需要及时看见，公示类最不着急
CATEGORY_BASE: dict[str, float] = {
    "exam": 1.5,
    "contest": 1.3,
    "lecture": 0.9,
    "activity": 1.0,
    "policy": 0.6,
    "other": 0.5,
}

# 用户「目标」到类别的映射：填了「考研」就更该看到考试与讲座
GOAL_CATEGORY: dict[str, set[str]] = {
    "考研": {"exam", "lecture"},
    "保研": {"exam", "policy", "contest"},
    "就业": {"policy", "activity"},
    "实习": {"policy", "activity"},
    "竞赛": {"contest"},
    "比赛": {"contest"},
    "出国": {"exam", "policy"},
    "考公": {"exam", "policy"},
    "科研": {"lecture", "contest"},
}


def category_label(category: str) -> str:
    return CATEGORY_LABELS.get(category, "其他")


def parse_day(value: str | None) -> date | None:
    if not value:
        return None
    text = str(value)[:10]
    for fmt in ("%Y-%m-%d", "%Y/%m/%d"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def _tags(item: dict[str, Any]) -> list[str]:
    raw = item.get("tags_json") or "[]"
    import json

    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        return []
    return [str(tag) for tag in value] if isinstance(value, list) else []


def score_item(
    item: dict[str, Any],
    profile: dict[str, Any],
    *,
    today: date | None = None,
) -> tuple[float, list[str]]:
    """返回 (分数, 理由列表)。理由按重要程度排列，最多三条。"""
    now = today or date.today()
    score = CATEGORY_BASE.get(item.get("category") or "other", 0.5)
    reasons: list[str] = []

    interests = [tag.lower() for tag in profile.get("interests") or []]
    goals = [tag.lower() for tag in profile.get("goals") or []]
    haystack = f"{item.get('title') or ''} {(item.get('summary') or '')[:400]}".lower()

    # 1) 兴趣命中：用条目标签与标题双向匹配
    matched: list[str] = []
    for tag in _tags(item):
        if any(tag.lower() in interest or interest in tag.lower() for interest in interests):
            if tag not in matched:
                matched.append(tag)
    for interest in interests:
        if interest and interest in haystack and interest not in matched:
            matched.append(interest)
    if matched:
        score += min(3.0, 1.2 * len(matched))
        reasons.append("与你的兴趣「" + "、".join(matched[:3]) + "」相关")

    # 2) 目标 → 类别
    category = item.get("category") or "other"
    goal_hit = [goal for goal in goals if category in GOAL_CATEGORY.get(goal, set())]
    if goal_hit:
        score += 1.2
        reasons.append(f"你关注「{goal_hit[0]}」，这条属于{category_label(category)}")

    # 3) 专业 / 院系命中：标题里出现专业或院系
    for field, label in (("major", "专业"), ("department", "院系")):
        value = (profile.get(field) or "").strip()
        if value and value in haystack:
            score += 1.5
            reasons.append(f"面向{label}「{value}」")
            break

    # 4) 年级匹配：面向对象或标题里点了年级
    grade = (profile.get("grade") or "").strip()
    if grade:
        blob = f"{item.get('audience') or ''} {item.get('title') or ''}"
        if grade in blob or any(key in blob for key in _grade_variants(grade)):
            score += 1.0
            reasons.append(f"与你所在的{grade}相关")

    # 5) 新鲜度
    published = parse_day(item.get("published_at"))
    if published:
        age = (now - published).days
        if 0 <= age <= 7:
            score += 1.2
            reasons.append("最近一周发布")
        elif 0 <= age <= 30:
            score += 0.6
        elif age > 180:
            score -= 0.8          # 半年前的旧通知降权，但仍可检索到

    # 6) 截止临近：对「还能不能报」这件事，截止日期比发布日期更重要
    deadline = parse_day(item.get("deadline"))
    if deadline:
        days_left = (deadline - now).days
        if days_left < 0:
            score -= 1.5
        elif days_left <= 7:
            score += 2.5
            reasons.append(f"报名 {deadline.isoformat()} 截止，只剩 {days_left} 天")
        elif days_left <= 14:
            score += 1.5
            reasons.append(f"{deadline.isoformat()} 截止")
        elif days_left <= 30:
            score += 0.6

    return round(score, 3), reasons[:3]


def _grade_variants(grade: str) -> list[str]:
    mapping = {
        "大一": ["一年级", "2025级", "2025 级"],
        "大二": ["二年级", "2024级", "2024 级"],
        "大三": ["三年级", "2023级", "2023 级"],
        "大四": ["四年级", "2022级", "2022 级", "应届"],
    }
    return mapping.get(grade, [])


def rank(
    rows: list[dict[str, Any]],
    profile: dict[str, Any],
    *,
    limit: int = 20,
    today: date | None = None,
) -> list[tuple[dict[str, Any], str]]:
    """按个性化分数排序，返回 (条目, 理由文案)。理由可为空字符串。"""
    scored: list[tuple[float, dict[str, Any], list[str]]] = []
    for row in rows:
        value, reasons = score_item(row, profile, today=today)
        scored.append((value, row, reasons))
    scored.sort(key=lambda triple: triple[0], reverse=True)

    result: list[tuple[dict[str, Any], str]] = []
    for value, row, reasons in scored[:limit]:
        result.append((row, "；".join(reasons)))
    return result


def upcoming(rows: list[dict[str, Any]], days: int = 14, today: date | None = None) -> list[dict]:
    """未来 N 天内截止的条目，按截止日升序。"""
    now = today or date.today()
    horizon = now + timedelta(days=days)
    hits: list[tuple[date, dict]] = []
    for row in rows:
        deadline = parse_day(row.get("deadline"))
        if deadline and now <= deadline <= horizon:
            hits.append((deadline, row))
    hits.sort(key=lambda pair: pair[0])
    return [row for _, row in hits]

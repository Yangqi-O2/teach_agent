"""用户画像的读写与归一化。

为什么单独一层
--------------
画像会被多个地方读（校园雷达的推荐、答疑的举例风格、后续的记忆卡素材），
但写入口只应该有一个。这里把「怎么解析、怎么归一化、怎么给模型看」收敛起来，
避免每个能力各写一套 `profile.get("school")` 然后各自解析失败。

存储细节：`interests_json` / `goals_json` 存 JSON 数组字符串，读的时候统一解析成 list，
坏数据（历史遗留、手工改库）一律降级成空列表，不抛异常。
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from typing import Any, Iterable

from sqlmodel import Session

from ..models import UserProfile

log = logging.getLogger(__name__)

# 校名 → 归一化 key。抓取源按 key 匹配，用户填「郑大」「郑州大学」都能落到 zzu。
SCHOOL_ALIASES: dict[str, str] = {
    "郑州大学": "zzu",
    "郑大": "zzu",
    "zzu": "zzu",
    "河南大学": "henu",
    "河大": "henu",
    "henu": "henu",
    "清华大学": "thu",
    "thu": "thu",
    "北京大学": "pku",
    "北大": "pku",
    "pku": "pku",
    "复旦大学": "fudan",
    "复旦": "fudan",
    "fudan": "fudan",
}

# 年级与学段关键词：用于判断一条通知「是不是面向你」
GRADE_KEYWORDS: dict[str, list[str]] = {
    "大一": ["大一", "2025级", "2025 级", "一年级"],
    "大二": ["大二", "2024级", "2024 级", "二年级"],
    "大三": ["大三", "2023级", "2023 级", "三年级"],
    "大四": ["大四", "2022级", "2022 级", "四年级", "应届"],
    "研一": ["研一", "硕士一年级"],
    "研二": ["研二", "硕士二年级"],
    "研三": ["研三", "硕士三年级", "毕业班"],
}

_MAX_TAG = 24
_MAX_TAGS = 12


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def normalize_school(name: str | None) -> tuple[str, str]:
    """返回 (展示名, 归一化 key)。未知学校保留原文，key 用安全的 slug。"""
    text = (name or "").strip()
    if not text:
        return "", ""
    key = SCHOOL_ALIASES.get(text) or SCHOOL_ALIASES.get(text.lower())
    if key:
        # 展示名统一成标准写法（用户填「郑大」也显示「郑州大学」）
        display = next((k for k, v in SCHOOL_ALIASES.items() if v == key and len(k) >= 3), text)
        return display, key
    slug = re.sub(r"[^a-z0-9]+", "", text.lower())[:24]
    return text, slug or "unknown"


def _parse_tags(raw: Any) -> list[str]:
    """接受 JSON 字符串、list、或逗号分隔字符串；去重、去空、限长。"""
    items: Iterable[Any]
    if raw is None or raw == "":
        return []
    if isinstance(raw, str):
        text = raw.strip()
        if not text:
            return []
        if text.startswith("["):
            try:
                parsed = json.loads(text)
            except json.JSONDecodeError:
                parsed = None
            items = parsed if isinstance(parsed, list) else re.split(r"[,，、;；\s]+", text)
        else:
            items = re.split(r"[,，、;；\s]+", text)
    elif isinstance(raw, (list, tuple, set)):
        items = raw
    else:
        return []

    result: list[str] = []
    seen: set[str] = set()
    for item in items:
        tag = str(item).strip()[:_MAX_TAG]
        if not tag or tag in seen:
            continue
        seen.add(tag)
        result.append(tag)
        if len(result) >= _MAX_TAGS:
            break
    return result


def _loads(raw: str | None) -> list[str]:
    if not raw:
        return []
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        return []
    return [str(item) for item in value] if isinstance(value, list) else []


def read(db: Session, user_id: int) -> UserProfile | None:
    return db.get(UserProfile, user_id)


def as_dict(profile: UserProfile | None) -> dict[str, Any]:
    """给 API / 模板用的纯字典视图。没有画像时返回空画像而不是 None，前端少一层判空。"""
    if profile is None:
        return {
            "school": "",
            "school_key": "",
            "grade": "",
            "department": "",
            "major": "",
            "class_name": "",
            "interests": [],
            "goals": [],
            "onboarded": False,
            "completeness": 0,
            "updated_at": None,
        }
    data = {
        "school": profile.school,
        "school_key": profile.school_key,
        "grade": profile.grade,
        "department": profile.department,
        "major": profile.major,
        "class_name": profile.class_name,
        "interests": _loads(profile.interests_json),
        "goals": _loads(profile.goals_json),
        "onboarded": profile.onboarded,
        "updated_at": profile.updated_at.isoformat() if profile.updated_at else None,
    }
    data["completeness"] = completeness(data)
    return data


def completeness(data: dict[str, Any]) -> int:
    """0–100，用于提示「资料填得越全，推荐越准」。学校与年级权重最高。"""
    weights = {"school": 30, "grade": 20, "department": 15, "major": 15, "interests": 20}
    score = 0
    for key, weight in weights.items():
        value = data.get(key)
        if value if isinstance(value, str) else bool(value):
            score += weight
    return score


def upsert(db: Session, user_id: int, payload: dict[str, Any]) -> UserProfile:
    """局部更新：只改 payload 里出现的字段，没传的保持原值。"""
    profile = db.get(UserProfile, user_id) or UserProfile(user_id=user_id)

    if "school" in payload:
        display, key = normalize_school(payload.get("school"))
        profile.school = display
        profile.school_key = key
    for field in ("grade", "department", "major", "class_name"):
        if field in payload:
            setattr(profile, field, str(payload.get(field) or "").strip()[:60])
    if "interests" in payload:
        profile.interests_json = json.dumps(_parse_tags(payload.get("interests")), ensure_ascii=False)
    if "goals" in payload:
        profile.goals_json = json.dumps(_parse_tags(payload.get("goals")), ensure_ascii=False)
    if "onboarded" in payload:
        profile.onboarded = bool(payload.get("onboarded"))
    elif not profile.onboarded:
        # 只要填了学校就算完成引导，避免用户被反复拦在引导页
        profile.onboarded = bool(profile.school)

    profile.updated_at = utcnow()
    db.add(profile)
    db.commit()
    db.refresh(profile)
    return profile


def prompt_block(data: dict[str, Any]) -> str:
    """给模型的画像描述。空字段直接省略，不要用「未填写」占位污染上下文。"""
    lines: list[str] = []
    if data.get("school"):
        lines.append(f"学校：{data['school']}")
    if data.get("department"):
        lines.append(f"院系：{data['department']}")
    if data.get("major"):
        lines.append(f"专业：{data['major']}")
    if data.get("grade"):
        lines.append(f"年级：{data['grade']}")
    if data.get("class_name"):
        lines.append(f"班级：{data['class_name']}")
    if data.get("interests"):
        lines.append("兴趣：" + "、".join(data["interests"]))
    if data.get("goals"):
        lines.append("目标：" + "、".join(data["goals"]))
    return "\n".join(lines)


def grade_keywords(grade: str) -> list[str]:
    """把用户填的年级展开成可用于匹配的若干关键词。"""
    text = (grade or "").strip()
    if not text:
        return []
    keywords: list[str] = [text]
    for label, words in GRADE_KEYWORDS.items():
        if text == label or text in words or any(word in text for word in words):
            keywords.extend(words)
            keywords.append(label)
    # 2023 / 2023级 / 2023 级 三种写法都算
    match = re.search(r"(19|20)\d{2}", text)
    if match:
        year = match.group(0)
        keywords.extend([year, f"{year}级", f"{year} 级"])
    return list(dict.fromkeys(k for k in keywords if k))

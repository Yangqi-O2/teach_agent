"""生词复习排程（FSRS-lite）。

行为完全照搬 etutor-cn 的 `api/src/schedule.ts`：

- 评分 1（忘了）走 lapse 分支：reps 归零、间隔回到 1 天、稳定度打折、难度上调；
- 评分 2~4 走成功分支：前两次用固定间隔（1/3、2/5），之后按 ease 与评分系数连乘；
- 间隔钳制在 1~180 天；难度钳制在 1~10；
- 稳定度直接等于间隔天数（“接口稳定，后续换真 FSRS 只改这个文件”）。

时间统一用 UTC ISO-8601 字符串（与 `store.now_iso()` 同格式），因此可以直接在
SQLite 里做字符串比较排序。
"""
from __future__ import annotations

import math
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone

SECONDS_PER_DAY = 86_400.0


@dataclass
class Card:
    """一张复习卡片的可序列化状态。"""

    stability: float = 0.0
    difficulty: float = 5.0
    reps: int = 0
    lapses: int = 0
    interval_days: int = 0
    last_review_at: str | None = None
    next_review_at: str | None = None


EMPTY = Card()

# 评分：1 忘了 / 2 勉强 / 3 记得 / 4 太简单
RATINGS = (1, 2, 3, 4)


def _clamp(value: float, low: float, high: float) -> float:
    return min(high, max(low, value))


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc(value: datetime | None) -> datetime:
    """把传入时间统一成 UTC aware datetime；naive 按 UTC 解释。"""
    if value is None:
        return _utcnow()
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _iso(value: datetime) -> str:
    """与 store.now_iso() 完全一致的格式（秒精度、+00:00 后缀）。"""
    return value.astimezone(timezone.utc).isoformat(timespec="seconds")


def parse_iso(value: str | None) -> datetime | None:
    """容错解析 ISO 时间；None/空/坏值返回 None。"""
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _js_round(value: float) -> int:
    """JS 的 Math.round 是 floor(x+0.5)；Python round 是银行家舍入，不能直接用。"""
    return math.floor(value + 0.5)


def schedule(prev: Card, rating: int, now: datetime | None = None) -> Card:
    """按评分推进一张卡片。返回新对象，不修改 prev。"""
    if rating not in RATINGS:
        raise ValueError(f"rating 必须是 1~4：{rating!r}")

    at = _as_utc(now)
    stability = float(prev.stability)
    difficulty = float(prev.difficulty)
    reps = int(prev.reps)
    lapses = int(prev.lapses)
    interval_days = int(prev.interval_days)

    if rating == 1:
        lapses += 1
        reps = 0
        interval_days = 1
        stability = max(0.5, stability * 0.4)
        difficulty = _clamp(difficulty + 0.8, 1.0, 10.0)
    else:
        reps += 1
        ease = 1.3 + ((10.0 - difficulty) / 10.0) * 1.2
        if reps == 1:
            interval_days = 2 if rating == 4 else 1
        elif reps == 2:
            interval_days = 5 if rating == 4 else 3
        else:
            factor = 0.8 if rating == 2 else 1.3 if rating == 4 else 1.0
            interval_days = _js_round(interval_days * ease * factor)
        interval_days = int(_clamp(interval_days, 1, 180))
        stability = float(interval_days)
        difficulty = _clamp(difficulty - (rating - 3) * 0.4, 1.0, 10.0)

    return replace(
        prev,
        stability=stability,
        difficulty=difficulty,
        reps=reps,
        lapses=lapses,
        interval_days=interval_days,
        last_review_at=_iso(at),
        next_review_at=_iso(at + timedelta(days=interval_days)),
    )


def retrievability(c: Card, now: datetime | None = None) -> float:
    """当前记忆可提取概率：exp(ln(0.9) * 已过天数 / 间隔天数)。"""
    last = parse_iso(c.last_review_at)
    if last is None or c.interval_days <= 0:
        return 0.0
    at = _as_utc(now)
    days = (at - last).total_seconds() / SECONDS_PER_DAY
    return float(_clamp(math.exp(math.log(0.9) * (days / c.interval_days)), 0.0, 1.0))


def is_due(c: Card, now: datetime | None = None) -> bool:
    """到期（或从未排程）就该复习。"""
    next_at = parse_iso(c.next_review_at)
    if next_at is None:
        return True
    return next_at <= _as_utc(now)


def card_from_row(row: dict) -> Card:
    """把 `english_vocab_states` 的一行（snake_case）转成 Card；缺列用默认值。"""
    return Card(
        stability=float(row.get("stability") or 0.0),
        difficulty=float(row.get("difficulty") or 5.0),
        reps=int(row.get("reps") or 0),
        lapses=int(row.get("lapses") or 0),
        interval_days=int(row.get("interval_days") or 0),
        last_review_at=(str(row["last_review_at"]) if row.get("last_review_at") else None),
        next_review_at=(str(row["next_review_at"]) if row.get("next_review_at") else None),
    )

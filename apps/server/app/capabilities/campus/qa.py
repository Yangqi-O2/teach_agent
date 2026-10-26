"""校园雷达 · 个性化问答。

两条路径
--------
- 配了模型：把「用户画像 + 候选条目」喂给模型，要求它只能基于这些条目作答。
- 没配模型：走规则摘要。这不是降级到不可用——校园通知本来就是结构化信息，
  按类别列出来 + 标截止日期，没有模型也能看清楚。

无论哪条路径，返回的条目都带原始链接，用户可以自己核对。
"""
from __future__ import annotations

import logging
from datetime import date
from typing import Any

from ...core.errors import ApiError

log = logging.getLogger(__name__)

CATEGORY_ORDER = ["exam", "contest", "lecture", "activity", "policy", "other"]

SYSTEM_PROMPT = """你是校园信息助理，服务对象是本校学生。

硬性规则：
1. 只能使用用户消息里给出的【通知列表】作答，不得引入列表之外的任何活动、比赛或政策。
2. 每提到一条通知，必须标注它的编号，例如 [3]。
3. 列表里没有的内容，直接说「已抓取的通知里没有相关信息」，不要用常识补充。
4. 不臆测截止日期；只有列表里写了截止日期才能提。
5. 回答用简体中文，先说结论，再列细节。不要写客套话。"""


def _profile_line(profile: dict[str, Any]) -> str:
    from ...core.profile import prompt_block

    block = prompt_block(profile)
    if not block:
        return "学生画像：未填写（按通用情况回答，并提醒他去补全资料）"
    return "学生画像：\n" + block


def _items_block(rows: list[dict[str, Any]], reasons: dict[int, str]) -> str:
    lines: list[str] = []
    for index, row in enumerate(rows, 1):
        bits = [f"[{index}]", row["title"]]
        meta = []
        if row.get("published_at"):
            meta.append(f"发布 {row['published_at']}")
        if row.get("deadline"):
            meta.append(f"截止 {row['deadline']}")
        if row.get("audience"):
            meta.append(f"面向 {row['audience']}")
        if meta:
            bits.append("（" + "，".join(meta) + "）")
        line = "".join(bits)
        if row.get("summary"):
            line += "\n    摘要：" + str(row["summary"])[:180]
        reason = reasons.get(int(row["id"]))
        if reason:
            line += f"\n    与这位学生的相关点：{reason}"
        lines.append(line)
    return "\n".join(lines)


async def answer(
    question: str,
    profile: dict[str, Any],
    rows: list[dict[str, Any]],
    *,
    user_id: int,
    limit: int = 10,
) -> dict[str, Any]:
    """返回 {answer, mode, items, note}。items 是前端要渲染的卡片数据。"""
    from . import recommend

    ranked = recommend.rank(rows, profile, limit=limit)
    picked = [row for row, _ in ranked]
    reasons = {int(row["id"]): reason for row, reason in ranked if reason}

    cards = [
        {
            "id": row["id"],
            "title": row["title"],
            "category": row["category"],
            "category_label": recommend.category_label(row["category"]),
            "published_at": row.get("published_at"),
            "deadline": row.get("deadline"),
            "url": row["url"],
            "reason": reasons.get(int(row["id"]), ""),
        }
        for row in picked
    ]

    if not picked:
        return {
            "answer": "目前还没有抓到任何校园通知。可以让管理员在「校园雷达」页手动更新一次。",
            "mode": "empty",
            "items": [],
            "note": "",
        }

    text = await _llm_answer(question, profile, picked, reasons, user_id=user_id)
    if text:
        return {"answer": text, "mode": "llm", "items": cards, "note": ""}

    return {
        "answer": _rule_answer(question, profile, picked, reasons),
        "mode": "rule",
        "items": cards,
        "note": "未配置模型，这里是按你的画像直接排出来的清单（信息未经过模型总结）。",
    }


async def _llm_answer(
    question: str,
    profile: dict[str, Any],
    rows: list[dict[str, Any]],
    reasons: dict[int, str],
    *,
    user_id: int,
) -> str:
    from ...capabilities.library.llm import try_load_llm

    client = try_load_llm(user_id)
    if client is None:
        return ""
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {
            "role": "user",
            "content": (
                f"今天是 {date.today().isoformat()}。\n\n"
                f"{_profile_line(profile)}\n\n"
                f"【通知列表】\n{_items_block(rows, reasons)}\n\n"
                f"【学生的问题】{question}\n\n"
                "请按要求作答：先用一两句话给结论，再按类别分条列出（每条带编号与截止日期），"
                "最后用一行提醒「最近要抓紧的事」。"
            ),
        },
    ]
    try:
        result = await client.chat(messages, temperature=0.3, max_tokens=1200)
    except ApiError as exc:
        log.info("校园雷达问答降级为规则摘要：%s", exc)
        return ""
    except Exception:  # noqa: BLE001
        log.exception("校园雷达问答调用模型失败，降级为规则摘要")
        return ""
    return (result.get("content") or "").strip()


def _rule_answer(
    question: str,
    profile: dict[str, Any],
    rows: list[dict[str, Any]],
    reasons: dict[int, str],
) -> str:
    from . import recommend

    today = date.today()
    school = profile.get("school") or "你所在的学校"
    lines: list[str] = [f"关于「{question}」，从已抓取的{school}通知里挑了 {len(rows)} 条最相关的：", ""]

    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault(row.get("category") or "other", []).append(row)

    for category in CATEGORY_ORDER:
        group = grouped.get(category)
        if not group:
            continue
        lines.append(f"【{recommend.category_label(category)}】")
        for row in group:
            meta: list[str] = []
            if row.get("published_at"):
                meta.append(f"{row['published_at']} 发布")
            deadline = row.get("deadline")
            if deadline:
                left = (recommend.parse_day(deadline) or today) - today
                suffix = f"，还有 {left.days} 天" if left.days >= 0 else "（已过期）"
                meta.append(f"{deadline} 截止{suffix}")
            head = f"· {row['title']}"
            if meta:
                head += "（" + "，".join(meta) + "）"
            lines.append(head)
            reason = reasons.get(int(row["id"]))
            if reason:
                lines.append(f"    为什么推荐：{reason}")
        lines.append("")

    urgent = recommend.upcoming(rows, days=7, today=today)
    if urgent:
        lines.append("【最近要抓紧】")
        for row in urgent[:3]:
            lines.append(f"· {row['title']} —— {row['deadline']} 截止")
    else:
        lines.append("【最近要抓紧】近 7 天没有临近截止的条目。")

    return "\n".join(lines).strip()

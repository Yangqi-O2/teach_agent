"""导出：``DigestPayload`` → txt / json / md / ics。

格式走 ``EXPORTERS`` 注册表，新增格式只加一个函数 + 注册一行；
``GET /digests/{id}/export?format=...`` 与前端下载链接自动可用。
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from typing import Any, Callable

# —— 导出格式元数据 ——
MEDIA_TYPES: dict[str, str] = {
    "txt": "text/plain; charset=utf-8",
    "json": "application/json; charset=utf-8",
    "md": "text/markdown; charset=utf-8",
    "ics": "text/calendar; charset=utf-8",
}

EXTENSIONS: dict[str, str] = {"txt": "txt", "json": "json", "md": "md", "ics": "ics"}

FORMAT_LABELS: dict[str, str] = {
    "txt": "文本总结",
    "json": "JSON 数据",
    "md": "待办 Markdown",
    "ics": "日程 ICS",
}


def _groups(payload: dict) -> list[dict]:
    groups = payload.get("groups") or []
    return [g for g in groups if isinstance(g, dict)]


def _stats_line(payload: dict) -> str:
    stats = payload.get("stats") or {}
    before = stats.get("before", 0)
    after = stats.get("after", 0)
    dropped = stats.get("dropped", max(0, int(before) - int(after)))
    chunks = stats.get("chunks", 0)
    return f"原始 {before} 条 → 保留 {after} 条（丢弃 {dropped} 条，分块 {chunks}）"


def _header_lines(payload: dict) -> list[str]:
    provider = str(payload.get("provider") or "").strip()
    model = str(payload.get("model") or "").strip()
    model_text = " / ".join(x for x in (provider, model) if x) or "（未记录）"
    return [
        f"群聊简报 · {payload.get('group_name') or '未命名会话'}",
        f"生成时间：{payload.get('created_at') or ''}",
        f"模型：{model_text}",
        f"清洗：{_stats_line(payload)}",
    ]


# ---------- txt：可直接读 / 复制回群 ----------
def export_txt(payload: dict) -> str:
    lines = ["=" * 56, *_header_lines(payload), "=" * 56, ""]
    for group in _groups(payload):
        name = group.get("name") or payload.get("group_name") or "群聊"
        lines.append(f"【{name}】")
        text = str(group.get("structured_text") or "").strip()
        if text:
            lines.append(text)
        else:
            lines.append(str(group.get("one_line") or "").strip())
        schedules = group.get("schedules") or []
        if schedules:
            lines.append("")
            lines.append("待办 / 日程：")
            for item in schedules:
                if not isinstance(item, dict):
                    continue
                box = "[x]" if item.get("done") else "[ ]"
                line = f"- {box} {item.get('title') or '未命名事项'}"
                if item.get("datetime"):
                    line += f"（{item['datetime']}）"
                if item.get("note"):
                    line += f" — {item['note']}"
                lines.append(line)
        lines.append("")
        lines.append("-" * 40)
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


# ---------- json：DigestPayload 原样 ----------
def export_json(payload: dict) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2) + "\n"


# ---------- md：待办 + 日程清单 ----------
def export_md(payload: dict) -> str:
    lines = [f"# 群聊简报 · {payload.get('group_name') or '未命名会话'}", ""]
    lines.extend(f"- {line}" for line in _header_lines(payload)[1:])
    lines.append("")
    for group in _groups(payload):
        name = group.get("name") or payload.get("group_name") or "群聊"
        lines.append(f"## {name}")
        one_line = str(group.get("one_line") or "").strip()
        if one_line:
            lines.extend([f"> {one_line}", ""])

        items = group.get("items") or []
        if items:
            lines.append("### 重要事项")
            lines.extend(f"- {item}" for item in items if str(item).strip())
            lines.append("")

        schedules = group.get("schedules") or []
        lines.append("### 待办 / 日程")
        has_schedule = False
        for item in schedules:
            if not isinstance(item, dict):
                continue
            has_schedule = True
            box = "[x]" if item.get("done") else "[ ]"
            line = f"- {box} **{item.get('title') or '未命名事项'}**"
            if item.get("datetime"):
                line += f"（{item['datetime']}）"
            if item.get("note"):
                line += f" — {item['note']}"
            if item.get("source_sender"):
                line += f"（提出人：{item['source_sender']}）"
            lines.append(line)
        if not has_schedule:
            lines.append("- 本次没有提取到明确的日程 / 待办。")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


# ---------- ics：标准 VCALENDAR ----------
def _ics_escape(text: str) -> str:
    """ICS 文本转义：反斜杠、分号、逗号、换行。"""
    text = str(text or "")
    text = text.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,")
    return text.replace("\r\n", "\n").replace("\r", "\n").replace("\n", "\\n")


def _created_date(payload: dict) -> str:
    created = str(payload.get("created_at") or "")
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", created)
    if m:
        return "".join(m.groups())
    return datetime.now().strftime("%Y%m%d")


def _ics_datetime(value: str, fallback_date: str) -> tuple[str, str]:
    """把 ``2026-10-24T23:59`` 之类转成 ICS 日期时间。

    返回 ``(参数部分, 值)``，例如 ``(";VALUE=DATE-TIME", "20261024T235900")``。
    """
    value = (value or "").strip()
    if not value:
        return ";VALUE=DATE", fallback_date
    # 完整日期时间
    m = re.match(r"(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})[T ](\d{1,2}):(\d{2})", value)
    if m:
        y, mo, d, h, mi = m.groups()
        return ";VALUE=DATE-TIME", f"{y}{int(mo):02d}{int(d):02d}T{int(h):02d}{mi}00"
    # 只有日期
    m = re.match(r"(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})", value)
    if m:
        y, mo, d = m.groups()
        return ";VALUE=DATE", f"{y}{int(mo):02d}{int(d):02d}"
    # 只有时间：用生成日期补齐
    m = re.match(r"(\d{1,2}):(\d{2})", value)
    if m:
        h, mi = m.groups()
        return ";VALUE=DATE-TIME", f"{fallback_date}T{int(h):02d}{mi}00"
    return ";VALUE=DATE", fallback_date


def export_ics(payload: dict) -> str:
    fallback_date = _created_date(payload)
    stamp = datetime.now().strftime("%Y%m%dT%H%M%SZ")
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//天健湖 TJH//群聊简报//CN",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
    ]
    for group in _groups(payload):
        group_name = group.get("name") or payload.get("group_name") or "群聊"
        for idx, item in enumerate(group.get("schedules") or []):
            if not isinstance(item, dict):
                continue
            title = str(item.get("title") or "未命名事项")
            dt_param, dt_value = _ics_datetime(str(item.get("datetime") or ""), fallback_date)
            note = str(item.get("note") or "").strip()
            sender = str(item.get("source_sender") or "").strip()
            description = note
            if sender:
                description = f"{description}（提出人：{sender}）" if description else f"提出人：{sender}"
            if not description:
                description = str(group.get("one_line") or "").strip()
            digest = hashlib.md5(
                f"{group_name}|{title}|{item.get('datetime')}|{idx}".encode("utf-8")
            ).hexdigest()[:16]
            summary = _ics_escape("[" + group_name + "] " + title)
            lines.extend(
                [
                    "BEGIN:VEVENT",
                    f"UID:{digest}@tianjianhu.local",
                    f"DTSTAMP:{stamp}",
                    f"SUMMARY:{summary}",
                    f"DTSTART{dt_param}:{dt_value}",
                    f"DESCRIPTION:{_ics_escape(description)}",
                    "END:VEVENT",
                ]
            )
    lines.append("END:VCALENDAR")
    # RFC 5545 要求 CRLF 换行
    return "\r\n".join(lines) + "\r\n"


# —— 注册表：新增格式只加一个函数 + 在这里注册 ——
EXPORTERS: dict[str, Callable[[dict], str]] = {
    "txt": export_txt,
    "json": export_json,
    "md": export_md,
    "ics": export_ics,
}


def normalize_format(fmt: str | None) -> str:
    return (fmt or "txt").strip().lower() or "txt"


def is_supported(fmt: str | None) -> bool:
    return normalize_format(fmt) in EXPORTERS


def render(fmt: str | None, payload: dict) -> str:
    """按格式渲染导出内容；不支持的格式抛 ``KeyError``（由上层转 ApiError）。"""
    key = normalize_format(fmt)
    exporter = EXPORTERS.get(key)
    if exporter is None:
        raise KeyError(key)
    return exporter(payload)


def media_type(fmt: str | None) -> str:
    return MEDIA_TYPES.get(normalize_format(fmt), "application/octet-stream")


def extension(fmt: str | None) -> str:
    key = normalize_format(fmt)
    return EXTENSIONS.get(key, key)


def formats() -> list[dict[str, Any]]:
    """可导出格式清单（供页面渲染下载按钮）。"""
    return [{"id": key, "label": FORMAT_LABELS.get(key, key)} for key in EXPORTERS]

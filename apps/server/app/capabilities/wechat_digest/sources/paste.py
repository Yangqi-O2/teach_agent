"""粘贴文本数据源：把微信 / QQ「复制聊天记录」得到的文本粘进来。

零权限、零账号、零审核，适用于任何聊天软件。移植自 ``python_work/wechat_ai``
的解析规则，支持的常见复制格式：

1. 带方括号时间的内联格式::

       [2026-10-22 17:50] 张三: 周五交实验报告

2. 微信 PC 版「复制」格式（发送者在前、时间在后、内容在下一行）::

       张三 2026-10-22 17:50
       周五交实验报告

3. QQ PC 版「复制」格式（时间在前、发送者带 QQ 号、内容在下一行）::

       2026-10-22 17:50:58 张三(123456)
       周五交实验报告

4. 简单内联格式（没有时间，只有「昵称: 内容」）::

       张三: 周五交实验报告

时间分隔条（如 ``———— 14:30 ————``）会被忽略；空行不打断消息。
"""
from __future__ import annotations

import re
from typing import Any

from .base import Message, MessageSource

# 时间片段：2026-10-22 17:50(:58)，也兼容 2026/10/22、2026.10.22
_TIME = r"\d{4}[-/.]\d{1,2}[-/.]\d{1,2}\s+\d{1,2}:\d{2}(?::\d{2})?"

# 1) [时间] 发送者: 内容
RE_INLINE_TIME = re.compile(rf"^\[(?P<time>{_TIME})\]\s*(?P<rest>.*)$")
# 2) 发送者 时间   （微信复制：昵称在前）
RE_HEADER_NAME_TIME = re.compile(rf"^(?P<sender>.{{1,40}}?)\s+(?P<time>{_TIME})$")
# 3) 时间 发送者   （QQ 复制：时间在前）
RE_HEADER_TIME_NAME = re.compile(rf"^(?P<time>{_TIME})\s+(?P<sender>.+)$")
# 4) 昵称: 内容 （兜底，中英文冒号都认）
RE_INLINE_NAME_TEXT = re.compile(r"^(?P<sender>[^\s:：][^:：]{0,30})[:：]\s*(?P<text>.+)$")

# 时间分隔条：———— 14:30 ———— / ----- -----
RE_SEPARATOR = re.compile(r"^[-—=~_\s]{3,}\s*(\d{1,2}:\d{2})?\s*[-—=~_\s]{3,}$")

# 在一段「时间型」记录里，行内出现「某某: 内容」时用来判断它是新消息还是上一句的续行。
# 常见字段名（「时间: 周五」「地点: 一教」）与网址/纯数字不当作发送者。
_FIELD_LABELS = {
    "时间", "日期", "地点", "地址", "内容", "备注", "说明", "链接", "网址", "会议",
    "会议时间", "会议地点", "会议号", "腾讯会议", "密码", "主题", "电话", "联系人",
    "群名", "群号", "公告", "附件", "注意", "提示", "要求", "费用", "报名", "活动",
    "负责", "负责人", "截止", "截止时间", "开始时间", "结束时间", "报名方式",
    "补充", "补充说明", "注", "附注", "详情", "具体", "例如", "比如", "时间安排",
    "活动安排", "负责人", "联系人", "原文", "转发", "回复", "引用",
}
_URLISH_RE = re.compile(r"^(?:https?|ftp|file|www|mailto|tel)$", re.IGNORECASE)
_DATEISH_RE = re.compile(r"^[\d\s:：/\-.年月日]+$")


def _is_plausible_sender(name: str) -> bool:
    """判断「昵称: 内容」里的昵称像不像一个人，而不是字段名 / 网址 / 日期。"""
    name = name.strip()
    if not name or len(name) > 20:
        return False
    if name in _FIELD_LABELS:
        return False
    if _URLISH_RE.match(name) or _DATEISH_RE.match(name):
        return False
    return True


def _clean_sender(name: str) -> str:
    """去掉 QQ 号后缀：``张三(123456)`` -> ``张三``。"""
    name = name.strip()
    name = re.sub(r"[\(（<]\s*\d{4,}\s*[\)）>]$", "", name).strip()
    return name


def parse_transcript(text: str, group_name: str = "粘贴内容") -> list[Message]:
    """把粘贴的聊天文本解析成 Message 列表（按出现顺序）。"""
    if not text or not text.strip():
        return []

    lines = [ln.rstrip() for ln in text.replace("\r\n", "\n").replace("\r", "\n").split("\n")]

    # 先判断是否包含「时间型」消息头，决定用哪种模式
    has_time_header = any(
        RE_INLINE_TIME.match(ln) or RE_HEADER_NAME_TIME.match(ln) or RE_HEADER_TIME_NAME.match(ln)
        for ln in lines
        if ln.strip()
    )

    messages: list[Message] = []
    cur: dict[str, str] | None = None

    def flush() -> None:
        nonlocal cur
        if cur and cur["text"].strip():
            messages.append(
                Message(
                    group=group_name,
                    sender=cur["sender"],
                    text=cur["text"].strip(),
                    time=cur["time"],
                )
            )
        cur = None

    def append_line(line: str, sender: str = "", time: str = "") -> None:
        """把一行接到当前消息；没有当前消息就开一条（可指定发送者 / 时间）。"""
        nonlocal cur
        if cur is None:
            cur = {"sender": sender, "time": time, "text": ""}
        if cur["text"] and not cur["text"].endswith("\n"):
            cur["text"] += "\n"
        cur["text"] += line + "\n"

    for raw in lines:
        line = raw.strip()

        if not line:
            # 空行不打断消息（有些导出格式段落间有空行）
            continue
        if RE_SEPARATOR.match(line):
            continue

        # —— 带时间的模式 ——
        if has_time_header:
            m = RE_INLINE_TIME.match(line)
            if m:
                flush()
                rest = m.group("rest")
                sm = RE_INLINE_NAME_TEXT.match(rest)
                if sm:
                    cur = {
                        "sender": _clean_sender(sm.group("sender")),
                        "time": m.group("time"),
                        "text": sm.group("text"),
                    }
                else:
                    cur = {"sender": "", "time": m.group("time"), "text": rest}
                continue

            m = RE_HEADER_TIME_NAME.match(line)     # QQ: 时间 昵称
            if m:
                flush()
                cur = {"sender": _clean_sender(m.group("sender")), "time": m.group("time"), "text": ""}
                continue

            m = RE_HEADER_NAME_TIME.match(line)     # 微信: 昵称 时间
            if m:
                flush()
                cur = {"sender": _clean_sender(m.group("sender")), "time": m.group("time"), "text": ""}
                continue

            # 混合格式（契约示例）：[时间] 李老师: … 之后跟着「张三: 收到」这种
            # 没有时间的行内消息——昵称像人、且上一条已有正文时，另起一条消息。
            sm = RE_INLINE_NAME_TEXT.match(line)
            if sm and _is_plausible_sender(sm.group("sender")) and (
                cur is None or cur["text"].strip()
            ):
                flush()
                cur = {
                    "sender": _clean_sender(sm.group("sender")),
                    "time": "",
                    "text": sm.group("text"),
                }
                continue

            # 普通内容行：接到当前消息后面
            append_line(line)
            continue

        # —— 无时间模式：按「昵称: 内容」 ——
        m = RE_INLINE_NAME_TEXT.match(line)
        if m and _is_plausible_sender(m.group("sender")):
            flush()
            cur = {"sender": _clean_sender(m.group("sender")), "time": "", "text": m.group("text")}
        else:
            append_line(line)

    flush()
    return messages


SAMPLE_TEXT = (
    "[2026-10-22 17:50] 李老师: 周五前交实验报告\n"
    "张三: 收到\n"
    "李老师: 下周三随堂测验，范围第 3-4 章"
)

PARAMS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "text": {
            "type": "string",
            "format": "textarea",
            "title": "聊天记录",
            "description": "支持 [时间] 昵称: 内容、微信/QQ 复制格式、纯「昵称: 内容」",
            "required": True,
        },
        "group_name": {"type": "string", "title": "会话 / 群名", "default": "粘贴内容"},
    },
}


class PasteSource(MessageSource):
    """从一段文本里读聊天记录。"""

    id = "paste"
    name = "粘贴文本"
    description = "把微信 / QQ 的聊天记录复制进来，零权限、零账号。"
    badge = "推荐"
    params_schema = PARAMS_SCHEMA
    sample_params = {"text": SAMPLE_TEXT, "group_name": "高数A班"}

    def load(self, params: dict[str, Any]) -> dict[str, list[Message]]:
        text = str(params.get("text") or "")
        group_name = str(params.get("group_name") or "").strip() or "粘贴内容"
        messages = parse_transcript(text, group_name)
        if not messages:
            raise ValueError(
                "没有从文本里解析出任何消息。支持 [时间] 昵称: 内容、微信/QQ「复制聊天记录」"
                "格式，或纯「昵称: 内容」"
            )
        return {group_name: messages}

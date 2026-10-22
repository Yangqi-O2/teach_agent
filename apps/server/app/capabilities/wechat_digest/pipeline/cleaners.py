"""多级清洗降噪：把低信息量的「吹水」消息过滤掉，省 token 并提升总结质量。

移植并增强自 ``python_work/wechat_ai/src/cleaners.py``，在原有 4 级降噪基础上
把丢弃原因统计出来，``POST /preview`` 直接展示：

- ``low_value``：拍一拍 / 撤回 / 入退群 / 「收到」「好的」「哈哈」 / 纯占位符 / 过短非问句
- ``duplicate``：长文本完全重复（重复转发去重）
- ``placeholder_limit``：同一种占位符（[图片] 等）超过保留上限

``stats`` 结构：``{before, after, dropped, drop_reasons:{low_value, duplicate, placeholder_limit}}``。
"""
from __future__ import annotations

import re

from ..sources.base import Message

# ---------- 低价值正则模式 ----------
LOW_VALUE_PATTERNS = [
    r"拍了拍",                      # 拍一拍
    r"撤回了一条消息",               # 撤回
    r"加入群聊",                    # 入群
    r"退出群聊",                    # 退群
    r"邀请.{1,20}加入群聊",          # 邀请入群
    r"分享了该群聊的二维码",
    r"改群名为",
]

# ---------- 低价值停用文本 ----------
LOW_VALUE_TEXTS = {
    "收到", "好的", "好", "嗯", "嗯嗯", "是的", "对", "可以", "ok", "OK",
    "谢谢", "哈哈", "辛苦了", "赞", "牛", "了解", "明白", "已阅", "1", "+1",
    "收到！", "好的！", "好嘞", "👍", "OK!", "谢谢!", "收到谢谢",
}

# ---------- 占位符限流：每种非文字占位最多保留的条数 ----------
PLACEHOLDER_LIMITS = {
    "[图片]": 3, "[表情]": 2, "[语音]": 2, "[视频]": 2, "[位置]": 2, "[文件]": 2,
}

PLACEHOLDER_RE = re.compile(r"\[(图片|表情|语音|视频|位置|文件)\]")

# 丢弃原因（保持契约 §3.2 的字段名）
DROP_LOW_VALUE = "low_value"
DROP_DUPLICATE = "duplicate"
DROP_PLACEHOLDER = "placeholder_limit"


def _empty_stats(before: int = 0) -> dict:
    return {
        "before": before,
        "after": 0,
        "dropped": 0,
        "drop_reasons": {DROP_LOW_VALUE: 0, DROP_DUPLICATE: 0, DROP_PLACEHOLDER: 0},
    }


def _is_mostly_symbol(text: str) -> bool:
    """判断文本是否绝大多数是符号 / 表情。"""
    if not text:
        return False
    symbols = re.findall(r"[^\w\u4e00-\u9fff]", text, flags=re.UNICODE)
    return len(symbols) / len(text) > 0.6


def _is_low_value_text(text: str) -> bool:
    """判断单条文本是否低价值（先剥掉 [图片] 等占位符再判断）。"""
    text = text.strip()
    if not text:
        return True

    # 剥掉占位符后再判断，避免「收到[图片]」这类漏网
    core = PLACEHOLDER_RE.sub("", text).strip()

    if text in LOW_VALUE_TEXTS or core in LOW_VALUE_TEXTS:
        return True
    # 剥掉占位符后为空 = 纯图片 / 表情
    if not core:
        return True
    # 过短且不是问句
    if len(core) <= 2 and "?" not in core and "？" not in core:
        return True
    if _is_mostly_symbol(text):
        return True
    for pat in LOW_VALUE_PATTERNS:
        if re.search(pat, text):
            return True
    return False


def clean_messages(messages: list[Message]) -> tuple[list[Message], dict]:
    """清洗消息列表，返回 ``(保留的消息, 统计信息)``；保留的消息维持原顺序。"""
    kept: list[Message] = []
    stats = _empty_stats(len(messages))
    drop = stats["drop_reasons"]
    seen_texts: set[str] = set()
    placeholder_count: dict[str, int] = {}

    for msg in messages:
        text = (msg.text or "").strip()

        # 1. 低价值文本
        if _is_low_value_text(text):
            stats["dropped"] += 1
            drop[DROP_LOW_VALUE] += 1
            continue

        # 2. 重复转发去重（长度 > 20 且内容完全重复；归一化空白后比较）
        norm = re.sub(r"\s+", "", text)
        if len(norm) > 20 and norm in seen_texts:
            stats["dropped"] += 1
            drop[DROP_DUPLICATE] += 1
            continue
        seen_texts.add(norm)

        # 3. 占位符限流（同一种占位符最多保留 N 条）
        ph_match = PLACEHOLDER_RE.search(text)
        if ph_match:
            ph = ph_match.group(0)
            if placeholder_count.get(ph, 0) >= PLACEHOLDER_LIMITS.get(ph, 2):
                stats["dropped"] += 1
                drop[DROP_PLACEHOLDER] += 1
                continue
            placeholder_count[ph] = placeholder_count.get(ph, 0) + 1

        kept.append(msg)

    stats["after"] = len(kept)
    return kept, stats


def clean_groups(by_group: dict[str, list[Message]]) -> tuple[dict[str, list[Message]], dict[str, dict]]:
    """按群清洗：``{群名: [Message]} -> ({群名: [保留]}, {群名: stats})``。"""
    cleaned: dict[str, list[Message]] = {}
    stats: dict[str, dict] = {}
    for name, messages in by_group.items():
        kept, st = clean_messages(messages)
        cleaned[name] = kept
        stats[name] = st
    return cleaned, stats

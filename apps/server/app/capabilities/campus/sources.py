"""校园雷达 · 抓取源定义。

只列真正会被抓的地址。加一所学校 = 在这里加几行，不需要改代码。
"""
from __future__ import annotations

from typing import Any

# 学校展示名（与 core/profile.SCHOOL_ALIASES 的 key 对应）
SCHOOL_NAMES: dict[str, str] = {
    "zzu": "郑州大学",
    "henu": "河南大学",
    "thu": "清华大学",
    "pku": "北京大学",
    "fudan": "复旦大学",
}

KIND_LABELS: dict[str, str] = {
    "notice": "通知公告",
    "news": "学校要闻",
    "openinfo": "信息公开",
    "academic": "学术活动",
}

# 郑州大学示例。
# 前两个是实测可达的（2026-10-26：index/tzgg.htm 返回 200，50 条链接）；
# 教务处与信息公开网在本机环境下返回 502，仍然保留为源——抓取会如实记录 error 状态并重试，
# 而不是把「抓不到」伪装成「没有通知」。
SOURCES: list[dict[str, Any]] = [
    {
        "id": "zzu-tzgg",
        "school_key": "zzu",
        "name": "郑州大学 · 通知公告",
        "url": "https://www.zzu.edu.cn/index/tzgg.htm",
        "kind": "notice",
    },
    {
        "id": "zzu-home",
        "school_key": "zzu",
        "name": "郑州大学 · 主页要闻",
        "url": "https://www.zzu.edu.cn/",
        "kind": "news",
    },
    {
        "id": "zzu-jwc",
        "school_key": "zzu",
        "name": "郑州大学 · 教务处",
        "url": "https://jw.zzu.edu.cn/",
        "kind": "notice",
    },
    {
        "id": "zzu-xxgk",
        "school_key": "zzu",
        "name": "郑州大学 · 信息公开",
        "url": "https://xxgk.zzu.edu.cn/",
        "kind": "openinfo",
    },
]


def sources_for(school_key: str) -> list[dict[str, Any]]:
    return [item for item in SOURCES if item["school_key"] == school_key]

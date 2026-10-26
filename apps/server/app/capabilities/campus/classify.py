"""条目分类、日期与截止时间抽取。

全部用规则，不用模型：
- 抓取阶段拿不到用户 Key，而且分类结果是入库字段，用模型会产生不可复现的数据；
- 关键词规则对中文通知标题的准确率够用（标题本身就是高度格式化的）。

宁可分到 other，也不要瞎猜 —— 用户在界面上能看到原文标题，猜错反而误导。
"""
from __future__ import annotations

import re
from datetime import date, datetime

# 优先级从高到低：一条通知同时命中多个类别时，取更「具体」的那个
RULES: list[tuple[str, list[str]]] = [
    (
        "contest",
        [
            "竞赛", "比赛", "大赛", "挑战赛", "选拔赛", "创新创业", "数学建模", "ACM",
            "程序设计", "学科竞赛", "创新创业训练", "互联网+", "挑战杯", "获奖", "参赛",
        ],
    ),
    (
        "exam",
        [
            "考试", "考核", "期中", "期末", "补考", "缓考", "重修", "四六级", "普通话等级测试",
            "成绩", "选课", "教学安排", "调课", "停课", "监考", "命题", "阅卷", "学籍", "毕业审核",
        ],
    ),
    (
        "lecture",
        ["讲座", "报告会", "学术报告", "讲堂", "论坛", "沙龙", "研讨", "学术会议", "名家"],
    ),
    (
        "activity",
        [
            "活动", "招募", "志愿者", "社团", "文艺", "演出", "运动会", "体育", "书画",
            "摄影", "征文", "晚会", "素质拓展", "社会实践", "暑期", "心理健康",
        ],
    ),
    (
        "policy",
        [
            "公示", "名单", "评选", "评定", "奖学金", "助学金", "助学贷款", "资助",
            "办法", "规定", "方案", "通知", "申报", "推荐", "审核", "管理办法",
        ],
    ),
]

CATEGORY_LABELS: dict[str, str] = {
    "contest": "竞赛",
    "exam": "考试教务",
    "lecture": "讲座学术",
    "activity": "活动",
    "policy": "政策公示",
    "other": "其他",
}

# 与用户兴趣做匹配时用的标签词表（命中的词会进 tags）
TAG_VOCAB: list[str] = [
    "人工智能", "AI", "算法", "编程", "数学", "物理", "化学", "生物", "英语", "四六级",
    "考研", "保研", "就业", "实习", "创业", "创新", "科研", "论文", "实验",
    "篮球", "足球", "排球", "羽毛球", "乒乓球", "田径", "运动会", "体育",
    "音乐", "舞蹈", "合唱", "戏剧", "话剧", "书法", "绘画", "摄影", "设计", "视频",
    "志愿", "公益", "支教", "社会实践", "社团", "学生会",
    "奖学金", "助学金", "评优", "竞赛", "比赛", "讲座", "报告", "心理健康",
    "计算机", "软件", "电子", "机械", "材料", "土木", "医学", "法学", "经济", "管理",
]

_CN_DATE = re.compile(r"(20\d{2})\s*[年\-/\.]\s*(\d{1,2})\s*[月\-/\.]\s*(\d{1,2})")
_SHORT_DATE = re.compile(r"(?<!\d)(\d{1,2})\s*[月\-]\s*(\d{1,2})(?!\d)")
_DEADLINE_HINT = re.compile(
    r"(截止|截至|报名时间|报名截止|提交时间|申报时间|申请时间|截止日期|deadline)", re.IGNORECASE
)
_DATE_RANGE = re.compile(
    r"(20\d{2}\s*年\s*\d{1,2}\s*月\s*\d{1,2}\s*日?|\d{1,2}\s*[月\-]\s*\d{1,2})"
    r"\s*[至到\-—~]\s*"
    r"(20\d{2}\s*年\s*\d{1,2}\s*月\s*\d{1,2}\s*日?|\d{1,2}\s*[月\-]\s*\d{1,2})"
)


def classify(title: str, content: str = "") -> str:
    text = f"{title}\n{content[:800]}"
    for category, words in RULES:
        if any(word in text for word in words):
            return category
    return "other"


def extract_tags(title: str, content: str = "", limit: int = 6) -> list[str]:
    text = f"{title}\n{content[:1200]}"
    hits = [word for word in TAG_VOCAB if word in text]
    # 标题里命中的排前面，正文里的补充
    titled = [word for word in hits if word in title]
    rest = [word for word in hits if word not in title]
    return list(dict.fromkeys(titled + rest))[:limit]


def _to_date(year: int, month: int, day: int) -> str | None:
    try:
        return date(year, month, day).isoformat()
    except ValueError:
        return None


def _guess_year(month: int, reference: date | None = None) -> int:
    """只有「10-14」这种短日期时补年份：比当前月份小很多就认为属于下一年。"""
    ref = reference or date.today()
    return ref.year + 1 if month < ref.month - 6 else ref.year


def find_dates(text: str, reference: date | None = None) -> list[str]:
    found: list[str] = []
    for match in _CN_DATE.finditer(text):
        value = _to_date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
        if value:
            found.append(value)
    for match in _SHORT_DATE.finditer(text):
        month, day = int(match.group(1)), int(match.group(2))
        if 1 <= month <= 12 and 1 <= day <= 31:
            value = _to_date(_guess_year(month, reference), month, day)
            if value:
                found.append(value)
    return found


def published_date(text: str, reference: date | None = None) -> str | None:
    """从列表页的一段文本里取发布日期：通常只有一个日期，取第一个。"""
    dates = find_dates(text, reference)
    return dates[0] if dates else None


def extract_deadline(text: str, reference: date | None = None) -> str | None:
    """抽取截止日期。

    三种情况按可信度依次退化：
    1. 「截止 / 报名时间」附近有日期 → 取附近最近的日期
    2. 有「A 至 B」时间范围 → 取 B（报名期的结束日）
    3. 都没有 → 返回 None，不猜
    """
    if not text:
        return None
    compact = re.sub(r"[ \t]+", " ", text)

    for match in _DEADLINE_HINT.finditer(compact):
        window = compact[match.start() : match.start() + 90]
        dates = find_dates(window, reference)
        if dates:
            return dates[-1] if len(dates) > 1 else dates[0]

    for match in _DATE_RANGE.finditer(compact):
        dates = find_dates(match.group(0), reference)
        if dates:
            return dates[-1]

    return None


def extract_audience(text: str) -> str:
    """抽取「面向对象」。只做轻量识别，抓不到就留空。"""
    patterns = [
        r"面向\s*([^，。；\n]{2,30}?)(?:，|。|；|$)",
        r"(?:参赛|报名|申请|评选|推荐)?对象\s*(?:为|是)\s*([^，。；\n]{2,30}?)(?:，|。|；|$)",
        r"([^，。；\n]{0,12}(?:年级|专业|学院|系)[^，。；\n]{0,18})",
    ]
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            value = match.group(1).strip()
            if 2 <= len(value) <= 40:
                return value
    return ""


def summarize(title: str, content: str, limit: int = 160) -> str:
    """一句话摘要：正文首个有信息量的段落，没有正文就退回标题。"""
    if not content:
        return ""
    text = re.sub(r"\s+", " ", content).strip()
    # 跳过「各学院：」「根据…」这类公文开场，但保留信息
    for sentence in re.split(r"(?<=[。！？])", text):
        candidate = sentence.strip()
        if len(candidate) >= 20:
            return candidate[:limit]
    return text[:limit]


def parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None

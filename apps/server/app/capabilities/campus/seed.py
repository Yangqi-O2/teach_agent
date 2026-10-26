"""内置示例条目（离线演示用）。

**不会被自动写入。** 只有管理员显式点「导入示例数据」时才执行，且每条都带
`is_demo = 1`，界面上会显示「示例」标记。

为什么要这个东西：抓取依赖外网，评审/演示环境可能没有网络，或者当天恰好
没有新通知。没有示例数据时，推荐与问答链路就无法演示——但用假数据冒充真实
通知是不可接受的，所以必须显式、可识别、可清除。
"""
from __future__ import annotations

import logging
from datetime import date, timedelta

from . import classify, store

log = logging.getLogger(__name__)

SOURCE_ID = "zzu-tzgg"

# 标题与正文都是构造的，只模仿真实通知的写法，不代表郑州大学实际发布内容。
SAMPLES: list[dict] = [
    {
        "title": "关于举办郑州大学程序设计竞赛（ACM 校内选拔赛）的通知",
        "category": "contest",
        "offset_publish": -4,
        "offset_deadline": 9,
        "summary": "面向全校本科生，个人赛，考察算法与数据结构，优胜者将代表学校参加省赛。",
        "content": (
            "为提高我校学生算法设计与编程能力，选拔参加河南省大学生程序设计竞赛的队员，"
            "现举办校内选拔赛。比赛采用 ACM 赛制，时长五小时，可使用的语言包括 C/C++、Java、Python。"
            "报名截止时间以本通知为准，逾期不再受理。参赛对象为全校在读本科生，"
            "计算机类、软件类专业学生优先，同时欢迎其他专业同学参加。"
        ),
        "audience": "全校本科生",
        "tags": ["算法", "编程", "竞赛", "计算机", "ACM"],
    },
    {
        "title": "关于 2026-2027 学年秋季学期大学英语四六级考试报名工作的通知",
        "category": "exam",
        "offset_publish": -7,
        "offset_deadline": 5,
        "summary": "本次报名采用网上缴费，逾期系统关闭，不再补报。",
        "content": (
            "根据教育部考试中心安排，本学期全国大学英语四、六级考试将于 12 月举行。"
            "报名对象为在校本科生与研究生。请同学登录教务系统完成报名与缴费，"
            "报名截止后系统自动关闭。照片不符合要求的需重新上传。"
        ),
        "audience": "在校本科生、研究生",
        "tags": ["英语", "四六级", "考试"],
    },
    {
        "title": "“嵩阳大讲堂”第七讲：人工智能时代的学习方式 学术报告会",
        "category": "lecture",
        "offset_publish": -2,
        "offset_deadline": None,
        "summary": "主讲人将从认知科学角度讨论生成式模型对学习习惯的影响。",
        "content": (
            "本次报告邀请校外专家，围绕人工智能技术发展对高等教育的影响展开讨论，"
            "内容包括知识获取方式的变化、学术诚信的边界以及学生应如何建立自己的学习方法。"
            "报告地点在图书馆报告厅，欢迎各院系师生参加。"
        ),
        "audience": "全校师生",
        "tags": ["人工智能", "AI", "讲座", "科研"],
    },
    {
        "title": "关于开展 2026 年“闪亮班集体”评选活动的通知",
        "category": "policy",
        "offset_publish": -10,
        "offset_deadline": 12,
        "summary": "以班级为单位申报，需提交班级建设材料与风采展示视频。",
        "content": (
            "为加强班风学风建设，现开展“闪亮班集体”评选。各学院按名额推荐，"
            "申报材料包括班级建设总结、集体活动照片与三分钟展示视频。"
            "评选结果将在校内公示。请各班班长按要求提交材料。"
        ),
        "audience": "各学院班级",
        "tags": ["评优", "班级", "社团"],
    },
    {
        "title": "关于组织学生参加 2026 年河南省大学生数学建模竞赛的通知",
        "category": "contest",
        "offset_publish": -6,
        "offset_deadline": 16,
        "summary": "三人一队，可跨院系组队，学校将组织赛前集训。",
        "content": (
            "河南省大学生数学建模竞赛将于暑期举行。参赛队由三名学生组成，鼓励跨专业组队。"
            "学校将组织为期两周的赛前培训，内容涵盖建模方法、论文写作与常用软件。"
            "报名后请留意培训通知。数学、统计、计算机等专业学生可优先考虑。"
        ),
        "audience": "全校本科生",
        "tags": ["数学", "数学建模", "竞赛"],
    },
    {
        "title": "关于举办第十六届历史情景剧系列活动的通知",
        "category": "activity",
        "offset_publish": -12,
        "offset_deadline": 20,
        "summary": "以学院为单位组队，剧本需经审核，演出时长不超过 15 分钟。",
        "content": (
            "为丰富校园文化生活，现举办历史情景剧活动。各学院组队参加，"
            "剧本需围绕历史事件或人物创作。活动设最佳剧目、最佳表演等奖项。"
            "排练场地可向团委申请。欢迎爱好表演与写作的同学报名。"
        ),
        "audience": "全校学生",
        "tags": ["戏剧", "话剧", "活动", "文艺"],
    },
    {
        "title": "关于做好学生心理健康测评工作的通知",
        "category": "exam",
        "offset_publish": -16,
        "offset_deadline": 3,
        "summary": "全体在校生需在规定时间内完成线上测评，结果仅用于心理健康服务。",
        "content": (
            "为掌握学生心理健康状况，现组织线上心理测评。测评结果严格保密，仅用于"
            "学校心理健康教育与咨询服务。请同学登录系统按实际情况填写，"
            "测评截止后系统关闭。如遇心理困扰可预约心理咨询中心。"
        ),
        "audience": "全体在校生",
        "tags": ["心理健康", "测评"],
    },
    {
        "title": "关于 2027 届毕业生就业双选会（秋季场）用人单位报名的通知",
        "category": "policy",
        "offset_publish": -3,
        "offset_deadline": 6,
        "summary": "双选会设 120 个展位，请用人单位在截止前完成线上报名。",
        "content": (
            "我校 2027 届毕业生秋季双选会将于下月举行，现开放用人单位报名。"
            "本次设展位 120 个，报名审核通过后按行业分区安排展位。"
            "毕业生可提前在就业网查看参会单位名单。"
        ),
        "audience": "2027 届毕业生",
        "tags": ["就业", "实习", "招聘"],
    },
]


def _day(offset: int | None) -> str | None:
    if offset is None:
        return None
    return (date.today() + timedelta(days=offset)).isoformat()


def install(school_key: str = "zzu") -> dict:
    """写入示例条目。已存在（按 url 去重）则跳过，可重复执行。"""
    created = 0
    skipped = 0
    for index, sample in enumerate(SAMPLES, 1):
        url = f"https://example.edu.cn/{school_key}/demo-notice-{index}"
        if store.find_item_by_url(url) is not None:
            skipped += 1
            continue
        content = sample["content"]
        store.upsert_item(
            {
                "source_id": SOURCE_ID,
                "school_key": school_key,
                "url": url,
                "title": sample["title"],
                "summary": sample["summary"] or classify.summarize(sample["title"], content),
                "content": content,
                "content_hash": f"demo-{index}",
                "category": sample["category"],
                "published_at": _day(sample["offset_publish"]),
                "deadline": _day(sample["offset_deadline"]),
                "audience": sample["audience"],
                "tags": sample["tags"],
                "is_demo": True,
            }
        )
        created += 1
    log.info("校园雷达：导入示例数据 %d 条（已存在 %d 条）", created, skipped)
    return {"created": created, "skipped": skipped, "total": len(SAMPLES)}


def remove() -> int:
    return store.execute("DELETE FROM campus_items WHERE is_demo = 1")

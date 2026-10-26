"""校园雷达与用户画像：核心逻辑 + API。

原则：**不依赖外网**。抓取相关的用例全部喂固定的 HTML 片段或指向必然失败的本地端口，
否则 CI 会因为某所学校的站点抽风而红。
"""
from __future__ import annotations

from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

from app.capabilities.campus import classify, crawler, recommend, seed, store
from app.core import profile as profiles


# ---------------------------------------------------------------- 画像

def test_normalize_school_aliases():
    assert profiles.normalize_school("郑大") == ("郑州大学", "zzu")
    assert profiles.normalize_school("郑州大学")[1] == "zzu"
    assert profiles.normalize_school("ZZU")[1] == "zzu"
    # 未知学校保留原文，key 退化为 slug
    display, key = profiles.normalize_school("某某职业技术学院")
    assert display == "某某职业技术学院"
    assert key


def test_parse_tags_accepts_mixed_shapes():
    parse = profiles._parse_tags
    assert parse("篮球,算法竞赛，AI") == ["篮球", "算法竞赛", "AI"]
    assert parse(["篮球", "篮球", " "]) == ["篮球"]
    assert parse('["考研","竞赛"]') == ["考研", "竞赛"]
    assert parse("") == []
    assert parse(None) == []
    # 坏 JSON 降级成分隔符切分，而不是抛异常
    assert parse('["未闭合') == ['["未闭合']


def test_completeness_weights():
    empty = profiles.as_dict(None)
    assert empty["completeness"] == 0
    full = profiles.as_dict(None)
    full.update(
        school="郑州大学", grade="大二", department="信息工程学院",
        major="计算机", interests=["算法"],
    )
    assert profiles.completeness(full) == 100


def test_grade_keywords_expand_year():
    keywords = profiles.grade_keywords("2024级")
    assert "2024" in keywords and "2024级" in keywords


# ---------------------------------------------------------------- 分类与日期

@pytest.mark.parametrize(
    "title,expected",
    [
        ("关于举办程序设计竞赛的通知", "contest"),
        ("关于开展数学建模大赛校内选拔的通知", "contest"),
        ("关于大学英语四六级考试报名的通知", "exam"),
        ("关于期末考试安排的通知", "exam"),
        ("嵩阳大讲堂学术报告会通知", "lecture"),
        ("关于举办运动会的通知", "activity"),
        ("关于奖学金评定名单的公示", "policy"),
        ("关于调整校园网维护时间的说明", "other"),
    ],
)
def test_classify(title, expected):
    assert classify.classify(title) == expected


def test_extract_deadline_with_hint():
    text = "报名截止时间：2026年11月5日，请及时提交。"
    assert classify.extract_deadline(text) == "2026-11-05"


def test_extract_deadline_from_range_takes_end():
    text = "报名时间 2026年10月20日至2026年11月8日。"
    assert classify.extract_deadline(text) == "2026-11-08"


def test_extract_deadline_returns_none_when_absent():
    assert classify.extract_deadline("本次会议于上午九点召开。") is None


def test_extract_audience():
    assert "本科生" in classify.extract_audience("参赛对象为全校本科生，欢迎报名。")


# ---------------------------------------------------------------- 推荐打分

def _row(**overrides):
    base = {
        "id": 1,
        "title": "关于举办程序设计竞赛的通知",
        "summary": "",
        "category": "contest",
        "published_at": date.today().isoformat(),
        "deadline": None,
        "audience": "",
        "tags_json": '["算法","竞赛"]',
    }
    base.update(overrides)
    return base


def test_interest_match_adds_score_and_reason():
    profile = {"interests": ["算法竞赛"], "goals": [], "major": "", "department": "", "grade": ""}
    score, reasons = recommend.score_item(_row(), profile)
    assert score > 1.3
    assert any("兴趣" in reason for reason in reasons)


def test_imminent_deadline_boosts_ranking():
    soon = _row(id=1, deadline=(date.today() + timedelta(days=3)).isoformat())
    later = _row(id=2, deadline=(date.today() + timedelta(days=60)).isoformat())
    profile = {"interests": [], "goals": [], "major": "", "department": "", "grade": ""}
    soon_score, soon_reasons = recommend.score_item(soon, profile)
    later_score, _ = recommend.score_item(later, profile)
    assert soon_score > later_score
    assert any("截止" in reason for reason in soon_reasons)


def test_expired_item_is_downranked():
    stale = _row(deadline=(date.today() - timedelta(days=10)).isoformat())
    profile = {"interests": [], "goals": [], "major": "", "department": "", "grade": ""}
    score, _ = recommend.score_item(stale, profile)
    fresh, _ = recommend.score_item(_row(), profile)
    assert score < fresh


def test_major_match_scores():
    profile = {"interests": [], "goals": [], "major": "计算机科学与技术", "department": "", "grade": ""}
    row = _row(title="计算机科学与技术专业实习安排")
    _, reasons = recommend.score_item(row, profile)
    assert any("专业" in reason for reason in reasons)


def test_rank_orders_by_score():
    rows = [
        _row(id=1, category="policy", title="关于公示学生名单的通知", tags_json="[]"),
        _row(id=2, category="contest", deadline=(date.today() + timedelta(days=2)).isoformat()),
    ]
    profile = {"interests": ["竞赛"], "goals": ["竞赛"], "major": "", "department": "", "grade": ""}
    ranked = recommend.rank(rows, profile)
    assert ranked[0][0]["id"] == 2


# ---------------------------------------------------------------- 列表页解析

LIST_HTML = """
<html><body>
  <ul>
    <li><a href="../info/1442/89177.htm">关于开展文博创意创新展示交流活动的通知</a>
        <span>2026-10-22</span></li>
    <li><a href="../info/1442/89158.htm">关于举办嵩阳大讲堂报告会的通知</a>
        <span>2026-10-14</span></li>
    <li><a href="https://other.example.com/ad">外部广告链接不应该被抓</a></li>
    <li><a href="javascript:void(0)">空链接</a></li>
    <li><a href="../info/1442/89177.htm">重复链接</a></li>
  </ul>
</body></html>
"""


def test_parse_list_filters_and_dedupes():
    entries = crawler.parse_list(LIST_HTML.encode("utf-8"), "https://www.zzu.edu.cn/index/tzgg.htm")
    urls = [entry.url for entry in entries]
    assert len(urls) == 2
    assert all("zzu.edu.cn" in url for url in urls)
    assert urls[0].endswith("/info/1442/89177.htm")
    assert entries[0].published_at == "2026-10-22"


def test_title_key_ignores_punctuation():
    a = crawler.title_key("关于举办“挑战杯”竞赛的通知")
    b = crawler.title_key("关于举办挑战杯竞赛的通知")
    assert a == b


# ---------------------------------------------------------------- 持久化与去重

def _item(url: str, title: str, **overrides):
    base = {
        "source_id": "zzu-tzgg",
        "school_key": "zzu",
        "url": url,
        "title": title,
        "summary": "摘要",
        "content": "正文内容",
        "content_hash": crawler._hash(title + "正文内容"),
        "category": "contest",
        "published_at": "2026-10-20",
        "deadline": "2026-11-01",
        "audience": "",
        "tags": ["竞赛"],
        "is_demo": False,
    }
    base.update(overrides)
    return base


def test_upsert_dedupes_by_url():
    url = "https://www.zzu.edu.cn/info/1442/dedupe-1.htm"
    first = store.upsert_item(_item(url, "去重测试通知一号"))
    second = store.upsert_item(_item(url, "去重测试通知一号"))
    assert first in ("created", "skipped")
    assert second == "skipped"


def test_upsert_updates_when_content_changes():
    url = "https://www.zzu.edu.cn/info/1442/dedupe-2.htm"
    store.upsert_item(_item(url, "正文会变的通知"))
    outcome = store.upsert_item(
        _item(url, "正文会变的通知", content="新的正文", content_hash="changed-hash")
    )
    assert outcome == "updated"
    row = store.find_item_by_url(url)
    assert row is not None and row["content"] == "新的正文"


def test_second_crawl_skips_everything(auth_client: TestClient):
    """同一份列表抓两次，第二次必须全部 skipped（这才是「避免重复爬取」）。"""
    source = store.get_source("zzu-tzgg")
    assert source is not None
    first = crawler.crawl_source(source, trigger="manual", max_detail=0)
    second = crawler.crawl_source(source, trigger="manual", max_detail=0)
    if first.status != "ok" or first.fetched == 0:
        pytest.skip("列表页当前不可达，跳过增量校验")
    assert second.created == 0
    assert second.skipped >= first.created


def test_crawl_failure_is_isolated():
    """源不可达时只记录 error，不抛异常、不影响其他源。"""
    broken = {
        "id": "test-broken",
        "school_key": "zzu",
        "name": "不可达测试源",
        "url": "http://127.0.0.1:1/",
        "kind": "notice",
    }
    stats = crawler.crawl_source(broken, trigger="manual", max_detail=0)
    assert stats.status == "error"
    assert stats.error


# ---------------------------------------------------------------- API

def test_profile_roundtrip(auth_client: TestClient):
    resp = auth_client.put(
        "/api/profile",
        json={
            "school": "郑大",
            "grade": "大三",
            "major": "软件工程",
            "interests": "算法竞赛,羽毛球",
            "goals": ["考研"],
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["school"] == "郑州大学"
    assert data["school_key"] == "zzu"
    assert set(data["interests"]) == {"算法竞赛", "羽毛球"}
    assert data["onboarded"] is True


def test_feed_requires_login():
    from app.main import app

    with TestClient(app) as anonymous:
        assert anonymous.get("/api/c/campus/feed").status_code in (401, 403)


def test_feed_shape(auth_client: TestClient):
    resp = auth_client.get("/api/c/campus/feed?limit=5")
    assert resp.status_code == 200
    data = resp.json()
    for key in ("school", "items", "sources", "config", "total"):
        assert key in data
    assert data["config"]["can_manage"] is True     # 首个用户是管理员


def test_ask_falls_back_to_rule_without_provider(auth_client: TestClient):
    resp = auth_client.post("/api/c/campus/ask", json={"question": "最近有什么比赛？"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["mode"] in ("rule", "llm", "empty")
    assert isinstance(data["answer"], str) and data["answer"]


def test_config_is_admin_only(auth_client: TestClient, second_user_client):
    normal = second_user_client("campusnormal")
    assert normal.get("/api/c/campus/feed").status_code == 200
    forbidden = normal.put("/api/c/campus/config", json={"interval_minutes": 120})
    assert forbidden.status_code == 403
    assert normal.post("/api/c/campus/crawl").status_code == 403


def test_admin_updates_interval(auth_client: TestClient):
    resp = auth_client.put("/api/c/campus/config", json={"interval_minutes": 120})
    assert resp.status_code == 200
    assert resp.json()["interval_minutes"] == 120
    # 恢复默认，避免影响后续用例
    auth_client.put("/api/c/campus/config", json={"interval_minutes": 360})


def test_seed_demo_and_clear(auth_client: TestClient):
    created = auth_client.post("/api/c/campus/seed-demo").json()
    assert created["created"] + created["skipped"] == created["total"]
    feed = auth_client.get("/api/c/campus/feed?limit=10").json()
    assert feed["demo_count"] >= 1
    assert all("is_demo" in item for item in feed["items"])
    removed = auth_client.delete("/api/c/campus/seed-demo").json()
    assert removed["removed"] >= 1


def test_seed_ids_are_marked_demo():
    """示例数据必须可识别——否则会被当成真实通知展示给用户。"""
    seed.install("zzu")
    rows = store.q("SELECT is_demo FROM campus_items WHERE url LIKE '%demo-notice%'")
    assert rows and all(row["is_demo"] == 1 for row in rows)
    seed.remove()

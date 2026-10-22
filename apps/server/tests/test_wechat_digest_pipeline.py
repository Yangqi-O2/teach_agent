"""群聊简报 · 管道单元测试：解析 / 清洗 / 分块 / JSON 提取 / 导出 / 注册表。"""
from __future__ import annotations

import json

import pytest

from app.capabilities.wechat_digest.pipeline import exporters, prompts, summarizer
from app.capabilities.wechat_digest.pipeline.cleaners import clean_groups, clean_messages
from app.capabilities.wechat_digest.sources import get_source, list_sources, parse_transcript
from app.capabilities.wechat_digest.sources.base import Message
from app.core.errors import ApiError


# ---------------------------------------------------------------- 解析


def test_message_to_ai_line() -> None:
    assert Message(group="g", sender="张三", text="你好", time="17:50").to_ai_line() == "[17:50] 张三: 你好"
    assert Message(group="g", sender="张三", text="你好").to_ai_line() == "张三: 你好"
    assert Message(group="g", sender="", text="补充说明").to_ai_line() == "补充说明"


def test_parse_inline_time_format() -> None:
    text = (
        "[2026-10-22 17:50] 李老师: 周五前交实验报告\n"
        "[2026-10-22 17:51] 张三: 收到，我今晚写"
    )
    messages = parse_transcript(text, "高数A班")
    assert len(messages) == 2
    assert messages[0].time == "2026-10-22 17:50"
    assert messages[0].sender == "李老师"
    assert messages[0].text == "周五前交实验报告"
    assert messages[1].sender == "张三"


def test_parse_wechat_header_format() -> None:
    text = "张三 2026-10-22 17:50\n周五交实验报告\n李四 2026-10-22 17:51\n收到"
    messages = parse_transcript(text)
    assert [(m.sender, m.time, m.text) for m in messages] == [
        ("张三", "2026-10-22 17:50", "周五交实验报告"),
        ("李四", "2026-10-22 17:51", "收到"),
    ]


def test_parse_qq_header_format_strips_qq_number() -> None:
    text = "2026-10-22 17:50:58 张三(123456)\n周五交实验报告\n2026-10-22 17:51:00 李四（654321）\n收到"
    messages = parse_transcript(text)
    assert [m.sender for m in messages] == ["张三", "李四"]
    assert messages[0].time == "2026-10-22 17:50:58"


def test_parse_mixed_time_and_plain_name_lines() -> None:
    """契约 /options 的示例就是混合格式：时间行 + 纯「昵称: 内容」行。"""
    text = (
        "[2026-10-22 17:50] 李老师: 周五前交实验报告\n"
        "张三: 收到\n"
        "李老师: 下周三随堂测验，范围第 3-4 章"
    )
    messages = parse_transcript(text, "高数A班")
    assert len(messages) == 3
    assert [m.sender for m in messages] == ["李老师", "张三", "李老师"]
    assert messages[2].text == "下周三随堂测验，范围第 3-4 章"


def test_parse_multiline_content_keeps_field_like_lines() -> None:
    text = "张三 2026-10-22 17:50\n作业要求：\n时间: 周五\n地点: 一教101\n李四 2026-10-22 17:51\n收到"
    messages = parse_transcript(text)
    assert len(messages) == 2
    assert messages[0].text == "作业要求：\n时间: 周五\n地点: 一教101"


def test_parse_plain_name_colon_format_and_separator() -> None:
    text = "张三: 周五交实验报告\n———— 14:30 ————\n李四：明天考试"
    messages = parse_transcript(text)
    assert [(m.sender, m.text) for m in messages] == [("张三", "周五交实验报告"), ("李四", "明天考试")]


def test_parse_empty_or_garbage_returns_empty() -> None:
    assert parse_transcript("") == []
    assert parse_transcript("   \n\n  ") == []


def test_paste_source_load_and_empty_error() -> None:
    source = get_source("paste")
    raw = source.load({"text": "张三: 收到\n李四: 明天交作业", "group_name": "测试群"})
    assert list(raw) == ["测试群"]
    assert len(raw["测试群"]) == 2
    with pytest.raises(ValueError):
        source.load({"text": ""})


# ---------------------------------------------------------------- 数据源注册表


def test_list_sources_descriptor() -> None:
    sources = list_sources()
    assert sources, "至少要有 paste 数据源"
    paste = next(s for s in sources if s["id"] == "paste")
    assert paste["name"] == "粘贴文本"
    assert paste["badge"] == "推荐"
    assert paste["available"] is True
    assert paste["hint"] is None
    assert paste["sample_params"]["group_name"] == "高数A班"
    schema = paste["params_schema"]
    assert schema["properties"]["text"]["required"] is True
    assert schema["properties"]["text"]["format"] == "textarea"
    assert schema["properties"]["group_name"]["default"] == "粘贴内容"


def test_get_source_unknown() -> None:
    with pytest.raises(ApiError) as excinfo:
        get_source("onebot")
    assert excinfo.value.code == "invalid_source"
    assert excinfo.value.status == 422


# ---------------------------------------------------------------- 清洗


def test_clean_messages_drop_reasons() -> None:
    def m(text: str) -> Message:
        return Message(group="g", sender="张三", text=text)

    messages = [
        m("收到"),                                        # low_value
        m("哈哈"),                                        # low_value（停用词）
        m("周五前把实验报告交到学习通，记得写名字和学号"),   # 保留
        m("周五前把实验报告交到学习通，记得写名字和学号"),   # duplicate
        m("看这张图[图片]"),                              # 占位符 1，保留
        m("看这张图[图片]"),                              # 占位符 2，保留
        m("看这张图[图片]"),                              # 占位符 3，保留
        m("看这张图[图片]"),                              # placeholder_limit
        m("???"),                                        # low_value（符号占比过高）
    ]
    kept, stats = clean_messages(messages)

    assert stats["before"] == 9
    assert stats["dropped"] == 5
    assert stats["after"] == len(kept) == 4
    assert stats["drop_reasons"] == {"low_value": 3, "duplicate": 1, "placeholder_limit": 1}


def test_clean_groups_per_group_stats() -> None:
    by_group = {
        "A群": [Message("A群", "张三", "收到"), Message("A群", "张三", "周五交作业")],
        "B群": [Message("B群", "李四", "明天考试")],
    }
    cleaned, stats = clean_groups(by_group)
    assert len(cleaned["A群"]) == 1
    assert stats["A群"]["dropped"] == 1
    assert stats["B群"]["after"] == 1


# ---------------------------------------------------------------- 分块 / token


def test_estimate_tokens_roughly_counts_cjk() -> None:
    assert summarizer.estimate_tokens("") == 0
    # 中文 1 字≈1 token
    assert summarizer.estimate_tokens("你好世界") == 4
    # ASCII 每 4 字符≈1 token
    assert summarizer.estimate_tokens("abcdefgh") == 2


def test_chunk_messages_split_and_preserve_order() -> None:
    messages = [
        Message(group="g", sender="s", text=f"第{i}条消息内容比较长一些用于触发分块", time="")
        for i in range(20)
    ]
    chunks = summarizer.chunk_messages(messages, budget=60)
    assert len(chunks) > 1
    assert [m.text for chunk in chunks for m in chunk] == [m.text for m in messages]
    assert all(chunk for chunk in chunks)


def test_chunk_messages_single_long_message_kept_whole() -> None:
    huge = Message(group="g", sender="s", text="很长" * 500)
    chunks = summarizer.chunk_messages([huge], budget=50)
    assert len(chunks) == 1
    assert chunks[0][0] is huge


# ---------------------------------------------------------------- JSON 提取


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ('{"one_line": "x"}', {"one_line": "x"}),
        ('```json\n{"one_line": "x", "items": ["a"]}\n```', {"one_line": "x", "items": ["a"]}),
        ('```\n{"one_line": "x"}\n```', {"one_line": "x"}),
        ('好的，结果如下：\n{"one_line": "x", "items": ["a"]}\n希望有帮助', {"one_line": "x", "items": ["a"]}),
        ("这里完全没有 JSON", {}),
        ("[1, 2, 3]", {}),                       # 数组不算合法结果
        ("", {}),
    ],
)
def test_extract_json(raw: str, expected: dict) -> None:
    assert summarizer.extract_json(raw) == expected


def test_parse_response_with_structured_text_and_json() -> None:
    raw = (
        "【一句话】周五前交实验报告。\n"
        "【重要事项】\n1. 周五前交实验报告\n"
        "----JSON----\n"
        '{"one_line": "周五前交实验报告。", "items": ["周五前交实验报告"],'
        ' "schedules": [{"title": "交实验报告", "datetime": "2026-10-24T23:59",'
        ' "note": "提交到学习通", "done": false, "source_sender": "李老师"}]}'
    )
    group = summarizer.parse_response("高数A班", raw, 12)

    assert group["name"] == "高数A班"
    assert group["message_count"] == 12
    assert group["one_line"] == "周五前交实验报告。"
    assert group["items"] == ["周五前交实验报告"]
    assert group["structured_text"] == "【一句话】周五前交实验报告。\n【重要事项】\n1. 周五前交实验报告"
    assert group["schedules"] == [
        {
            "title": "交实验报告",
            "datetime": "2026-10-24T23:59",
            "note": "提交到学习通",
            "done": False,
            "source_sender": "李老师",
        }
    ]


def test_parse_response_fenced_json_and_dirty_output() -> None:
    raw = (
        "【一句话】下周三随堂测验。\n"
        "----JSON----\n"
        "```json\n"
        '{"one_line": "下周三随堂测验。", "items": ["随堂测验"], "schedules": []}\n'
        "```\n"
        "以上。"
    )
    group = summarizer.parse_response("群", raw, 5)
    assert group["one_line"] == "下周三随堂测验。"
    assert group["items"] == ["随堂测验"]
    assert group["schedules"] == []


def test_parse_response_falls_back_to_plain_text() -> None:
    raw = "【一句话】今天讨论了实验报告。\n【重要事项】\n1. 周五交报告"
    group = summarizer.parse_response("群", raw, 3)
    assert group["one_line"] == "今天讨论了实验报告。"
    assert group["items"] == []
    assert group["schedules"] == []
    assert group["structured_text"] == raw


def test_parse_response_fallback_without_markers() -> None:
    raw = "今天大家讨论了实验报告，决定周五交。"
    group = summarizer.parse_response("群", raw, 1)
    assert group["one_line"] == raw
    assert group["structured_text"] == raw
    assert group["items"] == []


def test_parse_response_empty_raw_does_not_raise() -> None:
    group = summarizer.parse_response("群", "", 0)
    assert group["one_line"]
    assert group["items"] == []
    assert group["schedules"] == []


def test_normalize_schedules_ignores_invalid_items() -> None:
    raw = (
        "----JSON----\n"
        '{"schedules": [{"title": "有标题"}, "不是对象", {"note": "只有备注"},'
        ' {"title": "有时刻", "datetime": "2026-10-24"}]}'
    )
    group = summarizer.parse_response("群", raw, 1)
    titles = [item["title"] for item in group["schedules"]]
    assert titles == ["有标题", "有时刻"]


# ---------------------------------------------------------------- 提示词


def test_styles_registry_matches_contract() -> None:
    styles = prompts.list_styles()
    assert [s["id"] for s in styles] == ["general", "course", "club"]
    by_id = {s["id"]: s for s in styles}
    assert by_id["general"]["label"] == "通用"
    assert by_id["general"]["description"] == "均衡：重点、待办、日程都抓"
    assert by_id["course"]["label"] == "课程 / 学习"
    assert by_id["club"]["description"] == "更关注活动、报名、地点、负责人"


def test_build_prompt_contains_discipline_and_style() -> None:
    system, user = prompts.build_prompt(
        "高数A班", "[2026-10-22 17:50] 李老师: 交报告", 1, style="course"
    )
    assert "忠于原文" in system
    assert "不得编造" in user
    assert "----JSON----" in user
    assert "高数A班" in user
    assert "课程学习群" in user
    assert "交报告" in user


def test_get_style_unknown_falls_back_to_general() -> None:
    assert prompts.get_style("nope") is prompts.STYLES["general"]


def test_build_merge_prompt_mentions_partials() -> None:
    _, user = prompts.build_merge_prompt("群", ["【分段 1/2】A", "【分段 2/2】B"], 10, "general")
    assert "分段 1/2" in user and "分段 2/2" in user
    assert "合并去重" in user


# ---------------------------------------------------------------- 导出


@pytest.fixture()
def payload() -> dict:
    return {
        "version": 1,
        "source": "paste",
        "group_name": "高数A班",
        "style": "general",
        "provider": "AMD Radeon",
        "model": "DeepSeek-V4-Flash",
        "created_at": "2026-10-22T20:31:00",
        "stats": {"before": 120, "after": 48, "dropped": 72, "chunks": 2},
        "groups": [
            {
                "name": "高数A班",
                "message_count": 48,
                "one_line": "周五交实验报告，下周三随堂测验。",
                "items": ["周五前交实验报告", "下周三随堂测验"],
                "schedules": [
                    {
                        "title": "交实验报告",
                        "datetime": "2026-10-24T23:59",
                        "note": "提交到学习通",
                        "done": False,
                        "source_sender": "李老师",
                    },
                    {
                        "title": "买实验器材",
                        "datetime": "2026-10-23",
                        "note": "",
                        "done": True,
                        "source_sender": "",
                    },
                ],
                "structured_text": "【一句话】周五交实验报告，下周三随堂测验。\n【重要事项】\n1. 周五前交实验报告",
            }
        ],
    }


def test_export_txt_contains_meta_and_checklist(payload: dict) -> None:
    text = exporters.render("txt", payload)
    assert "群聊简报 · 高数A班" in text
    assert "生成时间：2026-10-22T20:31:00" in text
    assert "模型：AMD Radeon / DeepSeek-V4-Flash" in text
    assert "清洗：原始 120 条 → 保留 48 条（丢弃 72 条，分块 2）" in text
    assert "【一句话】周五交实验报告" in text
    assert "- [ ] 交实验报告（2026-10-24T23:59） — 提交到学习通" in text


def test_export_md_checklist(payload: dict) -> None:
    text = exporters.render("md", payload)
    assert text.startswith("# 群聊简报 · 高数A班")
    assert "### 待办 / 日程" in text
    assert "- [ ] **交实验报告**（2026-10-24T23:59） — 提交到学习通（提出人：李老师）" in text
    assert "- [x] **买实验器材**（2026-10-23）" in text


def test_export_md_empty_schedule(payload: dict) -> None:
    payload["groups"][0]["schedules"] = []
    assert "本次没有提取到明确的日程 / 待办" in exporters.render("md", payload)


def test_export_json_roundtrip(payload: dict) -> None:
    assert json.loads(exporters.render("json", payload)) == payload


def test_export_ics_structure(payload: dict) -> None:
    text = exporters.render("ics", payload)
    assert text.startswith("BEGIN:VCALENDAR\r\n")
    assert text.rstrip().endswith("END:VCALENDAR")
    assert "BEGIN:VEVENT" in text and "END:VEVENT" in text
    assert "SUMMARY:[高数A班] 交实验报告" in text
    assert "DTSTART;VALUE=DATE-TIME:20261024T235900" in text
    assert "DTSTART;VALUE=DATE:20261023" in text
    assert "DESCRIPTION:提交到学习通（提出人：李老师）" in text
    # 两个日程 → 两个 VEVENT
    assert text.count("BEGIN:VEVENT") == 2


def test_export_ics_escapes_special_chars(payload: dict) -> None:
    payload["groups"][0]["schedules"] = [
        {"title": "报名; 缴费, 领表", "datetime": "", "note": "地点：一教\n101", "done": False}
    ]
    text = exporters.render("ics", payload)
    assert "报名\\; 缴费\\, 领表" in text
    assert "地点：一教\\n101" in text


def test_export_unknown_format_raises_keyerror(payload: dict) -> None:
    with pytest.raises(KeyError):
        exporters.render("pdf", payload)
    assert exporters.is_supported("md") is True
    assert exporters.is_supported("pdf") is False
    assert set(exporters.EXPORTERS) == {"txt", "json", "md", "ics"}
    assert exporters.media_type("ics").startswith("text/calendar")
    assert exporters.extension("md") == "md"

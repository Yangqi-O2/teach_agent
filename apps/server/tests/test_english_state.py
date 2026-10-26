"""english 学习状态 agents 的单元测试（不发任何网络请求）。

覆盖：FSRS-lite 排程 / 可提取率、生词候选与命中、BM25 检索与切块、情景记忆合并
与上限、错误档案趋势与「已改正」、摘要、预算决策、文件文本抽取。

DB 测试用 conftest 已经把 `TJH_DATA_DIR` 指到临时目录后的 SQLite；迁移由能力启动时
执行（这里再兜底执行一次，保证单独跑本文件也能拿到表）。
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path

import pytest

from app.capabilities.english import store
from app.capabilities.english.agents import budget, errors, memory, rag, schedule, summary, vocab
from app.capabilities.english.agents import extract as extract_module
from app.capabilities.english.agents.extract import clean, extract_text
from app.core.errors import ApiError

# 本文件独占的 user_id 段，避免与其它测试模块的数据互相干扰
USER_VOCAB = 917_001
USER_ERRORS = 917_002
USER_TREND = 917_003
USER_IMPROVED = 917_004
USER_BUDGET = 917_005
USER_TREND_NEW = 917_006


@pytest.fixture(scope="session", autouse=True)
def _english_schema() -> None:
    """兜底执行 english 迁移（能力启动时通常已经执行过，这里是幂等的）。"""
    from app.db import run_migrations

    migrations = Path(__file__).resolve().parents[1] / "app" / "capabilities" / "english" / "migrations"
    if migrations.is_dir():
        run_migrations({"english": migrations})


def _run(coro):
    """在同步测试里跑协程，不依赖 pytest-asyncio。"""
    return asyncio.run(coro)


# ================================================================ schedule


def test_schedule_rating_intervals_increase_with_easier_rating() -> None:
    start = schedule.Card(stability=3.0, difficulty=5.0, reps=2, lapses=0, interval_days=3)
    cards = {rating: schedule.schedule(start, rating) for rating in (1, 2, 3, 4)}

    intervals = [cards[rating].interval_days for rating in (1, 2, 3, 4)]
    assert intervals == [1, 5, 6, 7]  # 忘了 / 勉强 / 记得 / 太简单
    assert intervals == sorted(intervals)

    # 忘了才记 lapse，reps 归零；其余评分 reps 递增
    assert cards[1].lapses == 1 and cards[1].reps == 0
    for rating in (2, 3, 4):
        assert cards[rating].lapses == 0
        assert cards[rating].reps == 3
        assert cards[rating].stability == float(cards[rating].interval_days)

    # 难度方向：评分越高越容易，难度越低；忘了则上调
    assert cards[1].difficulty > 5.0
    assert cards[4].difficulty < 5.0


def test_schedule_first_two_reps_use_fixed_intervals() -> None:
    first = schedule.schedule(schedule.EMPTY, 3)
    assert (first.reps, first.interval_days) == (1, 1)
    second = schedule.schedule(first, 3)
    assert (second.reps, second.interval_days) == (2, 3)
    third = schedule.schedule(second, 3)
    assert (third.reps, third.interval_days) == (3, 6)

    easy = schedule.schedule(schedule.EMPTY, 4)
    assert (easy.reps, easy.interval_days) == (1, 2)
    easy2 = schedule.schedule(easy, 4)
    assert (easy2.reps, easy2.interval_days) == (2, 5)


def test_schedule_clamps_and_sets_utc_iso_timestamps() -> None:
    now = datetime(2026, 1, 1, 8, 0, 0, tzinfo=timezone.utc)
    card = schedule.schedule(schedule.EMPTY, 3, now)
    assert card.last_review_at == "2026-01-01T08:00:00+00:00"
    assert card.next_review_at == "2026-01-02T08:00:00+00:00"

    # 间隔上限 180 天 / 难度上下限
    grown = schedule.Card(interval_days=180, stability=180.0, difficulty=1.0, reps=10)
    assert schedule.schedule(grown, 4).interval_days == 180
    assert schedule.schedule(grown, 1).difficulty <= 10.0
    hard = schedule.Card(interval_days=1, stability=1.0, difficulty=10.0, reps=10)
    assert schedule.schedule(hard, 4).difficulty >= 1.0
    assert schedule.schedule(schedule.EMPTY, 2).interval_days >= 1


def test_schedule_rejects_out_of_range_rating() -> None:
    with pytest.raises(ValueError):
        schedule.schedule(schedule.EMPTY, 0)
    with pytest.raises(ValueError):
        schedule.schedule(schedule.EMPTY, 5)


def test_retrievability_and_due() -> None:
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    card = schedule.schedule(schedule.EMPTY, 3, now)  # 间隔 1 天

    assert schedule.retrievability(card, now) == pytest.approx(1.0)
    assert schedule.retrievability(card, datetime(2026, 1, 2, tzinfo=timezone.utc)) == pytest.approx(0.9)
    assert schedule.retrievability(card, datetime(2026, 1, 31, tzinfo=timezone.utc)) < 0.05
    assert schedule.retrievability(schedule.EMPTY) == 0.0

    assert schedule.is_due(card, now) is False
    assert schedule.is_due(card, datetime(2026, 1, 2, tzinfo=timezone.utc)) is True
    assert schedule.is_due(schedule.EMPTY) is True


# ================================================================ vocab


def test_candidates_skip_capitalized_stopwords_and_duplicates() -> None:
    text = (
        "The shipment arrived late. The supplier apologised for the unexpected delay. "
        "Regulatory requirements were unclear, and the shipment is still stuck."
    )
    picked = vocab.candidates(text)
    assert "regulatory" not in picked  # 大写开头（专有名词/句首）
    assert "the" not in picked and "still" not in picked  # 停用词
    assert picked.count("shipment") == 1  # 去重
    assert {"unexpected", "apologised", "requirements"} <= set(picked)
    # 长度降序
    assert [len(word) for word in picked] == sorted([len(word) for word in picked], reverse=True)

    assert len(vocab.candidates(text, limit=2)) == 2
    assert vocab.candidates("") == []


def test_count_hits_respects_word_boundaries() -> None:
    text = "The cat sat on a category of concat toys, because the cat likes them."
    assert vocab.count_hits(text, ["cat", "category", "dog"]) == ["cat", "category"]
    assert vocab.count_hits("Nothing here", ["cat"]) == []
    assert vocab.count_hits("CAT and cat", ["cat"]) == ["cat"]


def _insert_vocab_item(user_id: int, lemma: str, created_at: str) -> None:
    store.execute(
        "INSERT INTO english_vocab_items "
        "(id, user_id, surface, lemma, context_sentence, message_id, gloss_zh, pos, created_at) "
        "VALUES (:id, :user_id, :surface, :lemma, '', NULL, NULL, NULL, :created_at)",
        id=store.new_id(),
        user_id=user_id,
        surface=lemma,
        lemma=lemma,
        created_at=created_at,
    )


def test_must_use_words_prefers_due_then_recent() -> None:
    assert vocab.must_use_words(USER_VOCAB, 3) == []

    _insert_vocab_item(USER_VOCAB, "delta", store.iso_ago(days=5))
    _insert_vocab_item(USER_VOCAB, "alpha", store.iso_ago(days=3))
    _insert_vocab_item(USER_VOCAB, "bravo", store.iso_ago(days=2))
    _insert_vocab_item(USER_VOCAB, "charlie", store.iso_ago(days=1))
    store.execute(
        "INSERT INTO english_vocab_states (user_id, lemma, stability, difficulty, reps, lapses, "
        "interval_days, last_review_at, next_review_at) "
        "VALUES (:user_id, 'delta', 1, 5, 1, 0, 1, :last, :next)",
        user_id=USER_VOCAB,
        last=store.iso_ago(days=5),
        next=store.iso_ago(days=1),
    )
    store.execute(
        "INSERT INTO english_vocab_states (user_id, lemma, stability, difficulty, reps, lapses, "
        "interval_days, last_review_at, next_review_at) "
        "VALUES (:user_id, 'echo', 1, 5, 1, 0, 1, :last, :next)",
        user_id=USER_VOCAB,
        last=store.now_iso(),
        next=store.iso_ago(days=-1),
    )

    # 到期词 delta 优先；不足的用最近新存词补齐（delta 不重复，echo 未存进 items 不出现）
    assert vocab.must_use_words(USER_VOCAB, 3) == ["delta", "charlie", "bravo"]
    assert vocab.must_use_words(USER_VOCAB, 1) == ["delta"]
    assert vocab.must_use_words(USER_VOCAB, 0) == []


# ================================================================ rag


def test_chunk_text_splits_paragraphs_and_long_blocks() -> None:
    assert rag.chunk_text("") == []
    assert rag.chunk_text("short") == []

    packed = rag.chunk_text(
        "First paragraph is long enough to keep.\n\nSecond paragraph is also long enough.",
        max_chars=1000,
    )
    assert len(packed) == 1
    assert "First paragraph" in packed[0] and "Second paragraph" in packed[0]

    long_paragraph = ("word " * 120).strip()  # 599 字符，单段超长 → 硬切 + overlap
    chunks = rag.chunk_text(long_paragraph, max_chars=200, overlap=50)
    # 窗口起点 0 / 150 / 300 / 450（步长 = max_chars - overlap）
    assert chunks == [long_paragraph[start : start + 200].strip() for start in (0, 150, 300, 450)]
    assert all(len(chunk) <= 200 for chunk in chunks)
    # 相邻块重叠 50 字符：第二块的起点落在第一块尾部
    assert chunks[1].startswith(long_paragraph[150:180])
    assert chunks[0].endswith(long_paragraph[160:200].strip())


def test_tokenize_and_bm25_ranking() -> None:
    assert rag.tokenize("The Shipment arrived; 42 boxes") == ["shipment", "arrived", "42", "boxes"]

    chunks = [
        rag.Chunk(id="c1", document_id="d1", idx=0, content="Customs held the shipment at the border."),
        rag.Chunk(id="c2", document_id="d2", idx=1, content="The monthly budget forecast looks fine."),
        rag.Chunk(id="c3", document_id="d3", idx=2, content="A delay penalty applies to late shipment delivery."),
    ]
    hits = rag.rank_bm25("shipment delay", chunks, 3)
    assert [chunk.id for chunk, _score in hits] == ["c3", "c1"]  # c2 无命中词
    assert all(score > 0 for _chunk, score in hits)
    assert len(rag.rank_bm25("shipment", chunks, top_k=1)) == 1
    assert rag.rank_bm25("", chunks) == []
    assert rag.rank_bm25("shipment", []) == []

    block = rag.render_reference(hits, {"d1": "Customs letter", "d3": "Contract"})
    assert "[1] Contract · part 3:" in block
    assert "Reference material" in block
    assert rag.render_reference([], {"d1": "x"}) == ""


# ================================================================ memory


def test_merge_memory_unions_arrays_and_bumps_revision() -> None:
    first = memory.merge_memory(memory.EMPTY_MEMORY, {"established_facts": ["a fact", "b fact"]})
    assert first["revision"] == 1
    assert first["established_facts"] == ["a fact", "b fact"]

    second = memory.merge_memory(first, {"established_facts": "c fact", "setting": "A warehouse"})
    assert second["revision"] == 2
    # 数组做并集：模型这轮「忘了」的旧事实不能丢
    assert second["established_facts"] == ["a fact", "b fact", "c fact"]
    assert second["setting"] == "A warehouse"

    deduped = memory.merge_memory(second, {"established_facts": ["A FACT", "a fact"]})
    assert deduped["established_facts"] == ["a fact", "b fact", "c fact"]


def test_merge_memory_caps_keep_earliest_or_latest() -> None:
    facts = [f"fact number {index:02d}" for index in range(10)]
    merged = memory.merge_memory(memory.EMPTY_MEMORY, {"established_facts": facts})
    assert len(merged["established_facts"]) == memory.CAPS["established_facts"] == 8
    assert merged["established_facts"][0] == "fact number 00"
    assert "fact number 09" not in merged["established_facts"]

    threads = [f"thread {index}" for index in range(8)]
    merged = memory.merge_memory(merged, {"open_threads": threads})
    assert len(merged["open_threads"]) == memory.CAPS["open_threads"] == 6
    assert merged["open_threads"][-1] == "thread 7"  # 保留最新
    assert "thread 0" not in merged["open_threads"]

    lexis = [f"word{index}" for index in range(15)]
    merged = memory.merge_memory(merged, {"lexis_used": lexis})
    assert len(merged["lexis_used"]) == memory.CAPS["lexis_used"] == 12


def test_memory_patch_accepts_single_strings() -> None:
    patch = memory.Patch(
        established_facts="a single fact",
        student_stance="wants a discount",
        lexis_used="discount",
    )
    merged = memory.merge_memory(memory.EMPTY_MEMORY, patch)
    assert merged["established_facts"] == ["a single fact"]
    assert merged["student_stance"] == ["wants a discount"]
    assert merged["lexis_used"] == ["discount"]


def test_memory_empty_and_normalize_and_render() -> None:
    assert memory.is_empty(memory.EMPTY_MEMORY) is True
    assert memory.is_empty({"setting": "A warehouse"}) is False
    assert memory.is_empty({"lexis_used": ["deadline"]}) is True  # 词汇统计不算剧情

    raw = memory.normalize_memory({"established_facts": "one fact", "revision": "3"})
    assert raw["established_facts"] == ["one fact"]
    assert raw["revision"] == 3
    assert memory.normalize_memory({"bad": object()})["open_threads"] == []

    assert memory.render_memory(memory.EMPTY_MEMORY) == ""
    block = memory.render_memory(
        {
            "setting": "A warehouse",
            "established_facts": ["3 crates missing"],
            "open_threads": ["who pays"],
        }
    )
    assert block.startswith("What has already happened in this scene")
    assert "- Setting: A warehouse" in block
    assert "- Established facts: 3 crates missing" in block
    assert "- Still unresolved: who pays" in block


class _MockMemoryLLM:
    """mock 模式：keep_memory 应该走确定性规则，不调用 json()。"""

    name = "mock"
    mock = True

    async def json(self, *_args, **_kwargs):
        raise AssertionError("mock 模式不应调用模型")

    async def stream(self, *_args, **_kwargs):
        raise AssertionError("mock 模式不应流式调用模型")


class _PatchLLM:
    """把预设 patch 当作模型结构化输出。"""

    name = "fake-planner"
    mock = False

    def __init__(self, patch: memory.Patch):
        self.patch = patch
        self.calls: list[dict] = []

    async def json(self, system: str, user: str, schema, max_tokens: int = 1200):
        assert schema is memory.Patch
        self.calls.append({"system": system, "user": user, "max_tokens": max_tokens})
        return self.patch


def test_keep_memory_mock_mode_advances_beats_without_model() -> None:
    changed, state = _run(
        memory.keep_memory(
            state=memory.EMPTY_MEMORY,
            topic_title="Late shipment",
            turn=0,
            beats=["open the claim", "agree on a refund"],
            last_user="The shipment left on Monday.",
            last_reply="Sorry to hear that.",
            llm=_MockMemoryLLM(),
        )
    )
    assert changed is True
    assert state["revision"] == 1
    assert state["beats_done"] == ["open the claim"]
    assert state["established_facts"] == ["The shipment left on Monday."]


def test_keep_memory_uses_llm_patch() -> None:
    llm = _PatchLLM(memory.Patch(established_facts=["3 crates missing"], open_threads="who pays"))
    changed, state = _run(
        memory.keep_memory(
            state=memory.EMPTY_MEMORY,
            topic_title="Late shipment",
            turn=1,
            beats=["open the claim"],
            last_user="Three crates are missing.",
            last_reply="Let me check.",
            llm=llm,
        )
    )
    assert changed is True
    assert state["established_facts"] == ["3 crates missing"]
    assert state["open_threads"] == ["who pays"]
    assert len(llm.calls) == 1
    assert "3 crates missing" not in llm.calls[0]["system"]
    assert "Three crates are missing." in llm.calls[0]["user"]


# ================================================================ errors


def test_trend_of_and_is_improved() -> None:
    assert errors.trend_of(3, 0) == "new"
    assert errors.trend_of(0, 3) == "down"
    assert errors.trend_of(3, 1) == "up"
    assert errors.trend_of(1, 3) == "down"
    assert errors.trend_of(2, 2) == "flat"
    assert errors.trend_of(0, 0) == "flat"

    assert errors.is_improved(None, 0) is False
    assert errors.is_improved("2026-01-01T00:00:00+00:00", 0) is True
    assert errors.is_improved(None, 5) is True


def test_record_analysis_dedupes_codes_and_aggregates_patterns() -> None:
    errors.record_analysis(USER_ERRORS, "msg-1", ["tense.past_simple", "tense.past_simple", "article.a_an_the"])
    run = store.one(
        "SELECT error_count FROM english_analysis_runs WHERE user_id = :user_id AND message_id = 'msg-1'",
        user_id=USER_ERRORS,
    )
    assert run is not None and run["error_count"] == 2

    errors.record_analysis(USER_ERRORS, "msg-2", ["tense.past_simple"])
    rows = store.q(
        "SELECT code, occurrences FROM english_error_patterns WHERE user_id = :user_id ORDER BY code",
        user_id=USER_ERRORS,
    )
    assert rows == [
        {"code": "article.a_an_the", "occurrences": 1},
        {"code": "tense.past_simple", "occurrences": 2},
    ]

    # 只有 occurrences >= 2 且未改正的才回流成弱项
    assert errors.weak_codes(USER_ERRORS) == ["tense.past_simple"]


def test_refresh_resolved_after_five_clean_runs() -> None:
    user = USER_IMPROVED
    errors.record_analysis(user, "m1", ["agreement.subject_verb"])
    # 把最后一次犯错挪到一天前，之后 5 次分析（now）才算「没再犯」
    store.execute(
        "UPDATE english_error_patterns SET last_seen = :last_seen "
        "WHERE user_id = :user_id AND code = 'agreement.subject_verb'",
        last_seen=store.iso_ago(days=1),
        user_id=user,
    )
    for index in range(5):
        errors.record_analysis(user, f"clean-{index}", [])

    errors.refresh_resolved(user)
    pattern = store.one(
        "SELECT resolved_at FROM english_error_patterns WHERE user_id = :user_id AND code = 'agreement.subject_verb'",
        user_id=user,
    )
    assert pattern is not None and pattern["resolved_at"]

    items = errors.list_patterns(user)
    assert len(items) == 1
    assert items[0]["code"] == "agreement.subject_verb"
    assert items[0]["improved"] is True
    assert errors.weak_codes(user) == []  # 已改正不再回流


def test_list_patterns_trend_uses_7_day_windows() -> None:
    user = USER_TREND
    errors.record_analysis(user, "m1", ["prep.time"])
    # 近 7 天 2 次、前 7 天 1 次 → up
    for index in range(2):
        store.execute(
            "INSERT INTO english_error_events "
            "(id, user_id, message_id, code, span, correction, explain_zh, severity, confidence, created_at) "
            "VALUES (:id, :user_id, 'm1', 'prep.time', 'in Monday', 'on Monday', '时间介词', 'minor', 0.9, :created_at)",
            id=store.new_id(),
            user_id=user,
            created_at=store.iso_ago(days=1, hours=index),
        )
    store.execute(
        "INSERT INTO english_error_events "
        "(id, user_id, message_id, code, span, correction, explain_zh, severity, confidence, created_at) "
        "VALUES (:id, :user_id, 'm1', 'prep.time', 'in Monday', 'on Monday', '时间介词', 'minor', 0.9, :created_at)",
        id=store.new_id(),
        user_id=user,
        created_at=store.iso_ago(days=10),
    )

    items = errors.list_patterns(user)
    assert items[0]["recent7"] == 2
    assert items[0]["prev7"] == 1
    assert items[0]["trend"] == "up"
    assert items[0]["evidence"] == []
    assert items[0]["label"]

    # 只有近 7 天数据 → new
    user_new = USER_TREND_NEW
    errors.record_analysis(user_new, "m1", ["word_form"])
    store.execute(
        "INSERT INTO english_error_events "
        "(id, user_id, message_id, code, span, correction, explain_zh, severity, confidence, created_at) "
        "VALUES (:id, :user_id, 'm1', 'word_form', 'advices', 'advice', '不可数名词', 'minor', 0.8, :created_at)",
        id=store.new_id(),
        user_id=user_new,
        created_at=store.iso_ago(days=2),
    )
    assert errors.list_patterns(user_new)[0]["trend"] == "new"


def test_weak_prompt_hints_translate_codes() -> None:
    hints = errors.weak_prompt_hints(["tense.present_perfect", "nope.unknown"])
    assert hints.startswith("The learner still struggles")
    assert "create a situation comparing past and present results" in hints
    assert "nope.unknown" not in hints
    assert errors.weak_prompt_hints([]) == ""
    assert errors.weak_prompt_hints(["nope.unknown"]) == ""


# ================================================================ summary


def test_should_summarize_thresholds() -> None:
    assert summary.should_summarize(12, 0) is True
    assert summary.should_summarize(11, 0) is False
    assert summary.should_summarize(20, 12) is True  # 未摘要 8 条
    assert summary.should_summarize(20, 13) is False
    assert summary.should_summarize(0, 0) is False


def test_fallback_summary_and_render_summary() -> None:
    turns = [
        {"role": "user", "content_md": "The   shipment left   on Monday."},
        {"role": "assistant", "content_md": "I can refund two crates."},
    ]
    text = summary.fallback_summary(turns)
    assert text.splitlines() == [
        "Learner: The shipment left on Monday.",
        "AI: I can refund two crates.",
    ]
    assert len(text) <= summary.SUMMARY_MAX_CHARS

    long_turns = [{"role": "user", "content_md": "x" * 200} for _ in range(20)]
    assert len(summary.fallback_summary(long_turns)) <= summary.SUMMARY_MAX_CHARS

    assert summary.render_summary(None, 0) == ""
    assert summary.render_summary("  ", 0) == ""
    rendered = summary.render_summary("Refund agreed.", 8)
    assert "(8 messages ago)" in rendered
    assert rendered.endswith("Refund agreed.")


class _StreamLLM:
    name = "fake-partner"
    mock = False

    def __init__(self, parts: list[str], delay: float = 0.0):
        self.parts = parts
        self.delay = delay
        self.seen: list[dict] = []

    async def stream(self, system: str, messages: list[dict], max_tokens: int = 600):
        self.seen.append({"system": system, "messages": messages, "max_tokens": max_tokens})
        for part in self.parts:
            if self.delay:
                await asyncio.sleep(self.delay)
            yield part


def test_summarize_with_llm_stream_and_timeout() -> None:
    llm = _StreamLLM(["Refund ", "of two ", "crates agreed."])
    text = _run(summary.summarize_with(llm, [{"role": "user", "content_md": "refund please"}], timeout=1.0))
    assert text == "Refund of two crates agreed."
    assert "AI: refund please" not in llm.seen[0]["messages"][0]["content"]
    assert llm.seen[0]["max_tokens"] == 900

    too_long = _StreamLLM(["y" * 800])
    assert len(_run(summary.summarize_with(too_long, [], timeout=1.0))) == summary.SUMMARY_MAX_CHARS

    slow = _StreamLLM(["late"], delay=0.2)
    with pytest.raises((asyncio.TimeoutError, TimeoutError)):
        _run(summary.summarize_with(slow, [], timeout=0.01))


# ================================================================ budget


def test_est_tokens_cost_and_budget_decision() -> None:
    assert budget.est_tokens("") == 0
    assert budget.est_tokens("abc") == 1
    assert budget.est_tokens("x" * 300) == 100

    assert budget.cost_of(1_000_000, 0) == pytest.approx(2.4)
    assert budget.cost_of(0, 1_000_000) == pytest.approx(9.6)
    assert budget.cost_of(1000, 2000) == pytest.approx(0.0216)
    assert budget.cost_of(1000, 2000, price_in=1.0, price_out=2.0) == pytest.approx(0.005)

    assert budget.budget_decision(0, 100)["degrade"] is False
    assert budget.budget_decision(89, 100)["degrade"] is False
    assert budget.budget_decision(90, 100)["degrade"] is True
    assert budget.budget_decision(150, 100)["ratio"] == pytest.approx(1.5)
    zero = budget.budget_decision(10, 0)
    assert zero == {"used": 10, "limit": 0, "ratio": 0.0, "degrade": False}


def test_month_tokens_and_check_budget() -> None:
    conversation_id = store.new_id()
    store.execute(
        "INSERT INTO english_conversations "
        "(id, user_id, scenario_id, topic_id, rolling_summary, summarized_upto, created_at, last_message_at) "
        "VALUES (:id, :user_id, 'scenario-1', '', NULL, 0, :now, :now)",
        id=conversation_id,
        user_id=USER_BUDGET,
        now=store.now_iso(),
    )

    def add_message(role: str, tokens_in: int, tokens_out: int, created_at: str) -> None:
        store.execute(
            "INSERT INTO english_messages "
            "(id, conversation_id, role, content_md, model, latency_ms, ttft_ms, "
            " tokens_in, tokens_out, cost_micros, metrics, created_at) "
            "VALUES (:id, :conversation_id, :role, 'hello', 'fake', 100, 10, "
            " :tokens_in, :tokens_out, 0, NULL, :created_at)",
            id=store.new_id(),
            conversation_id=conversation_id,
            role=role,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            created_at=created_at,
        )

    add_message("assistant", 100, 50, store.now_iso())
    add_message("user", 500, 0, store.now_iso())  # 用户消息不计入成本
    add_message("assistant", 1000, 0, store.iso_ago(days=40))  # 上月不计入本月

    assert budget.month_tokens(USER_BUDGET) == 150
    assert budget.month_tokens(USER_BUDGET + 1) == 0

    assert budget.check_budget(USER_BUDGET, {"monthly_token_budget": 200})["degrade"] is False
    over = budget.check_budget(USER_BUDGET, {"monthly_token_budget": 100})
    assert over["degrade"] is True and over["used"] == 150
    # 省略 settings 时读能力设置默认值
    assert budget.check_budget(USER_BUDGET)["limit"] == 2_000_000


# ================================================================ extract


def test_clean_removes_page_numbers_and_joins_wrapped_lines() -> None:
    raw = "Scene notes\n\n1\n\nThe shipment left late\nand nobody signed for it.\n\n\n\n12\n\nEnd of note."
    cleaned = clean(raw)
    assert "1\n" not in cleaned and "12" not in cleaned
    assert "The shipment left late and nobody signed for it." in cleaned
    assert cleaned.endswith("End of note.")
    assert "\n\n\n" not in cleaned


def test_extract_text_reads_plain_text_and_cleans() -> None:
    data = "The supplier apologised.\n\nPage 1\n\nThe shipment was three days late.".encode("utf-8")
    result = extract_text(data, "notes.txt")
    assert result["kind"] == "txt"
    assert "The supplier apologised." in result["text"]
    assert "The shipment was three days late." in result["text"]


def test_extract_text_reuses_docx_parser() -> None:
    from docx import Document

    document = Document()
    document.add_paragraph("The shipment left the warehouse on Monday.")
    buffer = BytesIO()
    document.save(buffer)

    result = extract_text(buffer.getvalue(), "shipment.docx")
    assert result["kind"] == "docx"
    assert "The shipment left the warehouse on Monday." in result["text"]


def test_extract_text_errors_are_422() -> None:
    with pytest.raises(ApiError) as unsupported:
        extract_text(b"some bytes that are long enough", "file.xyz")
    assert unsupported.value.status == 422
    assert unsupported.value.code == "EXTRACT_FAILED"

    with pytest.raises(ApiError) as empty:
        extract_text(b"", "empty.txt")
    assert empty.value.status == 422


def test_extract_text_size_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(extract_module, "MAX_BYTES", 10)
    with pytest.raises(ApiError) as excinfo:
        extract_text(b"x" * 20, "big.txt")
    assert excinfo.value.status == 422
    assert "12MB" in excinfo.value.message or "超过" in excinfo.value.message

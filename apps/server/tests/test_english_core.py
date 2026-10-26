"""english 能力 · agents-core 单测（迁移自 etutor-cn 的独立服务）。

覆盖：
- taxonomy：19 类闭合错误码 / 中文名 / 默认 severity；
- contract：zod 语义的校验、回退、词数钳制、语法点过滤、severity 窗口、难度阶梯；
- quality：指标（camelCase）、flags、重写判定与 penalty、重写提示；
- analyst：模型输出归一化、span 回验（丢弃对不上的 span / 去重）、规则兜底；
- planner：生成 + 落库 + slug 去重 + pick_topic 排序；
- partner：system prompt 关键字段与 STYLE_BANS；
- knowledge / gloss：DB 优先、mock 确定性兜底卡、失败返回 None。

全部使用本文件里的 FakeLLM，**不发任何真实网络请求**。
"""
from __future__ import annotations

import asyncio
import functools
import json
from pathlib import Path

import pytest
from pydantic import BaseModel, ValidationError

from app.capabilities.english.agents import (
    analyst,
    contract,
    gloss,
    knowledge,
    partner,
    planner,
    quality,
    taxonomy,
)
from app.capabilities.english.agents.analyst import Analysis, AnalysisSchema, GrammarError
from app.capabilities.english.agents.gloss import GlossSchema
from app.capabilities.english.agents.knowledge import CardSchema
from app.capabilities.english.agents.planner import PlanSchema, TopicSchema
from app.capabilities.english.store import execute, json_load, one, q


def _run_async(fn):
    """把 async 测试函数包成同步调用（本仓库没装 pytest-asyncio）。"""

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        return asyncio.run(fn(*args, **kwargs))

    return wrapper

# ---------------------------------------------------------------- Fake LLM


class FakeLLM:
    """离线 LLM：实现 §3.3 的最小接口（name / mock / stream / json）。

    - `payload`：json() 的固定返回；dict 会用传入的 schema 校验成模型实例；
    - `factory(schema, user)`：按 schema 动态造数据（analyst 用）；
    - `error`：json() 直接抛异常（测失败兜底）；
    - `mock=True`：模拟离线演示模式，记录是否被误调用。
    """

    def __init__(
        self,
        *,
        payload=None,
        factory=None,
        error: Exception | None = None,
        name: str = "fake-partner",
        mock: bool = False,
    ):
        self.name = name
        self.mock = mock
        self._payload = payload
        self._factory = factory
        self._error = error
        self.json_calls: list[dict] = []
        self.stream_calls: list[dict] = []

    async def stream(self, system: str, messages: list[dict], max_tokens: int = 600):
        self.stream_calls.append({"system": system, "messages": messages, "max_tokens": max_tokens})
        for chunk in ("Doctor ", "Grant ", "is ready. ", "What brings you in?"):
            yield chunk

    async def json(self, system: str, user: str, schema: type[BaseModel], max_tokens: int = 1200):
        self.json_calls.append({"system": system, "user": user, "schema": schema, "max_tokens": max_tokens})
        if self._error is not None:
            raise self._error
        value = self._factory(schema, user) if self._factory is not None else self._payload
        if isinstance(value, BaseModel):
            return value
        return schema.model_validate(value)


# ---------------------------------------------------------------- 测试库


MIGRATION_SQL = (
    Path(__file__).resolve().parents[1]
    / "app"
    / "capabilities"
    / "english"
    / "migrations"
    / "001_english.sql"
)


@pytest.fixture(scope="module", autouse=True)
def english_schema():
    """确保 english 表存在（复用能力迁移脚本，测试不依赖启动流程）。"""
    from app.db import engine

    raw = engine.raw_connection()
    try:
        raw.executescript(MIGRATION_SQL.read_text(encoding="utf-8"))
        raw.commit()
    finally:
        raw.close()
    yield


def _cleanup_scenario(scenario_id: str) -> None:
    execute("DELETE FROM english_topics WHERE scenario_id = :sid", sid=scenario_id)
    execute("DELETE FROM english_scenarios WHERE id = :sid", sid=scenario_id)


def _cleanup_cards(user_id: int) -> None:
    execute("DELETE FROM english_knowledge_cards WHERE user_id = :uid", uid=user_id)


# ---------------------------------------------------------------- taxonomy


def test_taxonomy_is_closed_with_19_codes():
    assert len(taxonomy.TAXONOMY) == 19
    assert isinstance(taxonomy.ERROR_CODES, tuple)
    assert len(taxonomy.ERROR_CODES) == 19
    assert len(set(taxonomy.ERROR_CODES)) == 19
    # 闭合枚举：ERROR_CODES 与 TAXONOMY 完全一致，且每个都有中文名 / 默认 severity
    assert set(taxonomy.ERROR_CODES) == set(taxonomy.TAXONOMY)
    assert set(taxonomy.DEFAULT_SEVERITY) == set(taxonomy.ERROR_CODES)
    for code in taxonomy.ERROR_CODES:
        assert taxonomy.TAXONOMY[code].strip(), code
        assert taxonomy.DEFAULT_SEVERITY[code] in {"low", "medium", "high"}, code
    assert taxonomy.code_label("tense.past_simple") == "一般过去时"
    assert taxonomy.code_label("agreement.subject_verb") == "主谓一致"
    # 未知 code 原样返回（TS: TAXONOMY[c]?.zh ?? c）
    assert taxonomy.code_label("made.up_code") == "made.up_code"
    assert taxonomy.default_severity("tense.present_perfect") == "high"
    assert taxonomy.default_severity("nope") == "medium"


# ---------------------------------------------------------------- contract


def test_contract_defaults_and_invalid_payload():
    c, warnings = contract.normalize_contract(None)
    assert warnings == []
    assert c == contract.DEFAULT_CONTRACT

    c2, warnings2 = contract.normalize_contract({})
    assert warnings2 == []
    assert c2.must_use_words == [] and c2.grammar_focus == []
    assert c2.correction_intensity == "medium"
    assert c2.difficulty_delta == 0
    assert c2.max_reply_words == 90

    invalid_payloads = [
        {"max_reply_words": 20},                       # < 40
        {"max_reply_words": 161},                      # > 160
        {"difficulty_delta": 2},                       # 越界
        {"correction_intensity": "brutal"},            # 非枚举
        {"must_use_words": ["a"]},                     # 单词 < 2 字符
        {"must_use_words": ["word"] * 7},              # 数组 > 6
        {"grammar_focus": ["x" * 61]},                 # 条目 > 60 字符
        {"must_use_words": "not-a-list"},              # 类型错
        "not-a-dict",
    ]
    for payload in invalid_payloads:
        bad, bad_warnings = contract.normalize_contract(payload)
        assert bad == contract.DEFAULT_CONTRACT, payload
        assert bad_warnings == ["参数不合法，已回退到默认设置"], payload


def test_contract_clamps_words_and_filters_grammar_focus():
    c, warnings = contract.normalize_contract(
        {
            "must_use_words": ["shipment", "deadline", "budget", "stakeholder"],
            "grammar_focus": ["tense.past_simple", "no_such.code", "article.a_an_the"],
        }
    )
    assert c.must_use_words == ["shipment", "deadline", "budget"]
    assert c.grammar_focus == ["tense.past_simple", "article.a_an_the"]
    assert warnings == [
        "一次最多自然复用 3 个词，已保留前 3 个",
        "忽略了无法识别的语法点：no_such.code",
    ]


def test_contract_normalize_does_not_mutate_defaults():
    c, _ = contract.normalize_contract({})
    c.must_use_words.append("shipment")
    c.grammar_focus.append("tense.past_simple")
    assert contract.DEFAULT_CONTRACT.must_use_words == []
    assert contract.DEFAULT_CONTRACT.grammar_focus == []


def test_apply_delta_clamps_within_ladder():
    assert contract.apply_delta("B1", 0) == ("B1", False)
    assert contract.apply_delta("B2", 1) == ("C1", False)
    assert contract.apply_delta("C1", 1) == ("C1", True)     # 越界停住并提示
    assert contract.apply_delta("A2", -1) == ("A2", True)
    assert contract.apply_delta("B1", -1) == ("A2", False)
    # 不在阶梯内：原样返回、不算越界（照搬 TS）
    assert contract.apply_delta("Z9", 1) == ("Z9", False)


def test_severity_window_by_intensity():
    assert contract.allowed_severity("light") == ["high"]
    assert contract.allowed_severity("medium") == ["high", "medium"]
    assert contract.allowed_severity("strict") == ["low", "medium", "high"]
    assert contract.allowed_severity("other") == ["high", "medium"]  # 未知按 medium
    assert contract.severity_allowed("light", "high") is True
    assert contract.severity_allowed("light", "medium") is False
    assert contract.severity_allowed("strict", "low") is True


def test_contract_hints():
    assert contract.contract_hints(contract.DEFAULT_CONTRACT) == ""
    c = contract.Contract(must_use_words=["shipment"], grammar_focus=["tense.past_simple"])
    hints = contract.contract_hints(c)
    assert hints.startswith("Learner request — ")
    assert "naturally use: shipment" in hints
    assert "the learner asked to practise: tense.past_simple" in hints
    assert hints.endswith("Work them in only where the scene allows; never force them.")


# ---------------------------------------------------------------- quality


GOOD_REPLY = (
    "The shipment is still sitting at the port, and the carrier wants a decision today. "
    "We could reroute it through Singapore, though that adds four days. "
    "Alternatively, keep the original route and accept the demurrage charge. "
    "I have checked the numbers, and the second option is cheaper in the short run. "
    "Tell me which one you prefer, and I will call the agent before noon. "
    "What matters more to you here: the cost or the delay?"
)


def test_quality_good_reply_has_no_flags():
    verdict = quality.measure_reply(GOOD_REPLY, "B1")
    assert verdict["flags"] == []
    metrics = verdict["metrics"]
    # 字段名保持 TS 版 camelCase（messages.metrics JSON 原样落库 / 看板读取）
    assert set(metrics) == {
        "words", "sentences", "avgSentenceWords", "endsWithQuestion", "bannedHits",
        "listLike", "hasHeading", "overLevelRatio", "repeatedOpener", "unfinished", "wordBasis",
    }
    assert metrics["endsWithQuestion"] is True
    assert 40 <= metrics["words"] <= 160
    assert 24 >= metrics["avgSentenceWords"] > 0
    assert metrics["bannedHits"] == []
    assert metrics["listLike"] is False and metrics["hasHeading"] is False
    assert metrics["unfinished"] is False
    assert metrics["overLevelRatio"] == 0
    assert metrics["wordBasis"] == "builtin:52words"
    assert quality.needs_repair(verdict) is False
    assert quality.penalty_of(verdict) == 0


def test_quality_bad_reply_flags_and_repair():
    bad = "It is important to note this. In conclusion, we should act now. - first item\n- second item"
    verdict = quality.measure_reply(bad, "B1")
    flags = verdict["flags"]
    assert "no_question" in flags
    assert "unfinished" in flags
    assert "list_format" in flags
    assert any(f.startswith("banned:") for f in flags)
    assert "too_short" in flags
    assert verdict["metrics"]["bannedHits"] == ["it is important to", "in conclusion"]

    assert quality.needs_repair(verdict) is True
    # 硬违规每条 -10，软违规每条 -1
    hard = sum(1 for f in flags if f.split(":")[0] in quality.HARD)
    assert quality.penalty_of(verdict) == -10 * hard - (len(flags) - hard)

    hint = quality.repair_hint(verdict)
    assert hint.startswith("Rewrite your previous reply. Problems: ")
    assert "you did not end with a question" in hint
    assert "you used a list instead of talking" in hint
    assert "you used phrases the learner should not see" in hint
    assert "avoid: it is important to, in conclusion" in hint
    assert hint.endswith(
        "Stay in character, 50–90 words, finish the sentence, end with one concrete question, "
        "no lists, no headings."
    )


def test_quality_soft_flags_only_not_repaired():
    # 过长 / 句子长属于软违规：只记录，不重写
    sentence = " ".join(["word"] * 30)
    long_sentences = ". ".join([sentence] * 6) + " Is that okay?"
    verdict = quality.measure_reply(long_sentences, "B2")
    assert "too_long" in verdict["flags"]
    assert "long_sentences" in verdict["flags"]
    assert quality.needs_repair(verdict) is False
    assert quality.penalty_of(verdict) < 0
    assert quality.repair_hint(verdict) == (
        "Rewrite your previous reply. Problems: . Stay in character, 50–90 words, "
        "finish the sentence, end with one concrete question, no lists, no headings."
    )


def test_quality_level_ratio_depends_on_cefr():
    text = "The decision was hard to explain. What will you do about the decision now?"
    a2 = quality.measure_reply(text, "A2")
    c1 = quality.measure_reply(text, "C1")
    assert a2["metrics"]["overLevelRatio"] == 1.0
    assert "over_level" in a2["flags"]
    assert c1["metrics"]["overLevelRatio"] == 0.0
    assert "over_level" not in c1["flags"]


# ---------------------------------------------------------------- analyst


def test_normalize_analysis_is_tolerant():
    raw = {
        "errors": [
            {"span": "have went", "code": "tense.present_perfect"},                    # 缺 severity -> 默认 high
            {"span": "", "code": "spelling"},                                          # 空 span -> 丢
            {"span": "decision", "code": "made.up_code"},                              # 未知 code -> 丢
            {"span": "decision", "code": "lexical_choice", "severity": "high",
             "correction": "choice", "explain_zh": "用词不当"},
        ],
        "confidence": "0.75",
    }
    analysis = analyst.normalize_analysis(raw)
    assert [e.span for e in analysis.errors] == ["have went", "decision"]
    assert analysis.errors[0].severity == "high"
    assert analysis.errors[0].confidence == pytest.approx(0.75)
    assert analysis.confidence == pytest.approx(0.75)
    assert analysis.errors[1].severity == "high"
    assert analysis.errors[1].correction == "choice"
    assert analysis.errors[1].explain_zh == "用词不当"
    # correction / explain_zh 缺省兜底
    assert analysis.errors[0].correction == "have went"
    assert analysis.errors[0].explain_zh == "用法有误"

    assert analyst.normalize_analysis({"confidence": "abc"}).confidence == pytest.approx(0.8)
    assert analyst.normalize_analysis({"confidence": 2}).confidence == pytest.approx(1.0)
    assert analyst.normalize_analysis({"confidence": -1}).confidence == pytest.approx(0.0)
    assert analyst.normalize_analysis(None).errors == []


def test_grammar_error_fields_follow_spec():
    # §6 契约：SSE annotations / error_events 只需要这 6 个字段（无 start/end）
    assert set(GrammarError.model_fields) == {
        "code", "span", "correction", "explain_zh", "severity", "confidence",
    }
    assert set(Analysis.model_fields) == {"errors", "confidence"}


def test_validate_spans_drops_and_dedupes():
    text = "I have went to school and I have went home."
    analysis = Analysis(
        errors=[
            GrammarError(code="tense.present_perfect", span="have went", correction="have gone",
                         explain_zh="要用过去分词", severity="high", confidence=0.9),
            GrammarError(code="tense.present_perfect", span="have went", correction="have gone",
                         explain_zh="重复", severity="high", confidence=0.9),   # 同位置同 code -> 去重
            GrammarError(code="tense.past_simple", span="have went", correction="went",
                         explain_zh="不同 code 可保留", severity="high", confidence=0.9),
            GrammarError(code="spelling", span="does not exist", correction="x",
                         explain_zh="模型编的 span", severity="low", confidence=0.9),  # 原文没有 -> 丢
        ],
        confidence=0.9,
    )
    cleaned = analyst.validate_spans(text, analysis)
    assert [(e.span, e.code) for e in cleaned.errors] == [
        ("have went", "tense.present_perfect"),
        ("have went", "tense.past_simple"),
    ]
    assert cleaned.confidence == pytest.approx(0.9)


def test_rule_analyze_covers_tense_and_agreement():
    text = "He go to work by bus. I have saw that film. I am know the answer."
    analysis = analyst.rule_analyze(text)
    assert analysis.confidence == pytest.approx(0.9)
    assert len(analysis.errors) <= 5
    by_code = {e.code: e for e in analysis.errors}
    assert by_code["agreement.subject_verb"].span == "He go"
    assert by_code["agreement.subject_verb"].correction == "He goes"
    assert by_code["tense.present_perfect"].span == "have saw"
    assert by_code["tense.present_perfect"].correction == "have seen"
    assert by_code["tense.present_continuous"].span == "am know"
    assert by_code["tense.present_continuous"].correction == "know"
    assert all(e.severity == "high" for e in analysis.errors)
    # 每条 span 都必须真的出现在原文里
    for error in analysis.errors:
        assert error.span in text
    assert all(e.confidence == pytest.approx(0.9) for e in analysis.errors)


def test_rule_analyze_covers_article_prep_and_spelling():
    text = "I saw a apple and an car in Monday. I recieve it."
    analysis = analyst.rule_analyze(text)
    assert len(analysis.errors) <= 5
    by_code = {e.code: e for e in analysis.errors}
    assert by_code["article.a_an_the"].span in ("a apple", "an car")
    corrections = {e.span: e.correction for e in analysis.errors}
    assert corrections["a apple"] == "an apple"
    assert corrections["an car"] == "a car"
    assert by_code["prep.time"].correction == "on Monday"
    assert by_code["spelling"].correction == "receive"
    assert by_code["spelling"].severity == "low"
    for error in analysis.errors:
        assert error.span in text


@_run_async
async def test_analyze_uses_llm_and_validates_spans():
    def factory(schema, user):
        assert schema is AnalysisSchema
        assert user == "原文：I have went to school."
        return {
            "errors": [
                {"span": "have went", "code": "tense.present_perfect", "severity": "high",
                 "correction": "have gone", "explain_zh": "要用过去分词"},
                {"span": "not in text", "code": "spelling"},     # 回验丢弃
                {"span": "went", "code": "not.a.code"},          # 闭合枚举丢弃
            ],
            "confidence": 0.8,
        }

    llm = FakeLLM(factory=factory, name="fake-planner")
    analysis, provider = await analyst.analyze("I have went to school.", llm)
    assert provider == "fake-planner"
    assert [(e.code, e.span) for e in analysis.errors] == [("tense.present_perfect", "have went")]
    assert llm.json_calls[0]["max_tokens"] == 700
    assert llm.json_calls[0]["schema"] is AnalysisSchema
    # 枚举写在 system prompt 里，且是闭合的 19 类
    assert "tense.present_perfect" in llm.json_calls[0]["system"]
    assert "枚举：" in llm.json_calls[0]["system"]


@_run_async
async def test_analyze_falls_back_to_rules():
    text = "He go to work by bus."
    # LLM 抛错 -> 规则兜底
    failed = FakeLLM(error=RuntimeError("upstream down"))
    analysis, provider = await analyst.analyze(text, failed)
    assert provider == "rule-based"
    assert [e.code for e in analysis.errors] == ["agreement.subject_verb"]

    # mock 模式：直接规则兜底，不调用 JSON
    mocked = FakeLLM(mock=True, name="mock")
    analysis2, provider2 = await analyst.analyze(text, mocked)
    assert provider2 == "rule-based"
    assert mocked.json_calls == []
    assert [e.code for e in analysis2.errors] == ["agreement.subject_verb"]


def test_analysis_schema_accepts_tolerant_model_output():
    schema = AnalysisSchema.model_validate(
        {"errors": [{"span": "x", "code": "spelling", "start": 3, "end": 4}], "confidence": "high"}
    )
    assert schema.errors[0].span == "x"
    assert schema.confidence == "high"


# ---------------------------------------------------------------- planner


def _plan_payload(slug: str = "cross-border-logistics") -> dict:
    return {
        "title_zh": "跨境物流谈判",
        "title_en": "Cross-border logistics negotiation",
        "slug": slug,
        "topics": [
            {
                "title": f"Topic angle {index}",
                "beats": ["open with a delayed shipment", "raise a constraint", "close with next step"],
                "target_tenses": ["past simple", "present perfect"],
                "target_lexis": ["demurrage", "deadline"],
                "difficulty": "B1" if index % 2 == 0 else "B2",
            }
            for index in range(6)
        ],
    }


@_run_async
async def test_plan_scenario_persists_and_returns_plan():
    llm = FakeLLM(payload=_plan_payload(), name="fake-planner")
    plan = await planner.plan_scenario("跨境物流", "B1", llm)
    try:
        assert plan["provider"] == "fake-planner"
        assert plan["title_zh"] == "跨境物流谈判"
        assert plan["slug"] == "cross-border-logistics"
        assert len(plan["topics"]) == 6
        assert set(plan["topics"][0]) == {"title", "beats", "target_tenses", "target_lexis", "difficulty"}
        assert llm.json_calls[0]["schema"] is PlanSchema
        assert llm.json_calls[0]["max_tokens"] == 1600
        assert llm.json_calls[0]["user"] == "领域：跨境物流\n学习者目标水平：B1"

        scenario = one("SELECT * FROM english_scenarios WHERE id = :id", id=plan["id"])
        assert scenario is not None
        assert scenario["slug"] == "cross-border-logistics"
        assert scenario["title_zh"] == "跨境物流谈判"
        assert scenario["domain"] == "跨境物流"
        assert scenario["cefr"] == "B1"
        assert scenario["created_at"]

        topics = q(
            "SELECT * FROM english_topics WHERE scenario_id = :sid ORDER BY created_at, title",
            sid=plan["id"],
        )
        assert len(topics) == 6
        assert json_load(topics[0]["beats"]) == _plan_payload()["topics"][0]["beats"]
        assert json_load(topics[0]["target_tenses"]) == ["past simple", "present perfect"]
        assert json_load(topics[0]["target_lexis"]) == ["demurrage", "deadline"]
        assert topics[0]["used_count"] == 0
        assert topics[0]["last_used_at"] is None
    finally:
        _cleanup_scenario(plan["id"])


@_run_async
async def test_plan_scenario_makes_slug_unique():
    existing_id = "test-existing-scenario"
    execute(
        "INSERT INTO english_scenarios (id, slug, title_zh, title_en, domain, cefr, created_at) "
        "VALUES (:id, :slug, :title_zh, :title_en, :domain, :cefr, :created_at)",
        id=existing_id,
        slug="cross-border-logistics",
        title_zh="占位",
        title_en="Placeholder",
        domain="跨境物流",
        cefr="B1",
        created_at="2026-01-01T00:00:00+00:00",
    )
    llm = FakeLLM(payload=_plan_payload())
    plan = await planner.plan_scenario("跨境物流", "B1", llm)
    try:
        assert plan["slug"] == "cross-border-logistics-2"
        assert one("SELECT 1 AS hit FROM english_scenarios WHERE slug = :slug", slug=plan["slug"])
    finally:
        _cleanup_scenario(plan["id"])
        execute("DELETE FROM english_scenarios WHERE id = :id", id=existing_id)


def test_pick_topic_prefers_least_used_then_oldest():
    scenario_id = "test-pick-topic"
    execute(
        "INSERT INTO english_scenarios (id, slug, title_zh, title_en, domain, cefr, created_at) "
        "VALUES (:id, :slug, :title_zh, :title_en, :domain, :cefr, :created_at)",
        id=scenario_id, slug="test-pick-topic", title_zh="占位", title_en="Placeholder",
        domain="测试", cefr="B1", created_at="2026-01-01T00:00:00+00:00",
    )
    rows = [
        ("t-1", "从未用过", 0, None),
        ("t-2", "较早用过", 0, "2026-01-01T00:00:00+00:00"),
        ("t-3", "用过一次", 1, None),
    ]
    for tid, title, used, last in rows:
        execute(
            "INSERT INTO english_topics (id, scenario_id, title, beats, target_tenses, target_lexis, "
            "difficulty, used_count, last_used_at, created_at) VALUES "
            "(:id, :sid, :title, :beats, :tenses, :lexis, :difficulty, :used, :last, :created)",
            id=tid, sid=scenario_id, title=title,
            beats=json.dumps(["beat one", "beat two", "beat three"], ensure_ascii=False),
            tenses=json.dumps(["past simple"]), lexis=json.dumps(["demurrage", "deadline"]),
            difficulty="B1", used=used, last=last, created="2026-01-01T00:00:00+00:00",
        )
    try:
        topic = planner.pick_topic(scenario_id)
        assert topic is not None
        assert topic["id"] == "t-1"                     # used_count 最少 + last_used_at NULLS FIRST
        assert topic["beats"] == ["beat one", "beat two", "beat three"]
        assert topic["target_tenses"] == ["past simple"]

        execute(
            "UPDATE english_topics SET used_count = 1, last_used_at = :now WHERE id = 't-1'",
            now="2026-01-02T00:00:00+00:00",
        )
        next_topic = planner.pick_topic(scenario_id)
        assert next_topic is not None and next_topic["id"] == "t-2"
        assert planner.pick_topic("no-such-scenario") is None
    finally:
        _cleanup_scenario(scenario_id)


def test_plan_schema_rejects_out_of_contract_plan():
    with pytest.raises(ValidationError):
        PlanSchema.model_validate({**_plan_payload(), "topics": _plan_payload()["topics"][:5]})
    with pytest.raises(ValidationError):
        PlanSchema.model_validate({**_plan_payload(), "slug": "Not A Slug!"})
    with pytest.raises(ValidationError):
        TopicSchema.model_validate(
            {"title": "abc", "beats": ["ok beat"], "target_tenses": ["x"],
             "target_lexis": ["a", "b"], "difficulty": "B1"}
        )


# ---------------------------------------------------------------- partner


def test_partner_prompt_contains_key_fields():
    prompt = partner.build_system_prompt(
        scenario_title="A stalled shipment",
        topic_title="Negotiating demurrage",
        beats=["open with a delayed shipment", "raise a constraint", "close with next step"],
        target_tenses=["past simple", "present perfect"],
        target_lexis=["demurrage", "deadline"],
        cefr="B2",
        turn=1,
        max_reply_words=90,
    )
    assert prompt.startswith("You are playing a character in a role-play conversation")
    assert "Scenario: A stalled shipment" in prompt
    assert "Current topic: Negotiating demurrage" in prompt
    assert "Learner level: B2. 句长有明显变化，可用非谓语与从句，允许少量习语。" in prompt
    assert 'Move the scene toward this beat: "raise a constraint".' in prompt
    assert "Use these tenses naturally where the situation calls for them: past simple, present perfect." in prompt
    assert "work in one of these words: demurrage, deadline." in prompt
    assert "Reply in 70–90 words" in prompt
    assert "End with one concrete question that keeps the learner talking." in prompt
    assert "Never correct the learner's grammar" in prompt
    assert partner.STYLE_BANS in prompt
    assert prompt.endswith("Do not use markdown headings. Plain conversational English only.")
    # 没有可选块时不应出现空行占位或 None
    assert "None" not in prompt
    assert "The learner is reviewing these words" not in prompt


def test_partner_prompt_includes_optional_blocks():
    prompt = partner.build_system_prompt(
        scenario_title="Interview",
        topic_title="Opening",
        beats=["open with a greeting"],
        target_tenses=["present simple"],
        target_lexis=["role", "experience"],
        cefr="A2",
        turn=0,
        must_use=["interview", "candidate"],
        memory_block="MEMORY-BLOCK",
        history_summary="SUMMARY-LINE",
        weak_hints="WEAK-HINTS",
        reference_block="REFERENCE-BLOCK",
        max_reply_words=60,
    )
    assert "Reply in 40–60 words" in prompt
    assert "The learner is reviewing these words: interview, candidate." in prompt
    assert "MEMORY-BLOCK" in prompt and "SUMMARY-LINE" in prompt
    assert "WEAK-HINTS" in prompt and "REFERENCE-BLOCK" in prompt
    assert "Facts NOT written in the reference above must not be stated" in prompt
    # TS 顺序：memory -> summary -> weak -> reference
    assert prompt.index("MEMORY-BLOCK") < prompt.index("SUMMARY-LINE")
    assert prompt.index("SUMMARY-LINE") < prompt.index("WEAK-HINTS")
    assert prompt.index("WEAK-HINTS") < prompt.index("REFERENCE-BLOCK")
    # 未知 cefr 回退 B1 引导语
    fallback = partner.build_system_prompt(
        scenario_title="X", topic_title="Y", beats=["beat one"], target_tenses=["t"],
        target_lexis=["a"], cefr="Z9", turn=0,
    )
    assert partner.LEVEL_GUIDE["B1"] in fallback


def test_partner_to_messages_slices_and_skips_bad_roles():
    rows = [{"role": "user", "content_md": f"m{index}"} for index in range(12)]
    rows.insert(3, {"role": "system", "content_md": "ignore me"})
    messages = partner.to_messages(rows)
    assert len(messages) == 9                                # 最近 10 条里还有 1 条异常 role 被跳过
    assert messages[0] == {"role": "user", "content": "m3"}
    assert all(message["role"] in ("user", "assistant") for message in messages)
    assert partner.to_messages([{"role": "assistant", "content_md": "hi"}]) == [
        {"role": "assistant", "content": "hi"}
    ]


# ---------------------------------------------------------------- knowledge


@pytest.mark.parametrize("user_id", [901_001, 901_002, 901_003])
def test_knowledge_creates_and_reuses_card(user_id: int):
    card_payload = {
        "title": "have/has + 过去分词",
        "rule_md": "**口诀**：have/has 后面跟过去分词。\n\n易混：went 是过去式，gone 才是过去分词。",
        "examples": [
            {"wrong": "She has went home.", "right": "She has gone home.", "note": "go 的三态"},
            {"wrong": "I have saw it.", "right": "I have seen it.", "note": "see 的三态"},
        ],
    }
    llm = FakeLLM(payload=card_payload, name="fake-planner")
    try:
        card = asyncio.run(knowledge.get_or_create_card(user_id, "tense.present_perfect", llm))
        assert card["code"] == "tense.present_perfect"
        assert card["label"] == "现在完成时"
        assert card["title"] == card_payload["title"]
        assert card["rule_md"] == card_payload["rule_md"]
        assert card["examples"] == card_payload["examples"]
        assert len(llm.json_calls) == 1
        assert llm.json_calls[0]["schema"] is CardSchema
        assert llm.json_calls[0]["max_tokens"] == 600
        assert llm.json_calls[0]["user"] == "错误类型：tense.present_perfect（现在完成时）"

        row = one(
            "SELECT * FROM english_knowledge_cards WHERE user_id = :uid AND code = :code",
            uid=user_id, code="tense.present_perfect",
        )
        assert row is not None
        assert json_load(row["examples"]) == card_payload["examples"]

        # 第二次：DB 优先，不再调用模型
        second = FakeLLM(error=RuntimeError("should not be called"))
        reused = asyncio.run(knowledge.get_or_create_card(user_id, "tense.present_perfect", second))
        assert reused["title"] == card_payload["title"]
        assert second.json_calls == []
    finally:
        _cleanup_cards(user_id)


def test_knowledge_mock_mode_uses_deterministic_card_without_llm():
    user_id = 901_004
    mocked = FakeLLM(mock=True, name="mock")
    try:
        card = asyncio.run(knowledge.get_or_create_card(user_id, "prep.time", mocked))
        assert mocked.json_calls == []                       # 离线演示：不发网络请求
        assert card["label"] == "时间介词"
        assert card["title"] == "时间介词：in 段、on 天、at 点"
        assert "in 用于年/月/季节" in card["rule_md"]
        assert len(card["examples"]) == 2
        row = one(
            "SELECT title FROM english_knowledge_cards WHERE user_id = :uid AND code = :code",
            uid=user_id, code="prep.time",
        )
        assert row is not None and row["title"] == card["title"]

        # HINTS 里没有的 code 用通用模板
        generic = asyncio.run(knowledge.get_or_create_card(user_id, "word_order", mocked))
        assert generic["title"] == "先看判断依据：语序"
        assert "**语序**" in generic["rule_md"]
    finally:
        _cleanup_cards(user_id)


def test_knowledge_rejects_unknown_code():
    with pytest.raises(ValueError):
        asyncio.run(knowledge.get_or_create_card(901_005, "no.such_code", FakeLLM(mock=True)))


# ---------------------------------------------------------------- gloss


@_run_async
async def test_gloss_word_returns_dict():
    llm = FakeLLM(payload={"gloss_zh": " 滞期费 ", "pos": " n. "}, name="fake-planner")
    result = await gloss.gloss_word("demurrage", "The demurrage charge is high.", llm)
    assert result == {"glossZh": "滞期费", "pos": "n."}
    assert llm.json_calls[0]["schema"] is GlossSchema
    assert llm.json_calls[0]["max_tokens"] == 200
    assert llm.json_calls[0]["user"] == "单词：demurrage\n句子：The demurrage charge is high."
    assert llm.json_calls[0]["system"] == gloss.SYSTEM


@_run_async
async def test_gloss_word_truncates_context_and_handles_failures():
    llm = FakeLLM(payload={"gloss_zh": "释义", "pos": "v."})
    await gloss.gloss_word("work", "x" * 300, llm)
    assert llm.json_calls[0]["user"] == "单词：work\n句子：" + "x" * 200

    # mock 模式不编造释义，直接 None，也不调模型
    mocked = FakeLLM(mock=True)
    assert await gloss.gloss_word("work", "", mocked) is None
    assert mocked.json_calls == []

    # 调用失败不阻塞存词
    broken = FakeLLM(error=RuntimeError("timeout"))
    assert await gloss.gloss_word("work", "I work here.", broken) is None

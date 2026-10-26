"""情景英语接口：统一挂载在 ``/api/c/english``（主站能力协议已统一加登录依赖）。

移植自 ``.tmp/etutor-src/api/src/routes.ts``，按产品决定删掉支付 / 会员 / 订单 /
转移码 / 匿名用户相关接口，配额改为读取能力设置（``settings["daily_quota"]``）。

保留的路由：

- 元信息与情景：``/health`` ``/scenarios`` ``/scenarios/{id}`` ``/scenarios/{id}/conversations``
- 会话：``/conversations/{id}``
- 核心：``POST /chat``（SSE，编排见 :func:`_chat_stream`）
- 学习闭环：``/knowledge/{code}`` ``/errors`` ``/memory/{scenario_id}``
- 生词：``POST /vocab`` ``GET /vocab`` ``POST /vocab/review``
- 资料：``POST /documents`` ``POST /documents/upload`` ``DELETE /documents/{id}`` ``GET /documents``
- 偏好契约：``GET /contract`` ``PUT /contract``
- 成本看板：``/stats``

约定（与 TS 版保持一致）：DB 行用 snake_case，SSE ``meta`` 等事件载荷用 camelCase；
时间全部是 UTC ISO-8601 字符串；JSON 列在 Python 侧用 ``store.json_load/json_dump`` 转换。
"""
from __future__ import annotations

import asyncio
import dataclasses
import inspect
import logging
import re
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

from fastapi import APIRouter, Body, Depends, File, Query, UploadFile
from fastapi.responses import StreamingResponse

from ...core.auth import current_user
from ...core.errors import ApiError
from ...models import User
from . import llm as english_llm
from . import metrics, store
from . import settings as english_settings
from .agents import contract as contract_mod
from .agents import extract as extract_mod
from .agents import memory as memory_mod
from .agents import schedule as schedule_mod
from .agents import summary as summary_mod
from .agents.analyst import analyze
from .agents.budget import budget_decision, check_budget, cost_of, est_tokens
from .agents.errors import (
    list_patterns,
    record_analysis,
    refresh_resolved,
    weak_codes,
    weak_prompt_hints,
)
from .agents.gloss import gloss_word
from .agents.knowledge import get_or_create_card
from .agents.partner import build_system_prompt, to_messages
from .agents.planner import pick_topic, plan_scenario
from .agents.quality import measure_reply, needs_repair, penalty_of, repair_hint
from .agents.rag import Chunk, chunk_text, rank_bm25, render_reference
from .agents.taxonomy import ERROR_CODES
from .agents.vocab import candidates, count_hits, must_use_words
from .sse import SSE_HEADERS, iter_coalesced, sse

log = logging.getLogger(__name__)

router = APIRouter(tags=["english"])

#: 20 秒没有新 token 就判上游卡死（原项目实测出现过 8 分钟无输出的请求）
STALL_SECONDS = 20.0
#: 角色扮演回复的 token 上限：系统提示本身也占额度，给足余量避免被截断
STREAM_MAX_TOKENS = 1600
#: 纠错 / 记忆最多等这么久，拿不到就少发事件，绝不拖住 done
TAIL_WAIT_SECONDS = 3.0
#: 摘要后台任务的条数窗口
SUMMARY_MAX_TAIL_CHARS = 1400

CEFRS: tuple[str, ...] = ("A2", "B1", "B2", "C1")

# 后台任务需要一个强引用，否则可能被 GC 掉（摘要不阻塞 done，但也不能凭空消失）
_BACKGROUND_TASKS: set[asyncio.Task] = set()


# ================================================================ 通用小工具


def _uid(user: User) -> int:
    return int(user.id or 0)


def _elapsed_ms(started: float) -> int:
    return int((time.perf_counter() - started) * 1000)


async def _maybe_await(value: Any) -> Any:
    """agents 里个别函数允许同步或 async 实现（Lead 的 capability 也这么兜底）。"""
    if inspect.isawaitable(value):
        return await value
    return value


async def _call(fn: Any, *args: Any, **kwargs: Any) -> Any:
    return await _maybe_await(fn(*args, **kwargs))


def _field(obj: Any, name: str, default: Any = None) -> Any:
    """字段读取：兼容 dataclass / pydantic / TypedDict / dict 四种返回类型。"""
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(name, default)
    try:
        return getattr(obj, name, default)
    except Exception:  # noqa: BLE001 - 防御模型自定义 __getattr__
        return default


def _jsonable(value: Any) -> Any:
    """把 dataclass / pydantic / dict 统一成可 JSON 序列化的结构。"""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_jsonable(item) for item in value]
    dump = getattr(value, "model_dump", None)
    if callable(dump):
        try:
            return _jsonable(dump())
        except Exception:  # noqa: BLE001
            pass
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return _jsonable(dataclasses.asdict(value))
    if hasattr(value, "__dict__"):
        return _jsonable(vars(value))
    return value


def _json_list(value: Any) -> list[Any]:
    """JSON 列容错转 list：DB 里是 TEXT，agent 返回时可能是真 list。"""
    data = store.json_load(value, []) if isinstance(value, str) else value
    if isinstance(data, list):
        return data
    if isinstance(data, tuple):
        return list(data)
    if data is None or data == "":
        return []
    return [data]


def _as_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _bad(message: str, code: str = "BAD_INPUT") -> ApiError:
    return ApiError(message, code=code, status=400)


def _forbid_input(body: Any) -> dict:
    """请求体必须是 JSON 对象；否则按 TS 的 BAD_INPUT 返回 400。"""
    if not isinstance(body, dict):
        raise _bad("参数不合法")
    return body


def _read_list_field(row: dict, key: str) -> list[Any]:
    return _json_list(row.get(key))


# ================================================================ 读取辅助


def _today_turns(user_id: int) -> int:
    row = store.one(
        "SELECT count(*) AS n FROM english_messages m "
        "JOIN english_conversations c ON c.id = m.conversation_id "
        "WHERE c.user_id = :user_id AND m.role = 'assistant' AND m.created_at >= :day_start",
        user_id=user_id,
        day_start=store.day_start_iso(),
    )
    return _as_int((row or {}).get("n"))


async def _load_contract(user_id: int) -> contract_mod.Contract:
    row = store.one("SELECT * FROM english_contracts WHERE user_id = :user_id", user_id=user_id)
    if not row:
        # 返回默认值的独立副本，避免调用方改到模块级常量
        return contract_mod.Contract()
    return contract_mod.Contract(
        must_use_words=[str(x) for x in _read_list_field(row, "must_use_words")],
        grammar_focus=[str(x) for x in _read_list_field(row, "grammar_focus")],
        correction_intensity=str(row.get("correction_intensity") or "medium"),
        difficulty_delta=_as_int(row.get("difficulty_delta")),
        max_reply_words=_as_int(row.get("max_reply_words"), 90) or 90,
    )


async def _save_contract(user_id: int, contract: contract_mod.Contract) -> None:
    store.execute(
        """INSERT INTO english_contracts
               (user_id, must_use_words, grammar_focus, correction_intensity,
                difficulty_delta, max_reply_words, updated_at)
           VALUES (:user_id, :words, :focus, :intensity, :delta, :max_words, :now)
           ON CONFLICT (user_id) DO UPDATE SET
               must_use_words = :words, grammar_focus = :focus,
               correction_intensity = :intensity, difficulty_delta = :delta,
               max_reply_words = :max_words, updated_at = :now""",
        user_id=user_id,
        words=store.json_dump(contract.must_use_words),
        focus=store.json_dump(contract.grammar_focus),
        intensity=contract.correction_intensity,
        delta=contract.difficulty_delta,
        max_words=contract.max_reply_words,
        now=store.now_iso(),
    )


async def _load_memory(user_id: int, scenario_id: str) -> memory_mod.MemoryState:
    row = store.one(
        "SELECT state, revision FROM english_scenario_memory "
        "WHERE user_id = :user_id AND scenario_id = :scenario_id",
        user_id=user_id,
        scenario_id=scenario_id,
    )
    if not row:
        return memory_mod.normalize_memory(None)
    state = store.json_load(row.get("state"), {}) or {}
    merged = memory_mod.normalize_memory(state)
    # revision 以独立列为准（state JSON 里也有一份，列更可信）
    merged["revision"] = _as_int(row.get("revision"), merged.get("revision", 0))
    return merged


async def _save_memory(user_id: int, scenario_id: str, state: Any) -> None:
    payload = _jsonable(state)
    if not isinstance(payload, dict):
        payload = {}
    revision = _as_int(payload.get("revision"))
    store.execute(
        """INSERT INTO english_scenario_memory (user_id, scenario_id, state, revision, updated_at)
           VALUES (:user_id, :scenario_id, :state, :revision, :now)
           ON CONFLICT (user_id, scenario_id) DO UPDATE SET
               state = :state, revision = :revision, updated_at = :now""",
        user_id=user_id,
        scenario_id=scenario_id,
        state=store.json_dump(payload),
        revision=revision,
        now=store.now_iso(),
    )


async def _retrieve_for(user_id: int, scenario_id: str, query: str) -> dict:
    """资料检索（BM25）。没有资料的人占多数：先做一次极轻的计数再扫切块。"""
    empty: dict[str, Any] = {"block": "", "sources": []}
    count_row = store.one(
        "SELECT count(*) AS n FROM english_documents "
        "WHERE user_id = :user_id AND (scenario_id = :scenario_id OR scenario_id IS NULL)",
        user_id=user_id,
        scenario_id=scenario_id,
    )
    if _as_int((count_row or {}).get("n")) == 0:
        return empty

    rows = store.q(
        """SELECT c.id, c.document_id, c.idx, c.content, d.filename
           FROM english_doc_chunks c JOIN english_documents d ON d.id = c.document_id
           WHERE d.user_id = :user_id AND (d.scenario_id = :scenario_id OR d.scenario_id IS NULL)
           ORDER BY d.created_at DESC LIMIT 150""",
        user_id=user_id,
        scenario_id=scenario_id,
    )
    if not rows:
        return empty

    chunks = [
        Chunk(
            id=str(row.get("id") or ""),
            document_id=str(row.get("document_id") or ""),
            idx=_as_int(row.get("idx")),
            content=str(row.get("content") or ""),
        )
        for row in rows
    ]
    hits = await _maybe_await(rank_bm25(query, chunks, 3))
    if not hits:
        return empty

    titles = {str(row.get("document_id") or ""): str(row.get("filename") or "document") for row in rows}
    sources: list[dict] = []
    for item in hits:
        item_chunk, score = item if isinstance(item, (tuple, list)) else (item, 0.0)
        sources.append(
            {
                "title": titles.get(str(_field(item_chunk, "document_id", "")) or "", "document"),
                "part": _as_int(_field(item_chunk, "idx")) + 1,
                "score": round(float(score or 0.0), 2),
            }
        )
    block = await _maybe_await(render_reference(hits, titles))
    return {"block": block or "", "sources": sources}


def _filter_saved(user_id: int, words: list[str]) -> list[str]:
    """已经存进词库的词不再重复推荐，否则学生点了没反应，会以为坏了。"""
    if not words:
        return []
    rows = store.q("SELECT lemma FROM english_vocab_items WHERE user_id = :user_id", user_id=user_id)
    saved = {str(row.get("lemma") or "") for row in rows}
    return [word for word in words if word not in saved]


def _top_flags(flags: list[str]) -> list[dict]:
    counts: dict[str, int] = {}
    for flag in flags:
        counts[flag] = counts.get(flag, 0) + 1
    ordered = sorted(counts.items(), key=lambda item: item[1], reverse=True)[:5]
    return [{"flag": flag, "n": n} for flag, n in ordered]


def _health_payload() -> dict:
    """把 metrics.snapshot() 收敛成接口约定的 {degraded, okCount, failCount, rates}。"""
    snap = metrics.snapshot() or {}
    if "ok" in snap or "okCount" in snap:
        ok_count = _as_int(snap.get("ok", snap.get("okCount")))
        fail_count = _as_int(snap.get("fail", snap.get("failCount")))
        rates = snap.get("rates") or {}
    else:  # 与 TS 一致的 counters/chains 结构
        chains = snap.get("chains") or []
        ok_count = sum(_as_int(chain.get("ok")) for chain in chains)
        fail_count = sum(_as_int(chain.get("fail")) for chain in chains)
        rates = {str(chain.get("name")): chain.get("rate", 0.0) for chain in chains}
    return {
        "degraded": bool(snap.get("degraded")),
        "okCount": ok_count,
        "failCount": fail_count,
        "rates": rates,
    }


# ================================================================ 后台任务


def _spawn_background(coro) -> None:
    task = asyncio.create_task(coro)
    _BACKGROUND_TASKS.add(task)
    task.add_done_callback(_BACKGROUND_TASKS.discard)


async def _maybe_summarize(conversation_id: str, user_id: int) -> bool:
    """L2 摘要：把最早那批未摘要的消息压成纪要，失败就用骨架文本兜底。返回是否真的压了。"""
    meta = store.one(
        "SELECT rolling_summary, summarized_upto FROM english_conversations WHERE id = :id",
        id=conversation_id,
    )
    if not meta:
        return False
    count_row = store.one(
        "SELECT count(*) AS n FROM english_messages WHERE conversation_id = :id",
        id=conversation_id,
    )
    total = _as_int((count_row or {}).get("n"))
    upto = _as_int(meta.get("summarized_upto"))
    if not summary_mod.should_summarize(total, upto):
        return False

    rows = store.q(
        "SELECT role, content_md FROM english_messages WHERE conversation_id = :id "
        "ORDER BY created_at ASC LIMIT 8 OFFSET :upto",
        id=conversation_id,
        upto=upto,
    )
    if not rows:
        return False

    fresh: str
    try:
        llm = english_llm.get_llm(user_id, "planner")
        fresh = await _call(summary_mod.summarize_with, llm, rows, 30.0)
    except Exception as exc:  # noqa: BLE001 - 摘要失败不阻塞对话
        log.warning("english summary 失败（用骨架兜底）: %s", exc)
        fresh = await _call(summary_mod.fallback_summary, rows)

    previous = str(meta.get("rolling_summary") or "").strip()
    merged = f"{previous}\n{fresh}" if previous else str(fresh or "")
    merged = merged[-SUMMARY_MAX_TAIL_CHARS:]
    store.execute(
        "UPDATE english_conversations SET rolling_summary = :summary, summarized_upto = :upto WHERE id = :id",
        summary=merged,
        upto=upto + len(rows),
        id=conversation_id,
    )
    log.info("english summary 更新: conversation=%s covered=%s chars=%s", conversation_id, upto + len(rows), len(merged))
    return True


async def _summarize_background(conversation_id: str, user_id: int) -> None:
    try:
        done = await _maybe_summarize(conversation_id, user_id)
        metrics.bump("summary_ok" if done else "summary_skip")
    except Exception as exc:  # noqa: BLE001
        metrics.bump("summary_fail")
        log.warning("english summary 后台任务失败: %s", exc)


async def _run_analysis(text: str, user_id: int) -> Any:
    """纠错与学生输入并行：它不参与首字，失败也不影响对话。"""
    try:
        llm = english_llm.get_llm(user_id, "planner")
        result = await _call(analyze, text, llm)
        metrics.bump("analyst_ok")
        return result
    except Exception as exc:  # noqa: BLE001
        metrics.bump("analyst_fail")
        log.warning("english analyst 失败: %s", exc)
        return None


async def _run_memory(
    *,
    user_id: int,
    state: Any,
    topic_title: str,
    turn: int,
    beats: list[str],
    last_user: str,
    last_reply: str,
) -> Any:
    try:
        llm = english_llm.get_llm(user_id, "planner")
        result = await _call(
            memory_mod.keep_memory,
            state=state,
            topic_title=topic_title,
            turn=turn,
            beats=beats,
            last_user=last_user,
            last_reply=last_reply,
            llm=llm,
        )
        metrics.bump("memory_ok")
        return result
    except Exception as exc:  # noqa: BLE001
        metrics.bump("memory_fail")
        log.warning("english memory 失败: %s", exc)
        return None


async def _wait_pair(first: asyncio.Task, second: asyncio.Task, timeout: float) -> tuple[Any, Any]:
    """最多等 timeout 秒；超时的任务直接取消（结果本来就打算丢弃）。"""
    done, pending = await asyncio.wait({first, second}, timeout=timeout)
    for task in pending:
        task.cancel()
    if pending:
        await asyncio.gather(*pending, return_exceptions=True)

    def _result(task: asyncio.Task) -> Any:
        if task not in done or task.cancelled():
            return None
        try:
            return task.result()
        except Exception:  # noqa: BLE001 - 任务内部已 catch，这里只是兜底
            return None

    return _result(first), _result(second)


async def _generate_once(llm: Any, system: str, messages: list[dict]) -> str | None:
    """重写用：一次性收集全文，不走 SSE（结果用 replace 事件整体替换）。"""
    try:
        parts: list[str] = []
        stream = llm.stream(system, messages, max_tokens=STREAM_MAX_TOKENS)
        stream = await _maybe_await(stream)
        async for delta in stream:
            if delta:
                parts.append(delta)
        return "".join(parts)
    except Exception as exc:  # noqa: BLE001 - 重写失败就保留原回复
        log.warning("english repair 重写失败: %s", exc)
        return None


def _unpack_analysis(result: Any) -> tuple[Any, str] | None:
    """兼容 `(analysis, provider)` 与 `{analysis, provider}` 两种返回形状。"""
    if result is None:
        return None
    if isinstance(result, (tuple, list)) and len(result) == 2:
        return result[0], str(result[1] or "none")
    if isinstance(result, dict):
        return result.get("analysis"), str(result.get("provider") or "none")
    return result, "none"


def _unpack_memory(result: Any) -> tuple[bool, Any] | None:
    """兼容 `(changed, state)` 与 `{changed, state}` 两种返回形状。"""
    if result is None:
        return None
    if isinstance(result, (tuple, list)) and len(result) == 2:
        return bool(result[0]), result[1]
    if isinstance(result, dict) and "changed" in result:
        return bool(result.get("changed")), result.get("state")
    return None


# ================================================================ 健康与情景


@router.get("/health")
async def health(user: User = Depends(current_user)) -> dict:
    """自报健康：辅助链路失败率超标时 degraded=true；provider 供顶栏展示。"""
    row = store.one("SELECT count(*) AS n FROM english_scenarios")
    try:
        provider = english_llm.get_llm(_uid(user), "partner").name
    except ApiError:
        provider = "unavailable"  # 没配供应商时页面仍要能打开
    except Exception:  # noqa: BLE001
        log.exception("english health 读取 provider 失败")
        provider = "unavailable"
    return {
        "ok": True,
        "scenarios": _as_int((row or {}).get("n")),
        "provider": provider,
        **_health_payload(),
    }


@router.get("/scenarios")
async def list_scenarios(user: User = Depends(current_user)) -> dict:  # noqa: ARG001
    rows = store.q(
        """SELECT s.id, s.slug, s.title_zh, s.title_en, s.cefr, s.domain,
                  (SELECT count(*) FROM english_topics t WHERE t.scenario_id = s.id) AS topic_count
           FROM english_scenarios s ORDER BY s.created_at DESC LIMIT 50"""
    )
    return {"items": rows}


@router.post("/scenarios")
async def create_scenario(body: Any = Body(...), user: User = Depends(current_user)) -> dict:
    payload = _forbid_input(body)
    domain = payload.get("domain")
    cefr = payload.get("cefr") or "B1"
    if not isinstance(domain, str) or not (2 <= len(domain.strip()) <= 60):
        raise _bad("领域或等级不合法")
    if cefr not in CEFRS:
        raise _bad("领域或等级不合法")

    llm = english_llm.get_llm(_uid(user), "planner")
    plan = await _call(plan_scenario, domain.strip(), cefr, llm)
    result = _jsonable(plan)
    log.info(
        "english scenario.created: slug=%s topics=%s provider=%s",
        _field(result, "slug"),
        len(_json_list(_field(result, "topics", []))),
        _field(result, "provider"),
    )
    return result


@router.get("/scenarios/{scenario_id}/conversations")
async def scenario_conversations(scenario_id: str, user: User = Depends(current_user)) -> dict:
    """情景下的历史会话：刷新页面后能接着聊。"""
    rows = store.q(
        """SELECT c.id, c.created_at, c.last_message_at, t.title AS topic_title,
                  (SELECT count(*) FROM english_messages m
                    WHERE m.conversation_id = c.id AND m.role = 'assistant') AS turns
           FROM english_conversations c LEFT JOIN english_topics t ON t.id = c.topic_id
           WHERE c.scenario_id = :scenario_id AND c.user_id = :user_id
           ORDER BY (c.last_message_at IS NULL) ASC, c.last_message_at DESC, c.created_at DESC
           LIMIT 10""",
        scenario_id=scenario_id,
        user_id=_uid(user),
    )
    return {"items": rows}


@router.get("/scenarios/{scenario_id}")
async def scenario_detail(scenario_id: str, user: User = Depends(current_user)) -> dict:  # noqa: ARG001
    scenario = store.one("SELECT * FROM english_scenarios WHERE id = :id", id=scenario_id)
    if not scenario:
        raise ApiError("情景不存在", code="NOT_FOUND", status=404)
    rows = store.q(
        "SELECT id, title, beats, target_tenses, target_lexis, difficulty, used_count "
        "FROM english_topics WHERE scenario_id = :scenario_id "
        "ORDER BY used_count ASC, created_at ASC",
        scenario_id=scenario_id,
    )
    topics = [
        {
            "id": row.get("id"),
            "title": row.get("title"),
            "beats": _read_list_field(row, "beats"),
            "target_tenses": _read_list_field(row, "target_tenses"),
            "target_lexis": _read_list_field(row, "target_lexis"),
            "difficulty": row.get("difficulty"),
            "used_count": _as_int(row.get("used_count")),
        }
        for row in rows
    ]
    return {**_jsonable(scenario), "topics": topics}


@router.get("/conversations/{conversation_id}")
async def conversation_detail(conversation_id: str, user: User = Depends(current_user)) -> dict:
    conv = store.one(
        "SELECT * FROM english_conversations WHERE id = :id AND user_id = :user_id",
        id=conversation_id,
        user_id=_uid(user),
    )
    if not conv:
        raise ApiError("会话不存在", code="NOT_FOUND", status=404)
    messages = store.q(
        "SELECT id, role, content_md, created_at FROM english_messages "
        "WHERE conversation_id = :id ORDER BY created_at",
        id=conversation_id,
    )
    # 刷新页面后纠错下划线不能丢：SSE 的 annotations 只在当场有效，
    # 这里一次性把该会话的错误事件按 message_id 挂回 user 消息（不做 N+1 查询）。
    error_rows = store.q(
        """SELECT e.message_id, e.code, e.span, e.correction, e.explain_zh,
                  e.severity, e.confidence
           FROM english_error_events e
           JOIN english_messages m ON m.id = e.message_id
           WHERE m.conversation_id = :conversation_id AND e.user_id = :user_id
           ORDER BY e.created_at""",
        conversation_id=conversation_id,
        user_id=_uid(user),
    )
    errors_by_message: dict[str, list[dict]] = {}
    for row in error_rows:
        message_id = str(row.get("message_id") or "")
        errors_by_message.setdefault(message_id, []).append(
            {
                "code": row.get("code"),
                "span": row.get("span"),
                "correction": row.get("correction"),
                "explain_zh": row.get("explain_zh"),
                "severity": row.get("severity"),
                "confidence": row.get("confidence"),
            }
        )
    for message in messages:
        # assistant 消息不挂纠错（纠错针对的是学生输入）
        if message.get("role") == "user":
            message["errors"] = errors_by_message.get(str(message.get("id") or ""), [])
    return {**_jsonable(conv), "messages": messages}


# ================================================================ chat（SSE）


class _StreamStalled(Exception):
    """上游 20 秒没有任何新 token。"""


@dataclass
class _ChatContext:
    """一次 /chat 请求的编排现场（prep 完成后交给流式生成器）。"""

    user_id: int
    settings: dict
    scenario: dict
    conv: dict
    topic: dict
    message: str
    history: list[dict]
    user_msg_id: str
    analysis_task: asyncio.Task
    contract: Any
    must_use: list[str]
    memory: Any
    reference: dict
    effective_cefr: str
    system: str
    topic_beats: list[str] = field(default_factory=list)


def _parse_chat_body(body: Any) -> tuple[str, str | None, str | None, str]:
    payload = _forbid_input(body)
    scenario_id = payload.get("scenarioId")
    conversation_id = payload.get("conversationId")
    topic_id = payload.get("topicId")
    message = payload.get("message")

    if not isinstance(scenario_id, str) or not scenario_id.strip():
        raise _bad("参数不合法")
    if conversation_id is not None and not isinstance(conversation_id, str):
        raise _bad("参数不合法")
    if topic_id is not None and not isinstance(topic_id, str):
        raise _bad("参数不合法")
    if not isinstance(message, str) or not (1 <= len(message) <= 800):
        raise _bad("参数不合法")
    return scenario_id.strip(), conversation_id, topic_id, message


@router.post("/chat")
async def chat(body: Any = Body(...), user: User = Depends(current_user)) -> StreamingResponse:
    """一轮角色扮演对话。SSE 事件：delta → (replace) → (annotations) → meta → done / error。"""
    started = time.perf_counter()
    user_id = _uid(user)
    capability_settings = english_settings.get_settings(user_id)

    # 1. 配额（来自能力设置，不再有 entitlements 表）
    quota = _as_int(capability_settings.get("daily_quota"), 30)
    used_today = _today_turns(user_id)
    if used_today >= quota:
        raise ApiError(
            f"今日 {quota} 轮已用完，明天再来或调整能力设置里的每日上限",
            code="QUOTA_EXCEEDED",
            status=429,
            detail={"remaining": 0},
        )

    # 2. 入参 → 情景 → 会话（校验归属）→ 话题
    scenario_id, conversation_id, topic_id, message = _parse_chat_body(body)

    scenario = store.one(
        "SELECT id, title_en, cefr FROM english_scenarios WHERE id = :id",
        id=scenario_id,
    )
    if not scenario:
        raise ApiError("情景不存在", code="NOT_FOUND", status=404)

    conv: dict | None = None
    if conversation_id:
        conv = store.one(
            "SELECT id, topic_id, rolling_summary FROM english_conversations "
            "WHERE id = :id AND user_id = :user_id",
            id=conversation_id,
            user_id=user_id,
        )
        if not conv:
            raise ApiError("会话不属于当前用户", code="FORBIDDEN", status=403)

    topic: dict | None = None
    if topic_id:
        topic = store.one(
            "SELECT id, title, beats, target_tenses, target_lexis, difficulty FROM english_topics "
            "WHERE id = :id AND scenario_id = :scenario_id",
            id=topic_id,
            scenario_id=scenario["id"],
        )
    if topic is None and conv and conv.get("topic_id"):
        topic = store.one(
            "SELECT id, title, beats, target_tenses, target_lexis, difficulty FROM english_topics "
            "WHERE id = :id",
            id=conv["topic_id"],
        )
    if topic is None:
        topic = await _call(pick_topic, scenario["id"])
    if not topic:
        raise ApiError("该情景还没有话题，请先重新生成", code="NO_TOPIC", status=400)

    now = store.now_iso()
    if not conv:
        new_conv_id = store.new_id()
        store.execute(
            "INSERT INTO english_conversations "
            "(id, user_id, scenario_id, topic_id, rolling_summary, summarized_upto, created_at, last_message_at) "
            "VALUES (:id, :user_id, :scenario_id, :topic_id, NULL, 0, :created_at, NULL)",
            id=new_conv_id,
            user_id=user_id,
            scenario_id=scenario["id"],
            topic_id=topic["id"],
            created_at=now,
        )
        store.execute(
            "UPDATE english_topics SET used_count = used_count + 1, last_used_at = :now WHERE id = :id",
            now=now,
            id=topic["id"],
        )
        conv = {"id": new_conv_id, "topic_id": topic["id"], "rolling_summary": None}

    # 历史取最近 12 条再反转（与 TS 一致）
    history = store.q(
        "SELECT role, content_md FROM english_messages WHERE conversation_id = :id "
        "ORDER BY created_at DESC LIMIT 12",
        id=conv["id"],
    )
    history.reverse()

    user_msg_id = store.new_id()
    store.execute(
        "INSERT INTO english_messages (id, conversation_id, role, content_md, created_at) "
        "VALUES (:id, :conversation_id, 'user', :content_md, :created_at)",
        id=user_msg_id,
        conversation_id=conv["id"],
        content_md=message,
        created_at=now,
    )
    store.execute(
        "UPDATE english_conversations SET last_message_at = :now WHERE id = :id",
        now=now,
        id=conv["id"],
    )

    # 3. 纠错先起跑（不参与首字）；其余五件事彼此独立，并发准备
    analysis_task = asyncio.create_task(_run_analysis(message, user_id))
    prep_started = time.perf_counter()
    try:
        contract, must_use, memory, weak_code_list, reference = await asyncio.gather(
            _call(_load_contract, user_id),
            _call(must_use_words, user_id, 3),
            _call(_load_memory, user_id, scenario["id"]),
            _call(weak_codes, user_id, 3),
            _call(_retrieve_for, user_id, scenario["id"], message),
        )
    except BaseException:
        analysis_task.cancel()
        raise
    prep_ms = _elapsed_ms(prep_started)

    words = list(dict.fromkeys([*(_field(contract, "must_use_words", []) or []), *list(must_use or [])]))[:3]
    weak = list(dict.fromkeys([*(_field(contract, "grammar_focus", []) or []), *list(weak_code_list or [])]))[:3]
    effective_cefr, _clamped = contract_mod.apply_delta(scenario["cefr"], _as_int(_field(contract, "difficulty_delta")))
    topic_beats = [str(beat) for beat in _read_list_field(topic, "beats")]
    max_reply_words = _as_int(_field(contract, "max_reply_words"), 90) or 90

    system = build_system_prompt(
        scenario_title=str(scenario.get("title_en") or ""),
        topic_title=str(topic.get("title") or ""),
        beats=topic_beats,
        target_tenses=[str(item) for item in _read_list_field(topic, "target_tenses")],
        target_lexis=[str(item) for item in _read_list_field(topic, "target_lexis")],
        cefr=effective_cefr,
        turn=len(history) // 2,
        must_use=words,
        memory_block=await _call(memory_mod.render_memory, memory),
        history_summary=await _call(summary_mod.render_summary, conv.get("rolling_summary"), 0),
        weak_hints="\n".join(
            part for part in (weak_prompt_hints(weak), contract_mod.contract_hints(contract)) if part
        ),
        reference_block=str((reference or {}).get("block") or ""),
        max_reply_words=max_reply_words,
    )

    log.info(
        "english chat.prep: prep_ms=%s prep_total_ms=%s has_ref=%s",
        prep_ms,
        _elapsed_ms(started),
        bool((reference or {}).get("block")),
    )

    ctx = _ChatContext(
        user_id=user_id,
        settings=capability_settings,
        scenario=scenario,
        conv=conv,
        topic=topic,
        message=message,
        history=history,
        user_msg_id=user_msg_id,
        analysis_task=analysis_task,
        contract=contract,
        must_use=words,
        memory=memory,
        reference=reference or {"block": "", "sources": []},
        effective_cefr=effective_cefr,
        system=system,
        topic_beats=topic_beats,
    )
    return StreamingResponse(
        _chat_stream(ctx),
        media_type="text/event-stream",
        headers=SSE_HEADERS,
    )


async def _chat_stream(ctx: _ChatContext) -> AsyncIterator[str]:
    """SSE 编排（忠实移植 routes.ts 第 5 步之后的流程）。"""
    started = time.perf_counter()
    ttft: int | None = None
    text = ""
    finished = False
    llm: Any = None
    coalesced: Any = None
    memory_state: Any = ctx.memory
    annotations: list[dict] = []
    annotations_provider = "none"

    try:
        # 4. 预算降级：月累计超 90% 换 fallback 模型
        try:
            budget = await _call(check_budget, ctx.user_id, ctx.settings)
        except Exception as exc:  # noqa: BLE001 - 预算判断失败不该挡住对话
            log.warning("english budget 判断失败（按不降级处理）: %s", exc)
            budget = {"degrade": False}
        degrade = bool(_field(budget, "degrade", False))
        llm = english_llm.get_llm(ctx.user_id, "partner", degrade=degrade)

        messages = [*to_messages(ctx.history), {"role": "user", "content": ctx.message}]
        source = llm.stream(ctx.system, messages, max_tokens=STREAM_MAX_TOKENS)
        source = await _maybe_await(source)
        coalesced = iter_coalesced(source)
        iterator = coalesced.__aiter__()

        # 5. 流式期间：20s 无新 token 看门狗 + 下行合并 + 记录 ttft
        while True:
            try:
                chunk = await asyncio.wait_for(anext(iterator), timeout=STALL_SECONDS)
            except StopAsyncIteration:
                break
            except asyncio.TimeoutError:
                raise _StreamStalled() from None
            if not chunk:
                continue
            if ttft is None:
                ttft = _elapsed_ms(started)
            text += chunk
            yield sse("delta", {"text": chunk})

        # 6. 质量测量：先流式给结果（首字不能等），发现问题再静默重写一次
        verdict = await _maybe_await(measure_reply(text, ctx.effective_cefr))
        if _field(verdict, "flags"):
            log.info("english reply.flags: flags=%s cefr=%s", _field(verdict, "flags"), ctx.effective_cefr)

        if bool(ctx.settings.get("repair_enabled", True)) and needs_repair(verdict):
            repaired = await _generate_once(
                llm,
                ctx.system,
                [
                    *to_messages(ctx.history),
                    {"role": "user", "content": ctx.message},
                    {"role": "assistant", "content": text},
                    {"role": "user", "content": repair_hint(verdict)},
                ],
            )
            if repaired:
                verdict2 = await _maybe_await(measure_reply(repaired, ctx.effective_cefr))
                if penalty_of(verdict2) > penalty_of(verdict):
                    log.info(
                        "english reply.repaired: before=%s after=%s",
                        _field(verdict, "flags"),
                        _field(verdict2, "flags"),
                    )
                    text = repaired
                    verdict = verdict2
                    yield sse("replace", {"text": repaired})

        # 7. 落 assistant 消息（成本按本轮输入/输出粗估）
        latency = _elapsed_ms(started)
        tokens_in = est_tokens(ctx.system) + est_tokens(ctx.message)
        tokens_out = est_tokens(text)
        cost_micros = round(
            cost_of(
                tokens_in,
                tokens_out,
                float(ctx.settings.get("price_in_per_m") or 2.4),
                float(ctx.settings.get("price_out_per_m") or 9.6),
            )
            * 1_000_000
        )
        store.execute(
            """INSERT INTO english_messages
                   (id, conversation_id, role, content_md, model, latency_ms, ttft_ms,
                    tokens_in, tokens_out, cost_micros, metrics, created_at)
               VALUES (:id, :conversation_id, 'assistant', :content_md, :model, :latency_ms,
                       :ttft_ms, :tokens_in, :tokens_out, :cost_micros, :metrics, :created_at)""",
            id=store.new_id(),
            conversation_id=ctx.conv["id"],
            content_md=text,
            model=str(_field(llm, "name", "") or ""),
            latency_ms=latency,
            ttft_ms=ttft,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            cost_micros=cost_micros,
            metrics=store.json_dump(_jsonable(verdict)),
            created_at=store.now_iso(),
        )

        # 8. 摘要后台跑（不阻塞 done）；纠错与记忆最多等 3s
        _spawn_background(_summarize_background(ctx.conv["id"], ctx.user_id))
        memory_task = asyncio.create_task(
            _run_memory(
                user_id=ctx.user_id,
                state=ctx.memory,
                topic_title=str(ctx.topic.get("title") or ""),
                turn=len(ctx.history) // 2,
                beats=ctx.topic_beats,
                last_user=ctx.message,
                last_reply=text,
            )
        )
        analyzed, kept = await _wait_pair(ctx.analysis_task, memory_task, TAIL_WAIT_SECONDS)

        # 9. 错误事件按纠错强度过滤 severity 后逐条落库；零错误也 record_analysis
        intensity = str(_field(ctx.contract, "correction_intensity", "medium"))
        analysis_pair = _unpack_analysis(analyzed)
        if analysis_pair is not None:
            analysis, annotations_provider = analysis_pair
            raw_errors = _field(analysis, "errors", []) or []
            confidence = float(_field(analysis, "confidence", 0.8) or 0.8)
            accepted = [
                err
                for err in raw_errors
                if contract_mod.severity_allowed(intensity, str(_field(err, "severity", "low")))
            ]
            error_now = store.now_iso()
            for err in accepted:
                store.execute(
                    """INSERT INTO english_error_events
                           (id, user_id, message_id, code, span, correction, explain_zh,
                            severity, confidence, created_at)
                       VALUES (:id, :user_id, :message_id, :code, :span, :correction,
                               :explain_zh, :severity, :confidence, :created_at)""",
                    id=store.new_id(),
                    user_id=ctx.user_id,
                    message_id=ctx.user_msg_id,
                    code=str(_field(err, "code", "other")),
                    span=str(_field(err, "span", "")),
                    correction=str(_field(err, "correction", "")),
                    explain_zh=str(_field(err, "explain_zh", "")),
                    severity=str(_field(err, "severity", "low")),
                    confidence=confidence,
                    created_at=error_now,
                )
            annotations = [_jsonable(err) for err in accepted]
            # 零错误也要留痕，否则无法判定「已改正」
            await _call(
                record_analysis,
                ctx.user_id,
                ctx.user_msg_id,
                [str(_field(err, "code", "other")) for err in accepted],
            )

        memory_pair = _unpack_memory(kept)
        if memory_pair is not None:
            changed, new_state = memory_pair
            if changed and new_state is not None:
                await _save_memory(ctx.user_id, ctx.scenario["id"], new_state)
                memory_state = new_state

        # 10. annotations / meta / done
        meta = {
            "conversationId": ctx.conv["id"],
            "topicId": ctx.topic.get("id"),
            "topicTitle": ctx.topic.get("title"),
            "provider": str(_field(llm, "name", "") or ""),
            "ttftMs": ttft,
            "latencyMs": latency,
            "cefr": ctx.effective_cefr,
            "vocabTargets": ctx.must_use,
            "vocabHits": count_hits(text, ctx.must_use),
            "candidates": _filter_saved(
                ctx.user_id, await _maybe_await(candidates(text, 6))
            ),
            "memoryRevision": _as_int(_field(memory_state, "revision")),
            "memoryFacts": _json_list(_field(memory_state, "established_facts", [])),
            "sources": list((ctx.reference or {}).get("sources") or []),
        }
        finished = True
        if annotations or annotations_provider != "none":
            yield sse(
                "annotations",
                {
                    "messageId": ctx.user_msg_id,
                    "errors": annotations,
                    "provider": annotations_provider,
                },
            )
        yield sse("meta", meta)
        yield sse("done", meta)
        log.info(
            "english chat.done: user=%s topic=%s ttft=%s latency=%s provider=%s errors=%s",
            ctx.user_id,
            ctx.topic.get("id"),
            ttft,
            latency,
            meta["provider"],
            len(annotations),
        )

    except asyncio.CancelledError:
        # 客户端断开：静默结束，既不写 error 事件也不刷日志（照抄 TS 的 res.on('close')）
        raise
    except _StreamStalled:
        if not finished:
            log.warning("english chat.stalled: ttft=%s elapsed=%s", ttft, _elapsed_ms(started))
            yield sse("error", {"code": "STALLED", "message": "模型响应超时，请重试", "retryable": True})
    except Exception as exc:  # noqa: BLE001
        if not finished:
            log.exception("english chat.error: %s", exc)
            yield sse("error", {"code": "UPSTREAM_ERROR", "message": "生成失败，请重试", "retryable": True})
    finally:
        if not ctx.analysis_task.done():
            ctx.analysis_task.cancel()
        if coalesced is not None:
            aclose = getattr(coalesced, "aclose", None)
            if callable(aclose):
                try:
                    await aclose()
                except Exception:  # noqa: BLE001 - 清理失败不影响已经发出的帧
                    pass


# ================================================================ 知识卡 / 错误档案 / 记忆


@router.get("/knowledge/{code}")
async def knowledge_card(code: str, user: User = Depends(current_user)) -> dict:
    if code not in ERROR_CODES:
        raise ApiError("未知的错误类型", code="BAD_CODE", status=400)
    llm = english_llm.get_llm(_uid(user), "planner")
    card = await _call(get_or_create_card, _uid(user), code, llm)
    return _jsonable(card)


@router.get("/errors")
async def error_archive(user: User = Depends(current_user)) -> dict:
    """错误档案：聚合 + 趋势 + 已改正判定。"""
    user_id = _uid(user)
    await _call(refresh_resolved, user_id)
    items = await _maybe_await(list_patterns(user_id)) or []
    return {
        "items": items,
        "active": len([item for item in items if not item.get("improved")]),
        "improved": len([item for item in items if item.get("improved")]),
    }


@router.get("/memory/{scenario_id}")
async def scenario_memory(scenario_id: str, user: User = Depends(current_user)) -> dict:
    state = await _load_memory(_uid(user), scenario_id)
    payload = _jsonable(state)
    if not isinstance(payload, dict):
        payload = {}
    return {
        **payload,
        "counts": {
            "facts": len(_json_list(payload.get("established_facts"))),
            "threads": len(_json_list(payload.get("open_threads"))),
            "beats": len(_json_list(payload.get("beats_done"))),
        },
    }


# ================================================================ 生词库


_LEMMA_STRIP_RE = re.compile(r"[^a-z'-]")


def _normalize_lemma(surface: str) -> str:
    """与 TS 版一致：小写后只保留 a-z、撇号与连字符。"""
    return _LEMMA_STRIP_RE.sub("", (surface or "").lower())


def _gloss_fields(gloss: Any) -> tuple[str | None, str | None]:
    if not gloss:
        return None, None
    gloss_zh = _field(gloss, "glossZh", _field(gloss, "gloss_zh"))
    pos = _field(gloss, "pos")
    return (str(gloss_zh) if gloss_zh else None, str(pos) if pos else None)


@router.post("/vocab")
async def save_vocab(body: Any = Body(...), user: User = Depends(current_user)) -> dict:
    payload = _forbid_input(body)
    surface = payload.get("surface")
    context = payload.get("context") or ""
    message_id = payload.get("messageId")
    if not isinstance(surface, str) or not (1 <= len(surface) <= 40):
        raise _bad("单词不合法")
    if not isinstance(context, str) or len(context) > 300:
        raise _bad("单词不合法")
    if message_id is not None and not isinstance(message_id, str):
        raise _bad("单词不合法")

    user_id = _uid(user)
    lemma = _normalize_lemma(surface)
    if len(lemma) < 2:
        raise _bad("单词不合法")

    now = store.now_iso()
    store.execute(
        """INSERT INTO english_vocab_items
               (id, user_id, surface, lemma, context_sentence, message_id, created_at)
           VALUES (:id, :user_id, :surface, :lemma, :context, :message_id, :created_at)
           ON CONFLICT (user_id, lemma) DO NOTHING""",
        id=store.new_id(),
        user_id=user_id,
        surface=surface.strip()[:40],
        lemma=lemma,
        context=context.strip()[:300],
        message_id=message_id,
        created_at=now,
    )
    card = schedule_mod.schedule(schedule_mod.EMPTY, 3)
    store.execute(
        """INSERT INTO english_vocab_states
               (user_id, lemma, stability, difficulty, reps, lapses,
                interval_days, last_review_at, next_review_at)
           VALUES (:user_id, :lemma, :stability, :difficulty, :reps, :lapses,
                   :interval_days, :last_review_at, :next_review_at)
           ON CONFLICT (user_id, lemma) DO NOTHING""",
        user_id=user_id,
        lemma=lemma,
        stability=card.stability,
        difficulty=card.difficulty,
        reps=card.reps,
        lapses=card.lapses,
        interval_days=card.interval_days,
        last_review_at=card.last_review_at,
        next_review_at=card.next_review_at,
    )
    log.info("english vocab.saved: user=%s lemma=%s", user_id, lemma)

    # 释义是复习的前提；生成失败不影响存词（前端显示占位）
    gloss: Any = None
    try:
        llm = english_llm.get_llm(user_id, "planner")
        gloss = await _call(gloss_word, lemma, context.strip() or lemma, llm)
    except Exception as exc:  # noqa: BLE001
        log.warning("english vocab 释义失败: %s", exc)
        gloss = None
    gloss_zh, pos = _gloss_fields(gloss)
    if gloss_zh or pos:
        store.execute(
            "UPDATE english_vocab_items SET gloss_zh = :gloss_zh, pos = :pos "
            "WHERE user_id = :user_id AND lemma = :lemma",
            gloss_zh=gloss_zh,
            pos=pos,
            user_id=user_id,
            lemma=lemma,
        )

    return {
        "lemma": lemma,
        "glossZh": gloss_zh,
        "pos": pos,
        "nextReviewAt": card.next_review_at,
        "intervalDays": card.interval_days,
    }


@router.get("/vocab")
async def list_vocab(user: User = Depends(current_user)) -> dict:
    user_id = _uid(user)
    rows = store.q(
        """SELECT i.lemma, i.surface, i.context_sentence, i.created_at, i.gloss_zh, i.pos,
                  s.interval_days, s.reps, s.lapses, s.last_review_at, s.next_review_at
           FROM english_vocab_items i
           LEFT JOIN english_vocab_states s ON s.user_id = i.user_id AND s.lemma = i.lemma
           WHERE i.user_id = :user_id ORDER BY i.created_at DESC LIMIT 100""",
        user_id=user_id,
    )
    now_iso = store.now_iso()
    items: list[dict] = []
    for row in rows:
        card = schedule_mod.Card(
            stability=0.0,
            difficulty=5.0,
            reps=_as_int(row.get("reps")),
            lapses=_as_int(row.get("lapses")),
            interval_days=_as_int(row.get("interval_days")),
            last_review_at=(str(row["last_review_at"]) if row.get("last_review_at") else None),
            next_review_at=(str(row["next_review_at"]) if row.get("next_review_at") else None),
        )
        next_review_at = card.next_review_at
        items.append(
            {
                "lemma": row.get("lemma"),
                "surface": row.get("surface"),
                "context": row.get("context_sentence"),
                "glossZh": row.get("gloss_zh"),
                "pos": row.get("pos"),
                "reps": card.reps,
                "intervalDays": card.interval_days,
                "nextReviewAt": next_review_at,
                "mastery": round(float(schedule_mod.retrievability(card)), 2),
                "due": (not next_review_at) or str(next_review_at) <= now_iso,
            }
        )
    return {"items": items, "dueCount": len([item for item in items if item["due"]])}


@router.post("/vocab/review")
async def review_vocab(body: Any = Body(...), user: User = Depends(current_user)) -> dict:
    payload = _forbid_input(body)
    lemma = payload.get("lemma")
    rating = payload.get("rating")
    if not isinstance(lemma, str) or not (2 <= len(lemma) <= 40):
        raise _bad("参数不合法")
    if not isinstance(rating, int) or isinstance(rating, bool) or not (1 <= rating <= 4):
        raise _bad("参数不合法")

    user_id = _uid(user)
    row = store.one(
        "SELECT * FROM english_vocab_states WHERE user_id = :user_id AND lemma = :lemma",
        user_id=user_id,
        lemma=lemma,
    )
    if not row:
        raise ApiError("单词不在词库", code="NOT_FOUND", status=404)

    previous = schedule_mod.card_from_row(row)
    following = schedule_mod.schedule(previous, rating)
    store.execute(
        """UPDATE english_vocab_states
              SET stability = :stability, difficulty = :difficulty, reps = :reps,
                  lapses = :lapses, interval_days = :interval_days,
                  last_review_at = :last_review_at, next_review_at = :next_review_at
            WHERE user_id = :user_id AND lemma = :lemma""",
        stability=following.stability,
        difficulty=following.difficulty,
        reps=following.reps,
        lapses=following.lapses,
        interval_days=following.interval_days,
        last_review_at=following.last_review_at,
        next_review_at=following.next_review_at,
        user_id=user_id,
        lemma=lemma,
    )
    return {
        "lemma": lemma,
        "intervalDays": following.interval_days,
        "nextReviewAt": following.next_review_at,
        "mastery": round(float(schedule_mod.retrievability(following)), 2),
    }


# ================================================================ 资料导入


def _insert_document(
    *,
    user_id: int,
    scenario_id: str | None,
    filename: str,
    mime: str,
    text: str,
    chunks: list[str],
) -> str:
    document_id = store.new_id()
    store.execute(
        """INSERT INTO english_documents
               (id, user_id, scenario_id, filename, mime, chars, chunk_count, created_at)
           VALUES (:id, :user_id, :scenario_id, :filename, :mime, :chars, :chunk_count, :created_at)""",
        id=document_id,
        user_id=user_id,
        scenario_id=scenario_id,
        filename=filename,
        mime=mime,
        chars=len(text),
        chunk_count=len(chunks),
        created_at=store.now_iso(),
    )
    for index, chunk in enumerate(chunks):
        store.execute(
            "INSERT INTO english_doc_chunks (id, document_id, idx, content) "
            "VALUES (:id, :document_id, :idx, :content)",
            id=store.new_id(),
            document_id=document_id,
            idx=index,
            content=chunk,
        )
    return document_id


@router.post("/documents")
async def import_document(body: Any = Body(...), user: User = Depends(current_user)) -> dict:
    """纯文本导入（粘贴）。文件名只用于展示，真实内容来自 content。"""
    payload = _forbid_input(body)
    filename = payload.get("filename")
    content = payload.get("content")
    scenario_id = payload.get("scenarioId")
    if not isinstance(filename, str) or not (1 <= len(filename) <= 120):
        raise _bad("文件名或内容不合法")
    if not isinstance(content, str) or not (20 <= len(content) <= 200_000):
        raise _bad("文件名或内容不合法")
    if scenario_id is not None and not isinstance(scenario_id, str):
        raise _bad("文件名或内容不合法")

    lower = filename.lower()
    if lower.endswith((".pdf", ".doc", ".docx", ".ppt", ".pptx")):
        raise ApiError(
            "暂只支持 .txt / .md / .csv，PDF 与 Word 请用「上传文件」或先另存为文本",
            code="UNSUPPORTED_TYPE",
            status=415,
        )

    chunks = await _call(chunk_text, content)
    if not chunks:
        raise ApiError("没有可用的文本内容", code="EMPTY", status=400)

    document_id = _insert_document(
        user_id=_uid(user),
        scenario_id=scenario_id,
        filename=filename,
        mime="text/plain",
        text=content,
        chunks=chunks,
    )
    log.info("english doc.imported: user=%s chunks=%s", _uid(user), len(chunks))
    return {"id": document_id, "filename": filename, "chunks": len(chunks)}


@router.post("/documents/upload")
async def upload_document(
    file: UploadFile = File(...),
    scenario_id: str | None = Query(default=None, alias="scenarioId"),
    user: User = Depends(current_user),
) -> dict:
    """multipart 上传：解析复用主站 library.parsers（docx/pptx/pdf/epub/md/txt/html）。"""
    filename = (file.filename or "upload.txt")[:120]
    data = await file.read()
    if not data:
        raise _bad("文件内容为空")

    try:
        extracted = await _call(extract_mod.extract_text, data, filename)
    except ApiError as exc:
        # 统一成契约里的 EXTRACT_FAILED（agents.extract 内部可能已经这么标了）
        raise ApiError(exc.message or "无法解析该文件", code="EXTRACT_FAILED", status=422) from exc
    except Exception as exc:  # noqa: BLE001
        raise ApiError(f"无法解析该文件：{exc}" if str(exc) else "无法解析该文件", code="EXTRACT_FAILED", status=422) from exc

    text = str(_field(extracted, "text", "") or "")
    kind = str(_field(extracted, "kind", "") or "text")
    if len(text) < 20:
        raise ApiError("没有提取到可用文本，可能是扫描版 PDF", code="EMPTY_TEXT", status=422)

    chunks = await _call(chunk_text, text)
    document_id = _insert_document(
        user_id=_uid(user),
        scenario_id=scenario_id,
        filename=filename,
        mime=kind,
        text=text,
        chunks=chunks,
    )
    log.info(
        "english doc.uploaded: user=%s kind=%s chars=%s chunks=%s",
        _uid(user),
        kind,
        len(text),
        len(chunks),
    )
    return {
        "id": document_id,
        "filename": filename,
        "chunks": len(chunks),
        "chars": len(text),
        "kind": kind,
    }


@router.delete("/documents/{document_id}")
async def delete_document(document_id: str, user: User = Depends(current_user)) -> dict:
    user_id = _uid(user)
    hit = store.one(
        "SELECT id FROM english_documents WHERE id = :id AND user_id = :user_id",
        id=document_id,
        user_id=user_id,
    )
    if not hit:
        raise ApiError("资料不存在", code="NOT_FOUND", status=404)
    # TS 版只删 documents，切块会变孤儿；这里顺手清掉，否则检索会扫到已删资料
    store.execute("DELETE FROM english_doc_chunks WHERE document_id = :id", id=document_id)
    store.execute("DELETE FROM english_documents WHERE id = :id", id=document_id)
    log.info("english doc.deleted: user=%s document=%s", user_id, document_id)
    return {"ok": True}


@router.get("/documents")
async def list_documents(user: User = Depends(current_user)) -> dict:
    rows = store.q(
        """SELECT d.id, d.filename, d.chunk_count, d.created_at, s.title_zh AS scenario
           FROM english_documents d LEFT JOIN english_scenarios s ON s.id = d.scenario_id
           WHERE d.user_id = :user_id ORDER BY d.created_at DESC LIMIT 50""",
        user_id=_uid(user),
    )
    return {"items": rows}


# ================================================================ 偏好契约 / 成本看板


@router.get("/contract")
async def get_contract(user: User = Depends(current_user)) -> dict:
    return _jsonable(await _load_contract(_uid(user)))


@router.put("/contract")
async def put_contract(body: Any = Body(default=None), user: User = Depends(current_user)) -> dict:
    contract, warnings = contract_mod.normalize_contract(body)
    await _save_contract(_uid(user), contract)
    return {"contract": _jsonable(contract), "warnings": warnings}


@router.get("/stats")
async def stats(user: User = Depends(current_user)) -> dict:
    """成本与质量看板（近 24h）。"""
    user_id = _uid(user)
    rows = store.q(
        """SELECT m.latency_ms, m.ttft_ms, m.tokens_in, m.tokens_out, m.cost_micros, m.metrics
           FROM english_messages m JOIN english_conversations c ON c.id = m.conversation_id
           WHERE c.user_id = :user_id AND m.role = 'assistant' AND m.created_at > :since
           ORDER BY m.created_at DESC LIMIT 500""",
        user_id=user_id,
        since=store.iso_ago(days=1),
    )

    def _avg(values: list[int]) -> int:
        return round(sum(values) / len(values)) if values else 0

    latencies = sorted(_as_int(row.get("latency_ms")) for row in rows)
    p95 = latencies[min(len(latencies) - 1, int(len(latencies) * 0.95))] if latencies else 0
    ttfts = [_as_int(row.get("ttft_ms")) for row in rows if _as_int(row.get("ttft_ms")) > 0]
    tokens = sum(_as_int(row.get("tokens_in")) + _as_int(row.get("tokens_out")) for row in rows)
    micros = sum(_as_int(row.get("cost_micros")) for row in rows)

    measured = []
    for row in rows:
        verdict = store.json_load(row.get("metrics"), None)
        if isinstance(verdict, dict) and isinstance(verdict.get("metrics"), dict):
            measured.append(verdict)
    flags = [str(flag) for verdict in measured for flag in (verdict.get("flags") or [])]
    quality = {
        "measured": len(measured),
        "avgWords": _avg([_as_int((verdict.get("metrics") or {}).get("words")) for verdict in measured]),
        "pctEndsWithQuestion": (
            round(
                100
                * len([v for v in measured if (v.get("metrics") or {}).get("endsWithQuestion")])
                / len(measured)
            )
            if measured
            else 0
        ),
        "flagged": len([verdict for verdict in measured if verdict.get("flags")]),
        "topFlags": _top_flags(flags),
    }

    capability_settings = english_settings.get_settings(user_id)
    budget = budget_decision(tokens, _as_int(capability_settings.get("monthly_token_budget")))

    return {
        "turns24h": len(rows),
        "ttftAvg": _avg(ttfts),
        "latencyP95": p95,
        "tokens24h": tokens,
        "costYuan24h": round(micros / 1_000_000, 4),
        "quality": quality,
        "budget": _jsonable(budget),
        "health": metrics.snapshot(),
    }


__all__ = ["router"]

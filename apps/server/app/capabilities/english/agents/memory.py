"""情景记忆（L3 结构化状态）。

为什么不用「把历史拼进 prompt」：20 轮后必然爆 token，而且模型会抓错重点。
结构化状态可以稳定注入、可以断言、可以合并。

照搬 etutor-cn `api/src/agents/memory.ts` 的核心语义：

- 数组字段**永远做并集**：模型这轮「忘了」某条旧事实，服务端不能跟着丢；
- 只有 `setting` 允许覆盖；
- 合并后 revision 自增；
- 每类字段有上限：事实类保留最早的（地基），其余保留最新的（近期更相关）。
"""
from __future__ import annotations

import json
import re
from typing import Annotated, Any, TypedDict

from pydantic import BaseModel, Field

# ---------------------------------------------------------------- 模型输出结构

Item = Annotated[str, Field(min_length=2, max_length=160)]
Lexis = Annotated[str, Field(min_length=2, max_length=40)]


class Patch(BaseModel):
    """模型每轮只输出「新增或变化」。数组字段同时接受单个字符串。

    模型经常把「一条立场」写成 string 而不是 [string]，严格 schema 会让整个记忆更新
    失败（原项目实测每轮都在重试，然后放弃），所以这里两种都收。
    """

    setting: Annotated[str, Field(min_length=2, max_length=200)] | None = None
    established_facts: list[Item] | Item | None = None
    open_threads: list[Item] | Item | None = None
    beats_done: list[Item] | Item | None = None
    student_stance: list[Item] | Item | None = None
    lexis_used: list[Lexis] | Lexis | None = None


class MemoryState(TypedDict):
    setting: str
    established_facts: list[str]
    open_threads: list[str]
    beats_done: list[str]
    student_stance: list[str]
    lexis_used: list[str]
    revision: int


EMPTY_MEMORY: MemoryState = {
    "setting": "",
    "established_facts": [],
    "open_threads": [],
    "beats_done": [],
    "student_stance": [],
    "lexis_used": [],
    "revision": 0,
}

# 每类字段的上限（与 TS 的 CAPS 一致）
CAPS: dict[str, int] = {
    "established_facts": 8,
    "open_threads": 6,
    "beats_done": 8,
    "student_stance": 5,
    "lexis_used": 12,
}

_ARRAY_KEYS: tuple[str, ...] = tuple(CAPS)

# 事实类保留最早的（它们是地基），其余保留最新的（近期更相关）
KEEP_EARLIEST = frozenset({"established_facts"})

_WEEKDAY_RE = re.compile(r"\b(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)\b", re.IGNORECASE)
_NUMBER_RE = re.compile(r"\b\d+\b")
_SENTENCE_RE = re.compile(r"(?<=[.!?])\s+")


# ---------------------------------------------------------------- 读写与合并


def normalize_memory(raw: Any) -> MemoryState:
    """把 DB 里的 JSON / dict / None 归一化成完整 MemoryState（容错旧数据缺列）。"""
    state: MemoryState = {
        "setting": "",
        "established_facts": [],
        "open_threads": [],
        "beats_done": [],
        "student_stance": [],
        "lexis_used": [],
        "revision": 0,
    }
    if not isinstance(raw, dict):
        return state
    setting = raw.get("setting")
    if isinstance(setting, str):
        state["setting"] = setting
    for key in _ARRAY_KEYS:
        value = raw.get(key)
        if isinstance(value, str):
            state[key] = [value] if value else []
        elif isinstance(value, (list, tuple)):
            state[key] = [str(item) for item in value if str(item).strip()]
    try:
        state["revision"] = int(raw.get("revision") or 0)
    except (TypeError, ValueError):
        state["revision"] = 0
    return state


def _patch_dict(patch: Patch | dict | None) -> dict:
    if patch is None:
        return {}
    if isinstance(patch, BaseModel):
        return patch.model_dump(exclude_none=True)
    if isinstance(patch, dict):
        return {key: value for key, value in patch.items() if value is not None}
    return {}


def _as_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, (list, tuple, set)):
        return [str(item) for item in value]
    return []


def union(prev: list[str], next_items: list[str], cap: int, keep_earliest: bool) -> list[str]:
    """去重并集（大小写不敏感），再按 cap 截断：保留最早或最新的一段。"""
    seen: set[str] = set()
    merged: list[str] = []
    for raw in [*prev, *next_items]:
        value = str(raw).strip()
        if not value:
            continue
        key = value.lower()
        if key in seen:
            continue
        seen.add(key)
        merged.append(value)
    if cap <= 0:
        return []
    return merged[:cap] if keep_earliest else merged[-cap:]


def merge_memory(prev: MemoryState | dict | None, patch: Patch | dict | None) -> MemoryState:
    """把 patch 合并进状态：数组求并集 + 上限截断，setting 允许覆盖，revision 自增。"""
    state = normalize_memory(prev)
    data = _patch_dict(patch)

    state["revision"] = state["revision"] + 1

    setting = data.get("setting")
    if isinstance(setting, str) and setting.strip():
        state["setting"] = setting.strip()

    for key in _ARRAY_KEYS:
        incoming = _as_list(data.get(key))
        if not incoming:
            continue
        state[key] = union(state[key], incoming, CAPS[key], key in KEEP_EARLIEST)  # type: ignore[literal-required]
    return state


def is_empty(m: MemoryState | dict | None) -> bool:
    """没有值得注入的故事内容（lexis_used 是词汇统计，不算剧情）。"""
    state = normalize_memory(m)
    return (
        not state["setting"]
        and not state["established_facts"]
        and not state["open_threads"]
        and not state["beats_done"]
        and not state["student_stance"]
    )


# ---------------------------------------------------------------- 模型更新


SYSTEM = """你在维护一段角色扮演对话的"记忆状态"。

只输出**新增或变化**，不要重复已知内容。规则：
1. established_facts：对话里确立的客观事实（数量、日期、人名、金额、地点）。最多 3 条。
2. open_threads：还没解决的分歧或待办。最多 2 条。
3. beats_done：已经完成的剧情节拍，用动词短语。最多 2 条。
4. student_stance：学生的立场或偏好，一句话。最多 1 条。
5. lexis_used：回复中出现的、学习者可能不认识的词。最多 3 个。
6. 没有新增就返回空对象 {}，不要编造。

只输出 JSON。"""


def _mock_patch(*, turn: int, beats: list[str], topic_title: str, last_user: str) -> dict:
    """mock：推进节拍 + 从含数字/星期的句子里抽一条「已确立事实」，保证机制可验收。"""
    index = min(max(0, int(turn)), len(beats) - 1) if beats else -1
    beat = beats[index] if index >= 0 else ""
    patch: dict = {"setting": topic_title, "beats_done": [beat] if beat else []}
    sentence = ""
    for candidate in _SENTENCE_RE.split(last_user or ""):
        if _NUMBER_RE.search(candidate) or _WEEKDAY_RE.search(candidate):
            sentence = candidate.strip()
            break
    if sentence and len(sentence) <= 120:
        patch["established_facts"] = [sentence]
    return patch


async def keep_memory(
    *,
    state: MemoryState | dict | None,
    topic_title: str,
    turn: int,
    beats: list[str],
    last_user: str,
    last_reply: str,
    llm,
) -> tuple[bool, MemoryState]:
    """跑一次记忆更新，返回 (changed, new_state)。

    与原项目一致：revision 每轮自增，所以状态总是「变化」（router 据此决定是否落库）。
    mock 模式下走确定性规则，不调用真实模型。
    """
    before = normalize_memory(state)
    before_json = json.dumps(before, ensure_ascii=False, sort_keys=True)

    if getattr(llm, "mock", False):
        patch: Patch | dict = _mock_patch(
            turn=turn, beats=beats, topic_title=topic_title, last_user=last_user
        )
    else:
        prompt = (
            f"当前状态：{json.dumps(before, ensure_ascii=False)}\n"
            f"话题：{topic_title}\n"
            f"学生说：{last_user}\n"
            f"AI 回：{last_reply}"
        )
        patch = await llm.json(SYSTEM, prompt, Patch, max_tokens=500)

    merged = merge_memory(before, patch)
    changed = json.dumps(merged, ensure_ascii=False, sort_keys=True) != before_json
    return changed, merged


# ---------------------------------------------------------------- 注入文本


def render_memory(m: MemoryState | dict | None) -> str:
    """注入 partner 的文本块（英文），控制在 ~250 token 内。"""
    state = normalize_memory(m)
    if not state["setting"] and not state["established_facts"] and not state["open_threads"]:
        return ""
    lines = ["What has already happened in this scene (do not contradict):"]
    if state["setting"]:
        lines.append(f"- Setting: {state['setting']}")
    if state["established_facts"]:
        lines.append(f"- Established facts: {'; '.join(state['established_facts'])}")
    if state["open_threads"]:
        lines.append(f"- Still unresolved: {'; '.join(state['open_threads'])}")
    if state["beats_done"]:
        lines.append(f"- Already covered: {'; '.join(state['beats_done'])}")
    if state["student_stance"]:
        lines.append(f"- The learner's position: {'; '.join(state['student_stance'])}")
    return "\n".join(lines)

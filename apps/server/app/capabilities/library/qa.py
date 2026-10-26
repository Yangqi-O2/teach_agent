"""教材问答：只用指定教材回答，逐句给出处，查不到就直说。

三条硬约束（这是「针对性强、可核对」和「一本正经胡说」的分界线）
---------------------------------------------------------------
1. **检索不到就不调模型**。命中为空时直接返回固定话术，既省钱也彻底避免编造。
2. **引用必须回验**。模型输出的 `[3]` 要真的对应本轮检索到的第 3 段；越界编号
   （比如只给了 5 段却写 `[7]`）一律丢弃并记进诊断。这和英语能力里「span 必须
   在原文里出现」是同一个原则：不信模型自报的定位信息。
3. **没有标注就明说**。答案里一个引用都没有时，不假装它是有据的——标记
   `citation_ok=False`，前端在答案下方给出提示。
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Sequence

from ...core.errors import ApiError
from . import retrieval, store
from .retrieval import Hit, SearchResult

log = logging.getLogger(__name__)

MAX_HISTORY_TURNS = 4
EMPTY_ANSWER = (
    "这份教材里没有找到和这个问题相关的内容。\n\n"
    "可以试试：换一个更具体的说法（比如直接问某个概念、公式或章节名）、"
    "换一本教材，或者先把相关章节上传进来。"
)

SYSTEM = """你是这门课的助教，只负责讲解学生上传的教材。

严格遵守：
1. 只能使用下面「教材片段」里的内容作答。片段之外的常识、你的记忆、网络知识一律不得作为依据。
2. 每个事实性结论后面必须紧跟出处编号，形如 [1]、[2][3]。编号只能取片段列表里出现过的。
3. 教材没有写到的内容，直接回答「教材这一节没有提到」，不要推测，更不要编造页码或章节。
4. 用中文讲解。先给结论，再展开推理；遇到学生容易卡住的地方，补一句「为什么」。
5. 涉及定义、公式、定理时，先按教材原话复述，再解释它的含义与适用条件。
6. 不要复述整个片段，只讲和问题有关的部分。"""


@dataclass
class AnswerBundle:
    text: str = ""
    citations: list[dict[str, Any]] = field(default_factory=list)
    unused: list[dict[str, Any]] = field(default_factory=list)
    citation_ok: bool = False
    bad_markers: list[int] = field(default_factory=list)
    mode: str = ""
    degraded: bool = False
    notes: list[str] = field(default_factory=list)

    def as_meta(self) -> dict[str, Any]:
        return {
            "citation_ok": self.citation_ok,
            "bad_markers": self.bad_markers,
            "retriever": self.mode,
            "degraded": self.degraded,
            "notes": self.notes,
            "cited": len(self.citations),
            "retrieved": len(self.citations) + len(self.unused),
        }


_CITE_RE = re.compile(r"\[(\d{1,2})\]")


def build_user_prompt(question: str, context: str) -> str:
    return (
        f"教材片段：\n\n{context}\n\n"
        f"----\n学生的问题：{question.strip()}\n\n"
        "请按系统提示的要求作答，并在每个结论后标注出处编号。"
    )


def collect_citations(text: str, hits: Sequence[Hit]) -> tuple[list[dict], list[dict], list[int]]:
    """从答案里抽引用编号并回验：越界的编号丢掉并单独记录。"""
    cited: list[int] = []
    bad: list[int] = []
    for match in _CITE_RE.finditer(text or ""):
        index = int(match.group(1))
        if index < 1 or index > len(hits):
            if index not in bad:
                bad.append(index)
            continue
        if index not in cited:
            cited.append(index)
    citations = [hits[index - 1].as_citation(index) for index in cited]
    unused = [
        hit.as_citation(index)
        for index, hit in enumerate(hits, start=1)
        if index not in cited
    ]
    return citations, unused, sorted(bad)


# ---------------------------------------------------------------- 检索


async def retrieve(
    user_id: int,
    question: str,
    document_ids: Sequence[int] | None,
    llm: Any = None,
    limit: int = 6,
) -> SearchResult:
    return await retrieval.search(
        user_id=user_id,
        query=question,
        document_ids=document_ids,
        limit=limit,
        llm=llm,
    )


# ---------------------------------------------------------------- 主流程


async def stream_answer(
    user_id: int,
    question: str,
    document_ids: Sequence[int] | None,
    llm: Any = None,
    history: Sequence[dict] | None = None,
    limit: int = 6,
) -> AsyncIterator[tuple[str, dict[str, Any]]]:
    """产出 (事件名, 载荷)：status → (citations) → delta* → done / error。"""
    question = (question or "").strip()
    if len(question) < 2:
        raise ApiError("问题太短了", code="empty_question", status=400)

    yield "status", {"stage": "retrieving", "message": "正在教材里查找相关段落"}

    if document_ids is not None and not list(document_ids):
        raise ApiError("请先选择要提问的教材", code="no_document", status=400)

    found = await retrieve(user_id, question, document_ids, llm=llm, limit=limit)
    if not found.hits:
        bundle = AnswerBundle(text=EMPTY_ANSWER, mode=found.mode or "empty", degraded=found.degraded)
        if found.note:
            bundle.notes.append(found.note)
        yield "delta", {"text": EMPTY_ANSWER}
        yield "done", {
            "answer": EMPTY_ANSWER,
            "citations": [],
            "unused": [],
            "meta": {**bundle.as_meta(), "empty": True},
        }
        return

    context, used = retrieval.build_context(found.hits)
    messages: list[dict] = [{"role": "system", "content": SYSTEM}]
    for turn in (history or [])[-MAX_HISTORY_TURNS:]:
        role = turn.get("role")
        content = str(turn.get("content") or "").strip()
        if role in ("user", "assistant") and content:
            messages.append({"role": role, "content": content[:1500]})
    messages.append({"role": "user", "content": build_user_prompt(question, context)})

    if llm is None:
        raise ApiError(
            "还没有配置模型供应商，请先在「设置 → 模型接入」里添加一个",
            code="no_provider",
            status=409,
        )

    yield "status", {
        "stage": "generating",
        "message": f"命中 {len(used)} 段教材内容，正在生成讲解",
        "retriever": found.mode,
    }

    buffer: list[str] = []
    try:
        async for delta in llm.stream(messages, temperature=0.3, max_tokens=1600):
            buffer.append(delta)
            yield "delta", {"text": delta}
    except ApiError:
        raise
    except Exception as exc:  # noqa: BLE001
        log.exception("教材问答生成失败")
        raise ApiError(f"生成失败：{exc}", code="llm_error", status=502) from exc

    answer = "".join(buffer).strip()
    citations, unused, bad = collect_citations(answer, used)
    notes = [found.note] if found.note else []
    if not citations:
        notes.append("这条回答没有标注出处，建议对照原文核对")
    if bad:
        notes.append(f"模型给出了不存在的出处编号 {bad}，已忽略")

    yield "citations", {"citations": citations, "unused": unused}
    yield "done", {
        "answer": answer,
        "citations": citations,
        "unused": unused,
        "meta": {
            "citation_ok": bool(citations),
            "bad_markers": bad,
            "retriever": found.mode,
            "degraded": found.degraded,
            "notes": notes,
            "cited": len(citations),
            "retrieved": len(used),
        },
    }


# ---------------------------------------------------------------- 会话落库


def ensure_thread(user_id: int, thread_id: str | None, document_ids: Sequence[int], title: str) -> str:
    if thread_id:
        row = store.one(
            "SELECT id FROM qa_threads WHERE id = :id AND user_id = :uid",
            id=thread_id,
            uid=user_id,
        )
        if row:
            store.execute(
                "UPDATE qa_threads SET updated_at = :now WHERE id = :id",
                now=store.now_iso(),
                id=thread_id,
            )
            return thread_id
        raise ApiError("会话不存在", code="not_found", status=404)
    new_id = store.new_id()
    now = store.now_iso()
    store.execute(
        "INSERT INTO qa_threads (id, user_id, title, document_ids, created_at, updated_at) "
        "VALUES (:id, :uid, :title, :docs, :now, :now)",
        id=new_id,
        uid=user_id,
        title=(title or "教材问答")[:60],
        docs=store.json_dump(list(document_ids)),
        now=now,
    )
    return new_id


def save_turn(
    thread_id: str,
    user_id: int,
    question: str,
    answer: str,
    citations: list[dict],
    meta: dict,
) -> None:
    now = store.now_iso()
    store.execute(
        "INSERT INTO qa_messages (id, thread_id, user_id, role, content_md, citations_json, "
        "meta_json, created_at) VALUES (:id, :thread, :uid, 'user', :content, '[]', '{}', :now)",
        id=store.new_id(),
        thread=thread_id,
        uid=user_id,
        content=question,
        now=now,
    )
    store.execute(
        "INSERT INTO qa_messages (id, thread_id, user_id, role, content_md, citations_json, "
        "meta_json, created_at) VALUES (:id, :thread, :uid, 'assistant', :content, :cites, "
        ":meta, :now)",
        id=store.new_id(),
        thread=thread_id,
        uid=user_id,
        content=answer,
        cites=store.json_dump(citations),
        meta=store.json_dump(meta),
        now=store.now_iso(),
    )

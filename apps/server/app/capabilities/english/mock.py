"""离线演示 / 测试夹具用的确定性 MockLLM。

只在能力设置里打开 `mock_mode` 时启用：把 SSE、话题池、会话落库整条管线跑通。
**它不是产品内容**——评审时不要把 mock 输出当成模型质量。
"""
from __future__ import annotations

import asyncio
import hashlib
from collections.abc import AsyncIterator
from typing import Any

from pydantic import BaseModel, ValidationError


def _hash(text: str) -> int:
    return int(hashlib.sha256(text.encode("utf-8")).hexdigest()[:8], 16)


def mock_plan(user_input: str) -> dict:
    """从 prompt 里取出领域名，生成 6~10 个话题。"""
    domain = ""
    for line in (user_input or "").splitlines():
        if "领域：" in line:
            domain = line.split("领域：", 1)[1].strip()
            break
    domain = domain or (user_input or "").strip()[:20] or "情景"
    seed = _hash(domain)
    angles = [
        ("A stalled shipment", "货物滞留"),
        ("A budget squeeze", "预算收紧"),
        ("A last-minute change", "临时变更"),
        ("A supplier swap", "供应商更换"),
        ("A compliance check", "合规审查"),
        ("A public backlash", "舆论反弹"),
        ("A field failure", "现场故障"),
        ("A handover meeting", "交接会议"),
    ]
    topics = []
    for i, (en, _zh) in enumerate(angles):
        topics.append(
            {
                "title": f"{en} in {domain}",
                "beats": [
                    f"open with {en.lower()}",
                    "raise a constraint the other side did not expect",
                    "negotiate a workable compromise",
                    "close with a concrete next step",
                ],
                "target_tenses": ["past simple", "present perfect"] if i % 2 == 0 else ["future", "present continuous"],
                "target_lexis": ["constraint", "deadline", "trade-off", "stakeholder"],
                "difficulty": "A2" if i < 3 else ("B1" if i < 6 else "B2"),
            }
        )
    return {
        "title_zh": f"{domain}（模拟）",
        "title_en": f"{domain} — simulated scenario",
        "slug": f"mock-{seed:x}",
        "topics": topics,
    }


_OPENERS = [
    "Right — I'm the counterpart. Let's get straight to it.",
    "Okay, noted. Here is where it gets awkward.",
    "Fair point, but there is a catch.",
    "Let me push back a little.",
]
_QUESTIONS = [
    "What would you do if the deadline moved up by a week?",
    "Who signs off on this on your side?",
    "Can we live with the cheaper option if it costs us two days?",
    "What is the one thing you will not compromise on?",
]


def mock_reply(messages: list[dict], turn: int = 0) -> str:
    last_user = ""
    for message in messages:
        if message.get("role") == "user":
            last_user = str(message.get("content") or "")
    idx = turn % len(_OPENERS)
    question = _QUESTIONS[(turn + len(last_user)) % len(_QUESTIONS)]
    return f"{_OPENERS[idx]} {question}"


def _default_value(annotation: Any) -> Any:
    origin = getattr(annotation, "__origin__", None)
    if annotation is bool or origin is bool:
        return False
    if annotation is int or origin is int:
        return 0
    if annotation is float or origin is float:
        return 0.5
    if annotation is str or origin is str:
        return "mock"
    if origin in (list, tuple, set):
        return []
    if origin is dict:
        return {}
    return None


class MockLLM:
    name = "mock"
    mock = True

    async def stream(
        self, system: str, messages: list[dict], max_tokens: int = 600
    ) -> AsyncIterator[str]:
        text = mock_reply(messages, turn=len(messages))
        for i in range(0, len(text), 6):
            await asyncio.sleep(0.005)
            yield text[i : i + 6]

    async def json(
        self,
        system: str,
        user: str,
        schema: type[BaseModel],
        max_tokens: int = 1200,
    ) -> BaseModel:
        fields = set(getattr(schema, "model_fields", {}))
        if "topics" in fields:
            data: dict = mock_plan(user)
        elif "errors" in fields:
            data = {"errors": [], "confidence": 0.0}
        elif "glossZh" in fields or "gloss_zh" in fields:
            data = {"glossZh": "（模拟释义）", "pos": "n."}
        elif "summary" in fields:
            data = {"summary": "（模拟摘要）"}
        elif "title" in fields and ("rule_md" in fields or "ruleMd" in fields):
            data = {"title": "（模拟）知识卡", "rule_md": "mock", "examples": []}
        else:
            data = {}
        # 补齐 schema 里其它必填字段，避免 mock 自己都过不了校验
        for field_name, field in getattr(schema, "model_fields", {}).items():
            if field_name not in data:
                data[field_name] = _default_value(field.annotation)
        try:
            return schema.model_validate(data)
        except ValidationError as exc:  # pragma: no cover - 防御性
            raise RuntimeError(f"MockLLM 未产出合法结构: {exc}") from exc

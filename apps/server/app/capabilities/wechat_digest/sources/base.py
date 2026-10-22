"""数据源适配器协议、内置消息结构与注册表。

**新增一个数据源的完整步骤（前端零改动）：**

1. 在本目录新增模块，例如 ``sources/onebot.py``，实现 ``MessageSource`` 子类::

       class OneBotSource(MessageSource):
           id = "onebot"
           name = "OneBot"
           description = "从本地 OneBot 机器人拉取群消息。"
           badge = "实验"
           params_schema = {...}     # JSON Schema 子集，前端据此渲染参数表单
           sample_params = None

           def available(self) -> tuple[bool, str | None]:
               return False, "还没有配置 OneBot 连接"

           def load(self, params: dict) -> dict[str, list[Message]]:
               return {"群名": [Message(...), ...]}

2. 在 ``sources/__init__.py`` 里 ``from .onebot import OneBotSource`` 并
   ``register_source(OneBotSource())``。

3. 完成。``GET /options`` 自动多一个数据源，``POST /preview`` / ``POST /digests``
   自动按 ``params_schema`` 接收参数（service 层只认 ``load()`` 的返回结构）。

约定：``load()`` 返回的是**未清洗**的 ``{群名: [Message, ...]}``；清洗统一由
``pipeline/cleaners.py`` 负责，数据源不要自己做降噪。
"""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from ....core.errors import ApiError

log = logging.getLogger(__name__)


@dataclass
class Message:
    """单条群消息（内部统一结构，见契约 §4.1）。"""

    group: str
    sender: str
    text: str
    time: str = ""

    def to_ai_line(self) -> str:
        """喂给大模型的一行：``[时间] 发送者: 内容``。"""
        if self.time:
            if self.sender:
                return f"[{self.time}] {self.sender}: {self.text}"
            return f"[{self.time}] {self.text}"
        if self.sender:
            return f"{self.sender}: {self.text}"
        return self.text


@dataclass
class SourceDescriptor:
    """数据源对外描述（直接对应 ``GET /options`` 的 sources 数组项，见契约 §3.1）。"""

    id: str
    name: str
    description: str
    params_schema: dict[str, Any] = field(default_factory=dict)
    badge: str | None = None
    available: bool = True
    hint: str | None = None
    sample_params: dict[str, Any] | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "badge": self.badge,
            "available": self.available,
            "hint": self.hint,
            "sample_params": self.sample_params,
            "params_schema": self.params_schema,
        }


class MessageSource(ABC):
    """数据源适配器基类（见契约 §5.1）。"""

    id: str = ""
    name: str = ""
    description: str = ""
    params_schema: dict[str, Any] = {}       # 子类用类属性覆盖（不要原地修改）
    badge: str | None = None
    sample_params: dict[str, Any] | None = None

    def available(self) -> tuple[bool, str | None]:
        """返回 ``(是否可用, 不可用提示)``。默认总是可用。"""
        return True, None

    @abstractmethod
    def load(self, params: dict[str, Any]) -> dict[str, list[Message]]:
        """返回 ``{群名: [Message, ...]}``（未清洗）。解析不出内容时抛 ValueError。"""

    def descriptor(self) -> SourceDescriptor:
        available, hint = self.available()
        return SourceDescriptor(
            id=self.id,
            name=self.name,
            description=self.description,
            params_schema=self.params_schema,
            badge=self.badge,
            available=available,
            hint=hint,
            sample_params=self.sample_params,
        )


# —— 模块级注册表 ——
_SOURCES: dict[str, MessageSource] = {}


def register_source(source: MessageSource) -> None:
    """注册数据源。重复注册同 id 时以最后一次为准（幂等，热重载也安全）。"""
    source_id = (getattr(source, "id", "") or "").strip()
    if not source_id:
        raise ValueError("数据源缺少 id")
    if source_id in _SOURCES and _SOURCES[source_id] is not source:
        log.warning("数据源 id 重复注册，已覆盖: %s", source_id)
    _SOURCES[source_id] = source


def get_source(source_id: str | None) -> MessageSource:
    """按 id 取数据源；未知 id 抛统一的 ApiError。"""
    sid = (source_id or "").strip() or "paste"
    source = _SOURCES.get(sid)
    if source is None:
        raise ApiError(f"未知的数据源：{sid}", code="invalid_source", status=422)
    return source


def list_sources() -> list[dict[str, Any]]:
    """转成 ``GET /options`` 里的 sources 描述列表。"""
    return [source.descriptor().as_dict() for source in _SOURCES.values()]


def list_source_objects() -> list[MessageSource]:
    """内部用：拿到数据源实例（例如做可用性探测）。"""
    return list(_SOURCES.values())

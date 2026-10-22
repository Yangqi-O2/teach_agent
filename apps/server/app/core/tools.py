"""工具注册表：能力把可被 Agent 调用的动作注册进来。

一个 Tool 就是：名字 + 描述 + JSON Schema 参数 + 执行函数。
聊天 Agent 在做 function calling 时，直接读这里的清单。
"""
from __future__ import annotations

import inspect
import logging
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

log = logging.getLogger(__name__)

ToolHandler = Callable[..., Awaitable[Any]]


@dataclass
class Tool:
    name: str
    description: str
    parameters: dict = field(default_factory=lambda: {"type": "object", "properties": {}})
    capability: str = ""
    scopes: list[str] = field(default_factory=list)
    needs_confirm: bool = False
    handler: ToolHandler | None = None

    async def run(self, **kwargs: Any) -> Any:
        if self.handler is None:
            raise RuntimeError(f"工具 {self.name} 没有绑定执行函数")
        result = self.handler(**kwargs)
        if inspect.isawaitable(result):
            result = await result
        return result

    def as_openai_spec(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }

    def as_public(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "parameters": self.parameters,
            "capability": self.capability,
            "scopes": self.scopes,
            "needs_confirm": self.needs_confirm,
        }


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        if tool.name in self._tools:
            raise ValueError(f"工具名重复: {tool.name}")
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def list(self, capability: str | None = None) -> list[Tool]:
        items = list(self._tools.values())
        if capability:
            items = [t for t in items if t.capability == capability]
        return items

    def openai_specs(self, allowed: set[str] | None = None) -> list[dict]:
        tools = self._tools.values()
        if allowed is not None:
            tools = [t for t in tools if t.capability in allowed or not t.capability]
        return [t.as_openai_spec() for t in tools]

    async def execute(self, name: str, arguments: dict | None = None) -> dict:
        tool = self._tools.get(name)
        if tool is None:
            return {"ok": False, "error": f"未知工具: {name}"}
        try:
            data = await tool.run(**(arguments or {}))
            return {"ok": True, "data": data}
        except Exception as exc:  # noqa: BLE001
            log.exception("工具执行失败: %s", name)
            return {"ok": False, "error": str(exc)}


registry = ToolRegistry()

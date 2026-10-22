"""能力（Capability）插件协议与自动发现。

约定：app/capabilities/<id>/capability.py 里必须暴露一个 CAPABILITY 实例。
能力可自带：路由、Agent 工具、启动钩子、SQL 迁移、设置项 Schema（前端自动渲染）。
"""
from __future__ import annotations

import importlib
import logging
import pkgutil
from pathlib import Path
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field

from .tools import Tool

log = logging.getLogger(__name__)


class NavItem(BaseModel):
    label: str
    path: str
    order: int = 100


class CapabilityManifest(BaseModel):
    id: str
    name: str
    description: str = ""
    icon: str = "sparkles"
    nav: NavItem | None = None
    version: str = "0.1.0"
    status: str = "stable"                  # stable | beta | planned
    settings_schema: dict[str, Any] = Field(default_factory=dict)


class Capability:
    """能力基类：子类至少提供 manifest。"""

    manifest: CapabilityManifest

    def router(self) -> APIRouter | None:
        return None

    def tools(self) -> list[Tool]:
        return []

    def migrations_dir(self) -> Path | None:
        return None

    async def on_startup(self, app: Any) -> None:  # noqa: ARG002
        return None


class CapabilityRegistry:
    def __init__(self) -> None:
        self._caps: dict[str, Capability] = {}

    def discover(self) -> list[Capability]:
        import app.capabilities as pkg

        found: list[Capability] = []
        for info in pkgutil.iter_modules(pkg.__path__):
            if not info.ispkg:
                continue
            try:
                module = importlib.import_module(f"app.capabilities.{info.name}.capability")
            except Exception:  # noqa: BLE001
                log.exception("能力加载失败: %s（已跳过）", info.name)
                continue
            cap = getattr(module, "CAPABILITY", None)
            if not isinstance(cap, Capability):
                log.warning("能力 %s 没有暴露 CAPABILITY 实例（已跳过）", info.name)
                continue
            if cap.manifest.id in self._caps:
                log.warning("能力 id 重复: %s（已跳过）", cap.manifest.id)
                continue
            self._caps[cap.manifest.id] = cap
            found.append(cap)
            log.info("已发现能力: %s (%s)", cap.manifest.id, cap.manifest.name)
        return found

    def get(self, capability_id: str) -> Capability | None:
        return self._caps.get(capability_id)

    def all(self) -> list[Capability]:
        return sorted(
            self._caps.values(),
            key=lambda c: (c.manifest.nav.order if c.manifest.nav else 999, c.manifest.id),
        )

    def migration_dirs(self) -> dict[str, Path]:
        dirs: dict[str, Path] = {}
        for cap in self._caps.values():
            d = cap.migrations_dir()
            if d is not None and d.is_dir():
                dirs[cap.manifest.id] = d
        return dirs

    def register_tools(self) -> None:
        from .tools import registry

        for cap in self._caps.values():
            for tool in cap.tools():
                tool.capability = tool.capability or cap.manifest.id
                registry.register(tool)

    def mount(self, app: Any) -> None:
        for cap in self._caps.values():
            router = cap.router()
            if router is not None:
                app.include_router(router, prefix=f"/api/c/{cap.manifest.id}")


# 全局能力注册表（单例）：main 装配时 discover 一次，路由与工具都读它
capabilities = CapabilityRegistry()

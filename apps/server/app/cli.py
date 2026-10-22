#!/usr/bin/env python3
"""天健湖命令行：run / doctor / new-capability / migrate。"""
from __future__ import annotations

import argparse
import importlib.util
import socket
import sys
import textwrap
from pathlib import Path

SERVER_DIR = Path(__file__).resolve().parent.parent
REPO_DIR = SERVER_DIR.parent.parent
WEB_DIR = REPO_DIR / "apps" / "web"


def cmd_run(args: argparse.Namespace) -> int:
    import uvicorn

    uvicorn.run("app.main:app", host=args.host, port=args.port, reload=args.reload, log_level="info")
    return 0


def cmd_doctor(_: argparse.Namespace) -> int:
    from .config import settings

    checks: list[tuple[str, bool, str]] = []
    version = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    checks.append(("Python ≥ 3.11", sys.version_info >= (3, 11), version))

    deps = ["fastapi", "uvicorn", "sqlmodel", "openai", "httpx", "cryptography", "sse_starlette"]
    missing = [d for d in deps if importlib.util.find_spec(d) is None]
    checks.append(("后端依赖", not missing, "全部就绪" if not missing else "缺少: " + ", ".join(missing)))

    checks.append(("数据目录", settings.data_dir.exists() or settings.data_dir.parent.exists(), str(settings.data_dir)))

    try:
        with socket.socket() as sock:
            sock.bind((settings.host, settings.port))
        checks.append(("端口可用", True, f"{settings.host}:{settings.port}"))
    except OSError:
        checks.append(("端口占用", False, f"{settings.host}:{settings.port} 已被占用（若是天健湖自己开着则正常）"))

    checks.append(
        ("前端产物", settings.web_dist.is_dir(), str(settings.web_dist) + ("" if settings.web_dist.is_dir() else "（未构建，执行 pnpm build）"))
    )
    checks.append(("Node 依赖", (WEB_DIR / "node_modules").is_dir(), str(WEB_DIR / "node_modules")))

    print("\n天健湖 · 环境自检\n" + "─" * 46)
    for name, ok, detail in checks:
        print(f"{'✓' if ok else '✗'}  {name:<12} {detail}")
    print("─" * 46)
    return 0 if all(ok for _, ok, _ in checks) else 1


def cmd_migrate(_: argparse.Namespace) -> int:
    from .core.capability import capabilities
    from .db import init_db

    capabilities.discover()
    applied = init_db(capabilities.migration_dirs())
    print("迁移完成：" + (", ".join(applied) if applied else "没有新的迁移"))
    return 0


CAPABILITY_TEMPLATE = '''"""能力：{name}

由 `python -m app.cli new-capability {cap_id}` 生成。
"""
from __future__ import annotations

from pathlib import Path

from ...core.capability import Capability, CapabilityManifest, NavItem
from ...core.tools import Tool
from .router import router


async def {ident}_ping() -> dict:
    return {{"pong": True, "capability": "{cap_id}"}}


class {cls_name}Capability(Capability):
    manifest = CapabilityManifest(
        id="{cap_id}",
        name="{name}",
        description="{description}",
        icon="{icon}",
        nav=NavItem(label="{name}", path="/cap/{cap_id}", order={order}),
        version="0.1.0",
        settings_schema={{"type": "object", "properties": {{}}}},
    )

    def router(self):
        return router

    def migrations_dir(self) -> Path:
        return Path(__file__).resolve().parent / "migrations"

    def tools(self) -> list[Tool]:
        return [
            Tool(
                name="{ident}_ping",
                description="示例工具：返回 pong，用于验证工具注册链路。",
                parameters={{"type": "object", "properties": {{}}}},
                handler={ident}_ping,
            )
        ]


CAPABILITY = {cls_name}Capability()
'''

ROUTER_TEMPLATE = '''from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(tags=["{cap_id}"])


@router.get("/ping")
async def ping() -> dict:
    """能力自检：/api/c/{cap_id}/ping"""
    return {{"ok": True, "capability": "{cap_id}"}}
'''

MIGRATION_TEMPLATE = '''-- {name}：能力自带迁移（按文件名顺序执行一次）
-- CREATE TABLE IF NOT EXISTS {cap_id}_items (
--     id INTEGER PRIMARY KEY AUTOINCREMENT,
--     created_at TEXT NOT NULL
-- );
'''

WEB_INDEX_TEMPLATE = '''import type {{ CapabilityModule }} from "../registry";
import {{ {cls_name}Page }} from "./page";

const capability: CapabilityModule = {{
  id: "{cap_id}",
  routes: [{{ path: "/cap/{cap_id}", element: <{cls_name}Page /> }}],
}};

export default capability;
'''

WEB_PAGE_TEMPLATE = '''import {{ PageHeader }} from "../../components/PageHeader";

export function {cls_name}Page() {{
  return (
    <div className="space-y-6">
      <PageHeader title="{name}" description="{description}" />
      <div className="card p-6 text-sm text-ink-soft">
        这是 {cap_id} 能力的页面占位。修改
        <code className="mx-1 rounded bg-brand-soft px-1.5 py-0.5 text-brand">
          apps/web/src/capabilities/{cap_id}/page.tsx
        </code>
        开始开发。
      </div>
    </div>
  );
}}
'''


def cmd_new_capability(args: argparse.Namespace) -> int:
    cap_id = args.id.strip().lower().replace(" ", "-")
    if not cap_id.replace("-", "").isalnum() or not cap_id[0].isalpha():
        print("能力 id 只能由字母、数字、连字符组成，且必须以字母开头（例如 my-feature）")
        return 1
    cap_dir = SERVER_DIR / "app" / "capabilities" / cap_id
    web_dir = WEB_DIR / "src" / "capabilities" / cap_id
    if cap_dir.exists() or web_dir.exists():
        print(f"能力已存在: {cap_dir}")
        return 1

    name = args.name or cap_id
    cls_name = "".join(part.capitalize() for part in cap_id.replace("_", "-").split("-"))
    ident = cap_id.replace("-", "_")
    description = args.description or f"{name}能力"
    ctx = dict(
        cap_id=cap_id,
        ident=ident,
        name=name,
        cls_name=cls_name,
        description=description,
        icon=args.icon,
        order=args.order,
    )

    (cap_dir / "migrations").mkdir(parents=True)
    (cap_dir / "__init__.py").write_text("", encoding="utf-8")
    (cap_dir / "capability.py").write_text(CAPABILITY_TEMPLATE.format(**ctx), encoding="utf-8")
    (cap_dir / "router.py").write_text(ROUTER_TEMPLATE.format(**ctx), encoding="utf-8")
    (cap_dir / "migrations" / "001_init.sql").write_text(MIGRATION_TEMPLATE.format(**ctx), encoding="utf-8")

    if not args.no_web:
        web_dir.mkdir(parents=True)
        (web_dir / "index.tsx").write_text(WEB_INDEX_TEMPLATE.format(**ctx), encoding="utf-8")
        (web_dir / "page.tsx").write_text(WEB_PAGE_TEMPLATE.format(**ctx), encoding="utf-8")

    print(f"已生成能力：{cap_id}")
    print(f"  后端: {cap_dir}")
    if not args.no_web:
        print(f"  前端: {web_dir}")
    print("\n下一步：重启后端，侧栏会自动出现这个能力；Agent 工具表也会多一个 " + f"{ident}_ping。")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="tianjianhu", description="天健湖命令行")
    sub = parser.add_subparsers(dest="command", required=True)

    p_run = sub.add_parser("run", help="启动后端")
    p_run.add_argument("--host", default="127.0.0.1")
    p_run.add_argument("--port", type=int, default=8787)
    p_run.add_argument("--reload", action="store_true")
    p_run.set_defaults(func=cmd_run)

    p_doc = sub.add_parser("doctor", help="环境自检")
    p_doc.set_defaults(func=cmd_doctor)

    p_mig = sub.add_parser("migrate", help="执行数据库迁移")
    p_mig.set_defaults(func=cmd_migrate)

    p_new = sub.add_parser("new-capability", help="生成一个能力骨架（前后端）")
    p_new.add_argument("id")
    p_new.add_argument("--name", help="中文名")
    p_new.add_argument("--description", help="一句话描述")
    p_new.add_argument("--icon", default="sparkles", help="lucide 图标名")
    p_new.add_argument("--order", type=int, default=100, help="导航排序")
    p_new.add_argument("--no-web", action="store_true", help="只生成后端")
    p_new.set_defaults(func=cmd_new_capability)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())

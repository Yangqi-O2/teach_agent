"""天健湖 · 应用装配。

启动顺序：建目录 → 发现能力 → 执行迁移 → 建核心表 → 注册工具 → 挂路由 → 托管前端。
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .api import jobs as jobs_api
from .api import providers as providers_api
from .api import settings as settings_api
from .api import system as system_api
from .config import APP_NAME, VERSION, settings
from .core.capability import capabilities
from .core.errors import ApiError, api_error_handler, validation_error_handler
from .core.jobs import jobs
from .db import init_db

logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s  %(levelname)-7s %(name)s  %(message)s",
)
log = logging.getLogger("tianjianhu")


def create_app() -> FastAPI:
    settings.ensure_dirs()

    capabilities.discover()
    init_db(capabilities.migration_dirs())
    capabilities.register_tools()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        for cap in capabilities.all():
            await cap.on_startup(app)
        log.info("%s v%s 已启动 · 能力 %d 个 · 工具 %d 个", APP_NAME, VERSION, len(capabilities.all()), len(__import__("app.core.tools", fromlist=["registry"]).registry.list()))
        yield

    app = FastAPI(
        title=APP_NAME,
        version=VERSION,
        lifespan=lifespan,
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.add_exception_handler(ApiError, api_error_handler)
    app.add_exception_handler(RequestValidationError, validation_error_handler)

    app.include_router(system_api.router, prefix="/api")
    app.include_router(providers_api.router, prefix="/api")
    app.include_router(jobs_api.router, prefix="/api")
    app.include_router(settings_api.router, prefix="/api")
    capabilities.mount(app)

    _mount_frontend(app)
    return app


def _mount_frontend(app: FastAPI) -> None:
    dist = settings.web_dist
    assets = dist / "assets"
    if assets.is_dir():
        app.mount("/assets", StaticFiles(directory=assets), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa(full_path: str, request: Request):
        if full_path.startswith("api/"):
            return JSONResponse(
                status_code=404,
                content={"code": "not_found", "message": f"接口不存在: /{full_path}"},
            )
        if not dist.is_dir():
            return JSONResponse(
                {
                    "app": APP_NAME,
                    "version": VERSION,
                    "message": "前端还没构建。开发模式请运行 pnpm dev（5174），或执行 ./scripts/start.sh。",
                    "api_docs": str(request.base_url) + "api/docs",
                },
                status_code=200,
            )
        target = (dist / full_path).resolve()
        if full_path and target.is_file() and str(target).startswith(str(dist.resolve())):
            return FileResponse(target)
        return FileResponse(dist / "index.html")


app = create_app()

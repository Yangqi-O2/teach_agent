"""任务中心：解析 / 嵌入 / 抓取这类耗时活儿统一走这里。

- 线程池执行，进度写库
- 前端通过 SSE 轮询快照展示
- 支持取消（协作式：任务自己调用 ctx.check_cancelled()）
"""
from __future__ import annotations

import json
import logging
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Any, Callable

from sqlmodel import Session, select

from ..config import settings
from ..db import engine
from ..models import Event, Job

log = logging.getLogger(__name__)

JobFn = Callable[["JobContext", dict], Any]


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class JobCancelled(Exception):
    pass


class JobContext:
    def __init__(self, job_id: str):
        self.job_id = job_id
        self._cancelled = threading.Event()

    def progress(self, pct: int, message: str | None = None) -> None:
        self.check_cancelled()
        with Session(engine) as session:
            job = session.get(Job, self.job_id)
            if job is None:
                return
            job.progress = max(0, min(100, int(pct)))
            if message:
                job.message = message
            job.updated_at = utcnow()
            session.add(job)
            session.commit()

    def check_cancelled(self) -> None:
        if self._cancelled.is_set():
            raise JobCancelled("任务已取消")


class JobManager:
    def __init__(self) -> None:
        self._pool = ThreadPoolExecutor(max_workers=settings.max_workers, thread_name_prefix="tjh-job")
        self._handlers: dict[str, JobFn] = {}
        self._contexts: dict[str, JobContext] = {}

    def register(self, job_type: str, handler: JobFn) -> None:
        self._handlers[job_type] = handler

    def submit(self, job_type: str, title: str, payload: dict | None = None) -> str:
        handler = self._handlers.get(job_type)
        if handler is None:
            raise ValueError(f"未注册的任务类型: {job_type}")
        job_id = uuid.uuid4().hex[:12]
        with Session(engine) as session:
            session.add(
                Job(
                    id=job_id,
                    type=job_type,
                    title=title,
                    payload=json.dumps(payload or {}, ensure_ascii=False),
                )
            )
            session.add(Event(kind="job", message=f"排队：{title}", payload=job_id))
            session.commit()
        self._pool.submit(self._run, job_id, handler, payload or {})
        return job_id

    def _run(self, job_id: str, handler: JobFn, payload: dict) -> None:
        ctx = JobContext(job_id)
        self._contexts[job_id] = ctx
        self._update(job_id, status="running", progress=1, message="开始执行")
        try:
            result = handler(ctx, payload)
            self._update(
                job_id,
                status="done",
                progress=100,
                message="已完成",
                result=json.dumps(result, ensure_ascii=False, default=str) if result is not None else None,
                finished_at=utcnow(),
            )
        except JobCancelled:
            self._update(job_id, status="cancelled", message="已取消", finished_at=utcnow())
        except Exception as exc:  # noqa: BLE001
            log.exception("任务失败: %s", job_id)
            self._update(job_id, status="error", message="执行失败", error=str(exc), finished_at=utcnow())
        finally:
            self._contexts.pop(job_id, None)

    def _update(self, job_id: str, **fields: Any) -> None:
        with Session(engine) as session:
            job = session.get(Job, job_id)
            if job is None:
                return
            for key, value in fields.items():
                setattr(job, key, value)
            job.updated_at = utcnow()
            session.add(job)
            session.commit()

    def cancel(self, job_id: str) -> bool:
        with Session(engine) as session:
            job = session.get(Job, job_id)
            if job is None:
                return False
            if job.status in ("queued", "running"):
                ctx = self._contexts.get(job_id)
                if ctx:
                    ctx._cancelled.set()
                job.status = "cancelled"
                job.message = "已取消"
                job.finished_at = utcnow()
                session.add(job)
                session.commit()
                return True
        return False

    def list(self, limit: int = 50) -> list[Job]:
        with Session(engine) as session:
            return list(
                session.exec(select(Job).order_by(Job.created_at.desc()).limit(limit)).all()
            )

    def get(self, job_id: str) -> Job | None:
        with Session(engine) as session:
            return session.get(Job, job_id)


jobs = JobManager()

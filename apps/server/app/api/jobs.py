"""任务中心接口：列表、详情、取消、SSE 实时快照（按用户隔离）。"""
from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, Depends
from sqlmodel import Session, select
from sse_starlette.sse import EventSourceResponse

from ..core.auth import current_user
from ..core.errors import ApiError
from ..core.jobs import jobs
from ..db import engine, get_session
from ..models import Job, User

router = APIRouter(prefix="/jobs", tags=["jobs"])

ACTIVE = ("queued", "running")


def _out(job: Job) -> dict:
    return {
        "id": job.id,
        "type": job.type,
        "title": job.title,
        "status": job.status,
        "progress": job.progress,
        "message": job.message,
        "error": job.error,
        "result": json.loads(job.result) if job.result else None,
        "created_at": job.created_at.isoformat() if job.created_at else None,
        "updated_at": job.updated_at.isoformat() if job.updated_at else None,
        "finished_at": job.finished_at.isoformat() if job.finished_at else None,
    }


@router.get("")
async def list_jobs(
    limit: int = 50,
    session: Session = Depends(get_session),
    user: User = Depends(current_user),
) -> list[dict]:
    rows = session.exec(
        select(Job)
        .where(Job.user_id == (user.id or 0))
        .order_by(Job.created_at.desc())
        .limit(limit)
    ).all()
    return [_out(j) for j in rows]


@router.get("/{job_id}")
async def get_job(
    job_id: str,
    session: Session = Depends(get_session),
    user: User = Depends(current_user),
) -> dict:
    job = session.get(Job, job_id)
    if job is None or job.user_id != (user.id or 0):
        raise ApiError("任务不存在", code="not_found", status=404)
    return _out(job)


@router.post("/{job_id}/cancel")
async def cancel_job(
    job_id: str,
    session: Session = Depends(get_session),
    user: User = Depends(current_user),
) -> dict:
    job = session.get(Job, job_id)
    if job is None or job.user_id != (user.id or 0):
        raise ApiError("任务不存在", code="not_found", status=404)
    if not jobs.cancel(job_id):
        raise ApiError("任务已经结束，无法取消", code="not_cancellable", status=409)
    return {"ok": True}


@router.get("/stream/events")
async def job_stream(user: User = Depends(current_user)) -> EventSourceResponse:
    user_id = user.id or 0

    async def gen():
        last = ""
        while True:
            with Session(engine) as session:
                active = session.exec(
                    select(Job)
                    .where(Job.user_id == user_id)
                    .where(Job.status.in_(ACTIVE))
                    .order_by(Job.created_at.desc())
                ).all()
                recent = session.exec(
                    select(Job)
                    .where(Job.user_id == user_id)
                    .order_by(Job.updated_at.desc())
                    .limit(8)
                ).all()
            payload = json.dumps(
                {"active": [_out(j) for j in active], "recent": [_out(j) for j in recent]},
                ensure_ascii=False,
            )
            if payload != last:
                yield {"event": "jobs", "data": payload}
                last = payload
            await asyncio.sleep(0.9)

    return EventSourceResponse(gen(), ping=20)

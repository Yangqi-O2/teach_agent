from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlmodel import Session, col, select

from ...core.auth import current_user
from ...core.errors import ApiError
from ...db import get_session
from ...models import User
from .models import Note

router = APIRouter(tags=["notes"])


class NoteIn(BaseModel):
    title: str = ""
    content: str = ""
    tags: str = ""


class NotePatch(BaseModel):
    title: str | None = None
    content: str | None = None
    tags: str | None = None


def _out(note: Note) -> dict:
    return {
        "id": note.id,
        "title": note.title,
        "content": note.content,
        "tags": [t for t in note.tags.split(",") if t],
        "created_at": note.created_at.isoformat() if note.created_at else None,
        "updated_at": note.updated_at.isoformat() if note.updated_at else None,
    }


@router.get("/items")
async def list_items(
    q: str = "",
    session: Session = Depends(get_session),
    user: User = Depends(current_user),
) -> list[dict]:
    stmt = (
        select(Note)
        .where(Note.user_id == (user.id or 0))
        .order_by(col(Note.created_at).desc())
        .limit(200)
    )
    if q:
        like = f"%{q}%"
        stmt = (
            select(Note)
            .where(Note.user_id == (user.id or 0))
            .where(col(Note.title).like(like) | col(Note.content).like(like))  # type: ignore[operator]
            .order_by(col(Note.created_at).desc())
            .limit(200)
        )
    return [_out(n) for n in session.exec(stmt).all()]


@router.post("/items")
async def create_item(
    body: NoteIn,
    session: Session = Depends(get_session),
    user: User = Depends(current_user),
) -> dict:
    title = body.title.strip() or (body.content.strip().splitlines() or ["无标题"])[0][:30]
    if not body.content.strip() and not body.title.strip():
        raise ApiError("内容不能为空", code="empty_note")
    note = Note(
        user_id=user.id or 0,
        title=title,
        content=body.content.strip(),
        tags=body.tags.strip(),
    )
    session.add(note)
    session.commit()
    session.refresh(note)
    return _out(note)


@router.patch("/items/{note_id}")
async def update_item(
    note_id: int,
    body: NotePatch,
    session: Session = Depends(get_session),
    user: User = Depends(current_user),
) -> dict:
    note = session.get(Note, note_id)
    if note is None or note.user_id != (user.id or 0):
        raise ApiError("速记不存在", code="not_found", status=404)
    if body.title is not None:
        note.title = body.title.strip()
    if body.content is not None:
        note.content = body.content
    if body.tags is not None:
        note.tags = body.tags.strip()
    note.updated_at = datetime.now(timezone.utc)
    session.add(note)
    session.commit()
    session.refresh(note)
    return _out(note)


@router.delete("/items/{note_id}")
async def delete_item(
    note_id: int,
    session: Session = Depends(get_session),
    user: User = Depends(current_user),
) -> dict:
    note = session.get(Note, note_id)
    if note is None or note.user_id != (user.id or 0):
        raise ApiError("速记不存在", code="not_found", status=404)
    session.delete(note)
    session.commit()
    return {"ok": True}

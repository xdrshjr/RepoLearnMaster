"""笔记服务（spec §5.2）。软删列在每个读取路径上都被过滤，由 `not_deleted()` 保证。"""

from __future__ import annotations

from sqlalchemy import select

from repolearn.core.clock import utcnow
from repolearn.core.errors import AppError
from repolearn.core.ids import new_id
from repolearn.models import Note
from repolearn.schemas.note import NoteCreate, NoteDetail, NotePatch
from repolearn.services.progress_service import LOCAL_USER_ID, ensure_local_user


def _to_detail(row: Note) -> NoteDetail:
    return NoteDetail(
        id=row.id,
        course_version_id=row.course_version_id,
        lesson_id=row.lesson_id,
        anchor_id=row.anchor_id,
        body_md=row.body_md,
        tags=list(row.tags or []),
        created_at=row.created_at.isoformat() if row.created_at else None,
        updated_at=row.updated_at.isoformat() if row.updated_at else None,
    )


async def create(session, payload: NoteCreate) -> NoteDetail:
    await ensure_local_user(session)
    row = Note(
        id=new_id("note"),
        user_id=LOCAL_USER_ID,
        course_version_id=payload.course_version_id,
        lesson_id=payload.lesson_id,
        anchor_id=payload.anchor_id,
        body_md=payload.body_md,
        tags=payload.tags,
        created_at=utcnow(),
        updated_at=utcnow(),
    )
    session.add(row)
    await session.flush()
    return _to_detail(row)


async def patch(session, note_id: str, payload: NotePatch) -> NoteDetail:
    row = await session.get(Note, note_id)
    if row is None or row.deleted_at is not None:
        raise AppError("OBJECT_MISSING", "笔记不存在", status=404)
    if payload.body_md is not None:
        row.body_md = payload.body_md
    if payload.tags is not None:
        row.tags = payload.tags
    row.updated_at = utcnow()
    await session.flush()
    return _to_detail(row)


async def delete(session, note_id: str) -> None:
    row = await session.get(Note, note_id)
    if row is None or row.deleted_at is not None:
        raise AppError("OBJECT_MISSING", "笔记不存在", status=404)
    row.deleted_at = utcnow()
    await session.flush()


async def list_notes(session, course_id: str | None = None) -> list[NoteDetail]:
    stmt = select(Note).where(Note.user_id == LOCAL_USER_ID, Note.deleted_at.is_(None))
    if course_id:
        stmt = stmt.where(Note.course_version_id == course_id)
    rows = (await session.execute(stmt.order_by(Note.created_at.desc()).limit(200))).scalars().all()
    return [_to_detail(row) for row in rows]

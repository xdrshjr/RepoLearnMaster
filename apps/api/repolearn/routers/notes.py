"""笔记路由（spec §5.2）。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Response, status

from repolearn.routers.deps import SessionDep, require_csrf, require_internal_token
from repolearn.schemas.note import NoteCreate, NoteDetail, NoteListResponse, NotePatch
from repolearn.services import note_service

router = APIRouter(prefix="/v1/notes", tags=["notes"], dependencies=[Depends(require_internal_token)])


@router.get("", response_model=NoteListResponse)
async def list_notes(session: SessionDep, course_id: str | None = None) -> NoteListResponse:
    return NoteListResponse(items=await note_service.list_notes(session, course_id))


@router.post("", response_model=NoteDetail, dependencies=[Depends(require_csrf)])
async def create_note(payload: NoteCreate, session: SessionDep) -> NoteDetail:
    return await note_service.create(session, payload)


@router.patch("/{note_id}", response_model=NoteDetail, dependencies=[Depends(require_csrf)])
async def patch_note(note_id: str, payload: NotePatch, session: SessionDep) -> NoteDetail:
    return await note_service.patch(session, note_id, payload)


@router.delete("/{note_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=[Depends(require_csrf)])
async def delete_note(note_id: str, session: SessionDep) -> Response:
    await note_service.delete(session, note_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)

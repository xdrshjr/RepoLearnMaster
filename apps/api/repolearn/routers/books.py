"""书籍与 PDF 路由（spec §5.2 第四组）。"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Header, Response, status

from repolearn.routers.deps import SessionDep, body_hash, require_csrf, require_internal_token
from repolearn.schemas.book import (
    BookChapterDetail,
    BookCreatedResponse,
    BookDetail,
    BookGenerateRequest,
    PdfCreateRequest,
    PdfStatus,
)
from repolearn.services import book_service

router = APIRouter(prefix="/v1", tags=["books"], dependencies=[Depends(require_internal_token)])


@router.post("/courses/{course_id}/books", response_model=BookCreatedResponse)
async def create_book(
    course_id: str,
    payload: BookGenerateRequest,
    session: SessionDep,
    response: Response,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
    _csrf: None = Depends(require_csrf),
) -> BookCreatedResponse:
    body, code = await book_service.create_book(
        session,
        course_id,
        preset=payload.preset,
        include_audio=payload.include_audio,
        idempotency_key=idempotency_key,
        request_hash=body_hash(payload.model_dump()),
    )
    response.status_code = code
    return body


@router.get("/books/{book_id}", response_model=BookDetail)
async def get_book(book_id: str, session: SessionDep) -> BookDetail:
    return await book_service.get_book(session, book_id)


@router.get("/books/{book_id}/chapters/{chapter_key}", response_model=BookChapterDetail)
async def get_chapter(book_id: str, chapter_key: str, session: SessionDep) -> BookChapterDetail:
    return await book_service.get_chapter(session, book_id, chapter_key)


@router.post("/books/{book_id}/pdf", status_code=status.HTTP_202_ACCEPTED, dependencies=[Depends(require_csrf)])
async def create_pdf(book_id: str, payload: PdfCreateRequest, session: SessionDep) -> dict:
    job_id = await book_service.create_pdf(session, book_id, engine=payload.engine)
    return {"job_id": job_id}


@router.get("/books/{book_id}/pdf", response_model=PdfStatus)
async def pdf_status(book_id: str, session: SessionDep) -> PdfStatus:
    return await book_service.pdf_status(session, book_id)

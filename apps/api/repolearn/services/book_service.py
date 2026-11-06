"""书籍与 PDF 服务（spec §3.10 / §5.2 第四组）。

幂等键 `sha256(course_version_id, preset, template_version)` 落在
`book_versions.cache_key`：同课程同 preset 第二次请求返回 `200 reused`，
**不新建 Job、不再花一遍排版与模型成本**（T-BOOK-1）。
"""

from __future__ import annotations

import hashlib

from sqlalchemy import select

from repolearn.core.clock import utcnow
from repolearn.core.config import settings
from repolearn.core.errors import AppError
from repolearn.core.ids import new_id
from repolearn.core.logging import get_logger
from repolearn.jobs import queue
from repolearn.models import BookChapter, BookVersion, CourseVersion, PdfExport
from repolearn.rendering.pdf import chromium_available
from repolearn.schemas.book import (
    BookChapterDetail,
    BookCreatedResponse,
    BookDetail,
    ChapterBrief,
    PdfStatus,
)
from repolearn.services import object_store
from repolearn.services.course_service import get_course

log = get_logger("book_service")

TEMPLATE_VERSION = "1"


def book_cache_key(course_version_id: str, preset: str, template_version: str = TEMPLATE_VERSION) -> str:
    raw = f"{course_version_id}|{preset}|{template_version}"
    return hashlib.sha256(raw.encode()).hexdigest()


def pdf_cache_key(book_version_id: str, engine: str = "chromium") -> str:
    raw = f"{book_version_id}|chromium-v1|{engine}"
    return hashlib.sha256(raw.encode()).hexdigest()


async def create_book(
    session, course_id: str, *, preset: str, include_audio: bool, idempotency_key: str | None, request_hash: str
) -> tuple[BookCreatedResponse, int]:
    if idempotency_key:
        cached = await queue.check_idempotency(
            session, scope="books.create", key=idempotency_key, request_hash=request_hash
        )
        if cached:
            return BookCreatedResponse(**cached), 200

    await get_course(session, course_id, require_ready=True)
    key = book_cache_key(course_id, preset)
    existing = (
        await session.execute(select(BookVersion).where(BookVersion.cache_key == key))
    ).scalar_one_or_none()
    if existing is not None and existing.status in ("ready", "generating"):
        response = BookCreatedResponse(book_id=existing.id, reused=True)
        await _store(session, idempotency_key, request_hash, response, None)
        return response, 200

    # 同一 cache_key 只有一个 book 行（唯一约束）。上次失败的行必须**复用**：
    # 再插一行会撞唯一约束 → 500，用户看到的是"这本书再也生成不出来"。
    book = existing
    if book is None:
        book = BookVersion(
            id=new_id("book"),
            course_version_id=course_id,
            cache_key=key,
            preset=preset,
            template_version=TEMPLATE_VERSION,
            title="",
            status="generating",
            quality={},
            created_at=utcnow(),
        )
        session.add(book)
    else:
        book.status = "generating"
        book.quality = {}
    await session.flush()
    job = await queue.enqueue(
        session,
        kind="book",
        payload={"book_id": book.id, "course_id": course_id, "preset": preset, "include_audio": include_audio},
        book_version_id=book.id,
        course_version_id=course_id,
        cache_key=key,
    )
    response = BookCreatedResponse(book_id=book.id, job_id=job.id)
    await _store(session, idempotency_key, request_hash, response, job.id)
    return response, 202


async def _store(session, key: str | None, request_hash: str, response: BookCreatedResponse, job_id: str | None) -> None:
    if not key:
        return
    await queue.store_idempotency(
        session,
        scope="books.create",
        key=key,
        request_hash=request_hash,
        response=response.model_dump(),
        job_id=job_id,
    )


async def get_book(session, book_id: str) -> BookDetail:
    book = await session.get(BookVersion, book_id)
    if book is None:
        raise AppError("OBJECT_MISSING", "书籍不存在", status=404)
    chapters = (
        await session.execute(
            select(BookChapter).where(BookChapter.book_version_id == book_id).order_by(BookChapter.order_index)
        )
    ).scalars().all()
    return BookDetail(
        id=book.id,
        course_version_id=book.course_version_id,
        preset=book.preset,
        status=book.status,
        title=book.title,
        chapters=[ChapterBrief(key=c.key, title=c.title, words=c.word_count) for c in chapters],
        toc=[{"key": c.key, "title": c.title, "order": c.order_index} for c in chapters],
        quality=dict(book.quality or {}),
        word_count=book.word_count,
    )


async def get_chapter(session, book_id: str, key: str) -> BookChapterDetail:
    row = (
        await session.execute(
            select(BookChapter).where(BookChapter.book_version_id == book_id, BookChapter.key == key)
        )
    ).scalar_one_or_none()
    if row is None:
        raise AppError("OBJECT_MISSING", "章节不存在", status=404)
    return BookChapterDetail(
        key=row.key,
        title=row.title,
        blocks=list(row.blocks or []),
        source_refs=list(row.source_refs or []),
    )


async def create_pdf(session, book_id: str, *, engine: str | None) -> str:
    book = await session.get(BookVersion, book_id)
    if book is None:
        raise AppError("OBJECT_MISSING", "书籍不存在", status=404)
    if book.status != "ready":
        raise AppError("COURSE_NOT_READY", "书籍还没生成完成")

    chosen = engine or settings.pdf_default_engine
    if chosen == "chromium" and not chromium_available():
        # G2 失败：**不生成假 PDF**，直接标成 browser-print 并返回可用的打印视图。
        chosen = "browser-print"
    key = pdf_cache_key(book_id, chosen)
    existing = (
        await session.execute(select(PdfExport).where(PdfExport.cache_key == key))
    ).scalar_one_or_none()
    if existing is not None:
        # 导出记录已存在：仍然建一个 Job，但复用同一条记录（cache_key 唯一），
        # 这样"重新导出"不会产生重复的 PDF 文件，也不会让库里的引用指向旧 URL。
        job = await queue.enqueue(
            session,
            kind="pdf",
            payload={"pdf_id": existing.id, "book_id": book_id, "engine": existing.engine},
            book_version_id=book_id,
            cache_key=key,
            priority=90,
        )
        existing.status = "queued"
        await session.flush()
        return job.id

    export = PdfExport(
        id=new_id("pdf"),
        book_version_id=book_id,
        cache_key=key,
        engine=chosen,
        status="queued",
        error={},
        created_at=utcnow(),
    )
    session.add(export)
    await session.flush()
    job = await queue.enqueue(
        session,
        kind="pdf",
        payload={"pdf_id": export.id, "book_id": book_id, "engine": chosen},
        book_version_id=book_id,
        cache_key=key,
    )
    return job.id


async def pdf_status(session, book_id: str) -> PdfStatus:
    book = await session.get(BookVersion, book_id)
    if book is None:
        raise AppError("OBJECT_MISSING", "书籍不存在", status=404)
    export = (
        await session.execute(
            select(PdfExport).where(PdfExport.book_version_id == book_id).order_by(PdfExport.created_at.desc()).limit(1)
        )
    ).scalar_one_or_none()
    course = await session.get(CourseVersion, book.course_version_id)
    if export is None:
        return PdfStatus(status="queued", engine=settings.pdf_default_engine, commit_sha=course.commit_sha if course else "")
    url = object_store.public_url("pdf", export.object_key) if export.object_key else None
    return PdfStatus(
        status=export.status,
        pdf_url=url,
        pages=export.pages,
        bytes=export.bytes,
        generated_at=export.finished_at.isoformat() if export.finished_at else None,
        commit_sha=course.commit_sha if course else "",
        engine=export.engine,
        print_view_url=f"/book/{book_id}/pdf?print=1" if export.engine == "browser-print" else None,
        error=dict(export.error or {}),
    )

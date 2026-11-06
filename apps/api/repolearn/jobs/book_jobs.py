"""书籍与 PDF 任务（spec §3.9 S5 / §3.10）。

书籍生成**复用课程资产分章**：章节来自 `course_versions.sections`，正文来自课时
的 narration + code_notes + trace。这样做的原因是成本——重新让模型写一本书等于
再跑一遍课程生成，而 PRD 明确要求"复用"。

PDF 引擎只有 Chromium（spec §13 问题 2）。Chromium 不可用时降级为
`engine='browser-print'` 并提供打印视图，**不生成假 PDF**。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select

from repolearn.core.clock import utcnow
from repolearn.core.config import settings
from repolearn.core.db import session_scope
from repolearn.core.errors import AppError
from repolearn.core.ids import new_id
from repolearn.core.logging import get_logger
from repolearn.models import BookChapter, BookVersion, CourseVersion, Lesson, PdfExport, Step
from repolearn.rendering.book_layout import build_chapters
from repolearn.services import object_store

log = get_logger("book_jobs")


async def run_book_job(*, job_id: str, payload: dict, emit: Any) -> Any:
    from repolearn.jobs.handlers import JobOutcome

    book_id = str(payload.get("book_id", ""))
    course_id = str(payload.get("course_id", ""))
    preset = str(payload.get("preset", "standard"))
    if not book_id or not course_id:
        raise AppError("INTERNAL", "书籍任务缺少 book_id/course_id")

    await emit("job.phase", {"node": "compose_book", "phase": "start", "progress": 10})
    async with session_scope() as session:
        book = await session.get(BookVersion, book_id)
        course = await session.get(CourseVersion, course_id)
        if book is None or course is None:
            raise AppError("INTERNAL", "书籍或课程不存在")
        lessons = (
            await session.execute(
                select(Lesson).where(Lesson.course_version_id == course_id).order_by(Lesson.order_index)
            )
        ).scalars().all()
        payload_lessons: list[dict] = []
        for lesson in lessons:
            steps = (
                await session.execute(select(Step).where(Step.lesson_id == lesson.id).order_by(Step.order_index))
            ).scalars().all()
            payload_lessons.append(
                {
                    "key": lesson.key,
                    "title": lesson.title,
                    "goal": lesson.goal,
                    "minutes": lesson.minutes,
                    "section_key": lesson.section_key,
                    "steps": [
                        {
                            "title": s.title,
                            "segments": s.segments or [],
                            "code_notes": s.code_notes or [],
                            "board": s.board or {},
                        }
                        for s in steps
                    ],
                    "files": (lesson.playback_meta or {}).get("files") or [],
                }
            )
        chapters = build_chapters(
            course_title=course.title or "课程书籍",
            commit_sha=course.commit_sha,
            repo_full_name=str((course.blueprint or {}).get("repo_full_name", "") or ""),
            sections=course.sections or [],
            lessons=payload_lessons,
            preset=preset,
        )
        for idx, chapter in enumerate(chapters):
            session.add(
                BookChapter(
                    id=new_id("chapter"),
                    book_version_id=book_id,
                    key=chapter["key"],
                    title=chapter["title"],
                    order_index=idx,
                    blocks=chapter["blocks"],
                    source_refs=chapter["source_refs"],
                    word_count=chapter["word_count"],
                    created_at=utcnow(),
                )
            )
        book.title = chapters[0]["blocks"][0].get("text", course.title or "课程书籍")[:180] if chapters else course.title or ""
        book.chapter_count = len(chapters)
        book.word_count = sum(c["word_count"] for c in chapters)
        book.quality = {
            "chapters": len(chapters),
            "words": book.word_count,
            "refs": sum(len(c["source_refs"]) for c in chapters),
            "preset": preset,
        }
        book.status = "ready" if chapters else "failed"
    await emit("job.phase", {"node": "compose_book", "phase": "done", "progress": 100})
    return JobOutcome(
        status="ready" if chapters else "failed",
        message=f"书籍生成完成：{len(chapters)} 章",
        details={"book_id": book_id, "chapters": len(chapters)},
    )


async def run_pdf_job(*, job_id: str, payload: dict, emit: Any) -> Any:
    from repolearn.jobs.handlers import JobOutcome
    from repolearn.rendering.pdf import render_pdf

    pdf_id = str(payload.get("pdf_id", ""))
    book_id = str(payload.get("book_id", ""))
    engine = str(payload.get("engine", settings.pdf_default_engine))
    if not pdf_id or not book_id:
        raise AppError("INTERNAL", "PDF 任务缺少 pdf_id/book_id")

    await emit("job.phase", {"node": "render_pdf", "phase": "start", "progress": 10})
    async with session_scope() as session:
        export = await session.get(PdfExport, pdf_id)
        book = await session.get(BookVersion, book_id)
        if export is None or book is None:
            raise AppError("INTERNAL", "PDF 导出记录或书籍不存在")
        chapters = (
            await session.execute(
                select(BookChapter).where(BookChapter.book_version_id == book_id).order_by(BookChapter.order_index)
            )
        ).scalars().all()
        course = await session.get(CourseVersion, book.course_version_id)

        html = _book_html(book, chapters, course)
        result = await render_pdf(html, engine=engine, name=f"{book_id}-{book.preset}-v{book.template_version}")
        export.engine = result.engine
        export.status = "ready" if result.ok else "failed"
        export.pages = result.pages
        export.bytes = len(result.data)
        export.object_key = result.object_key
        export.error = result.error or {}
        export.finished_at = utcnow()
    await emit("job.phase", {"node": "render_pdf", "phase": "done", "progress": 100})
    if not result.ok and result.engine == "chromium":
        raise AppError("PROVIDER_UNAVAILABLE", "PDF 引擎不可用", hint="按 G2 Gate 的提示安装 Chromium，或改用打印视图")
    return JobOutcome(
        status="ready" if result.ok else "failed",
        message=f"PDF 已生成（{result.pages} 页，{result.engine}）",
        details={
            "pdf_url": object_store.public_url("pdf", result.object_key) if result.object_key else None,
            "pages": result.pages,
            "bytes": len(result.data),
            "engine": result.engine,
        },
    )


def _book_html(book: BookVersion, chapters: list[BookChapter], course: CourseVersion | None) -> str:
    """服务端模板。**不插入原始 HTML**（spec §3.12）——所有内容都从结构化块渲染。"""
    from repolearn.rendering.book_layout import blocks_to_html

    parts = [
        "<!doctype html><html lang='zh-CN'><head><meta charset='utf-8'>",
        "<style>",
        "@page { size: A4; margin: 18mm 16mm; }",
        "body { font-family: 'PingFang SC','Microsoft YaHei',system-ui; color:#111; background:#fff; line-height:1.7; }",
        "h1 { font-size:26pt; margin:0 0 8pt; }",
        "h2 { font-size:17pt; margin:22pt 0 6pt; border-bottom:1px solid #ddd; padding-bottom:4pt; }",
        "h3 { font-size:13pt; margin:14pt 0 4pt; }",
        "pre { background:#f6f8f7; border:1px solid #e2e8e5; padding:8pt; font-size:9pt; overflow:hidden; }",
        "code { font-family:'JetBrains Mono',Consolas,monospace; font-size:9.5pt; }",
        ".meta { color:#666; font-size:9pt; }",
        ".ref { color:#666; font-size:8.5pt; }",
        "</style></head><body>",
        f"<h1>{_esc(book.title or '课程书籍')}</h1>",
        f"<p class='meta'>源仓库 {_esc(str((course.blueprint or {}).get('repo_full_name', '') if course else ''))} · "
        f"Commit {_esc((course.commit_sha if course else '')[:12])} · "
        f"License {_esc(str((course.blueprint or {}).get('license', '未标注') if course else '未标注'))}</p>",
    ]
    for idx, chapter in enumerate(chapters, start=1):
        parts.append(f"<h2>{idx}. {_esc(chapter.title)}</h2>")
        parts.append(blocks_to_html(chapter.blocks or []))
        if chapter.source_refs:
            refs = ", ".join(f"{r.get('file')}:{r.get('line_start', 1)}" for r in chapter.source_refs[:12] if isinstance(r, dict))
            parts.append(f"<p class='ref'>来源：{_esc(refs)}</p>")
    parts.append("</body></html>")
    return "".join(parts)


def _esc(text: str) -> str:
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )

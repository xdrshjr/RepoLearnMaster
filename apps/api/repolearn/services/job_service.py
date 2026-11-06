"""任务查询与指标（spec §5.2 第五组 / §3.13）。

`/v1/metrics` 用聚合 SQL 而不是内存计数：开发机重启一次，内存计数就归零，
而 PRD §6 的四项指标是"产品是否有效"的证据，不能因为重启而失真。
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from sqlalchemy import func, select

from repolearn.core.clock import utcnow
from repolearn.core.errors import AppError
from repolearn.models import (
    CostLedger,
    CourseVersion,
    Job,
    PdfExport,
    QuizAttempt,
    UserProgress,
)
from repolearn.schemas.job import JobCost, JobDetail, MetricsResponse

TERMINAL = ("ready", "partial", "failed", "failed_budget", "cancelled")


def to_detail(job: Job, cost: JobCost | None = None) -> JobDetail:
    return JobDetail(
        id=job.id,
        kind=job.kind,
        status=job.status,
        progress=job.progress,
        node=job.node,
        message=job.message,
        course_id=job.course_version_id,
        book_id=job.book_version_id,
        started_at=job.started_at.isoformat() if job.started_at else None,
        finished_at=job.finished_at.isoformat() if job.finished_at else None,
        error=dict(job.error or {}) or None,
        cost=cost or JobCost(),
        created_at=job.created_at.isoformat() if job.created_at else None,
        attempts=job.attempts,
    )


async def list_jobs(
    session, *, status: str | None = None, kind: str | None = None, limit: int = 20
) -> list[JobDetail]:
    stmt = select(Job)
    if status:
        stmt = stmt.where(Job.status == status)
    if kind:
        stmt = stmt.where(Job.kind == kind)
    rows = (
        await session.execute(stmt.order_by(Job.created_at.desc()).limit(min(limit, 50)))
    ).scalars().all()
    costs = await _costs(session, [row.id for row in rows])
    return [to_detail(row, costs.get(row.id)) for row in rows]


async def get_job(session, job_id: str) -> JobDetail:
    job = await session.get(Job, job_id)
    if job is None:
        raise AppError("JOB_NOT_FOUND")
    costs = await _costs(session, [job.id])
    return to_detail(job, costs.get(job.id))


async def _costs(session, job_ids: list[str]) -> dict[str, JobCost]:
    if not job_ids:
        return {}
    rows = (
        await session.execute(
            select(
                CostLedger.job_id,
                func.sum(CostLedger.tokens_in + CostLedger.tokens_out),
                func.sum(CostLedger.usd),
            )
            .where(CostLedger.job_id.in_(job_ids))
            .group_by(CostLedger.job_id)
        )
    ).all()
    return {str(job_id): JobCost(tokens=int(tokens or 0), usd=round(float(usd or 0), 6)) for job_id, tokens, usd in rows}


async def metrics(session) -> MetricsResponse:
    since = utcnow() - timedelta(days=7)
    total_jobs = int((await session.execute(select(func.count(Job.id)))).scalar() or 0)
    by_status = dict(
        (await session.execute(select(Job.status, func.count(Job.id)).group_by(Job.status))).all()
    )
    finished = int(sum(count for status, count in by_status.items() if status in TERMINAL))
    success = int(by_status.get("ready", 0) + by_status.get("partial", 0))
    courses = int((await session.execute(select(func.count(CourseVersion.id)))).scalar() or 0)
    reused = int(
        (
            await session.execute(
                select(func.count(CourseVersion.id)).where(CourseVersion.status.in_(("ready", "partial")))
            )
        ).scalar()
        or 0
    )
    tokens = int((await session.execute(select(func.sum(CostLedger.tokens_in + CostLedger.tokens_out)))).scalar() or 0)
    usd = float((await session.execute(select(func.sum(CostLedger.usd)))).scalar() or 0)
    attempts = int((await session.execute(select(func.count(QuizAttempt.id)))).scalar() or 0)
    correct = int(
        (await session.execute(select(func.count(QuizAttempt.id)).where(QuizAttempt.correct.is_(True)))).scalar() or 0
    )
    completed = int(
        (
            await session.execute(
                select(func.count(UserProgress.id)).where(UserProgress.percent >= 100)
            )
        ).scalar()
        or 0
    )
    progress_rows = int((await session.execute(select(func.count(UserProgress.id)))).scalar() or 0)
    pdfs = int(
        (await session.execute(select(func.count(PdfExport.id)).where(PdfExport.status == "ready"))).scalar() or 0
    )
    books = int(
        (
            await session.execute(select(func.count(func.distinct(PdfExport.book_version_id))))
        ).scalar()
        or 0
    )
    duration_rows = (
        await session.execute(
            select(Job.started_at, Job.finished_at).where(Job.finished_at.isnot(None)).limit(200)
        )
    ).all()
    durations = sorted(
        [
            (finished_at - started_at).total_seconds()
            for started_at, finished_at in duration_rows
            if started_at and finished_at
        ]
    )
    return MetricsResponse(
        jobs={
            "total": total_jobs,
            "by_status": {str(k): int(v) for k, v in by_status.items()},
            "success_rate": round(success / max(1, finished), 3),
            "p50_seconds": round(durations[len(durations) // 2], 1) if durations else 0.0,
            "p95_seconds": round(durations[int(len(durations) * 0.95)] if durations else 0.0, 1),
        },
        cache={
            "courses": courses,
            "readable_courses": reused,
            "reuse_rate": round(reused / max(1, courses), 3),
        },
        providers={
            "tokens": tokens,
            "usd": round(usd, 6),
            "since": since.isoformat(),
        },
        learning={
            "quiz_answered": attempts,
            "quiz_accuracy": round(correct / max(1, attempts), 3),
            "courses_started": progress_rows,
            "courses_completed": completed,
            "completion_rate": round(completed / max(1, progress_rows), 3),
            "pdf_exports": pdfs,
            "books_with_pdf": books,
        },
        generated_at=utcnow().isoformat(),
    )


async def cancel(session, job_id: str) -> str:
    """取消任务。`queued` 当场终结，`running` 由 runner 的心跳观察到之后再收敛。

    终结路径必须**顺手把课程从 `generating` 里放出来**：取消一个排队中的任务时
    没有任何 worker 会替它收尾，课程会一直停在"生成中"，直到 reaper 在
    `job_deadline + grace`（默认 30 分钟）之后才回收。
    """
    from repolearn.jobs import queue

    job = await session.get(Job, job_id)
    if job is None:
        raise AppError("JOB_NOT_FOUND")
    status = await queue.request_cancel(session, job_id)
    if status == "cancelled":
        await _mark_generation_cancelled(session, job.course_version_id)
    return status


async def _mark_generation_cancelled(session, course_id: str | None) -> None:
    if not course_id:
        return
    course = await session.get(CourseVersion, course_id)
    if course is None or course.status != "generating":
        return
    course.status = "failed"
    course.updated_at = utcnow()
    course.warnings = list(course.warnings or []) + [
        {
            "code": "GENERATION_CANCELLED",
            "message": "生成已被取消，可以重新发起",
            "severity": "info",
            "node": "cancel",
        }
    ]


async def retry(session, job_id: str) -> str:
    from repolearn.jobs import queue

    job = await queue.retry(session, job_id)
    return job.id


async def job_events(session, job_id: str, last_event_id: int = 0) -> tuple[list[Any], bool]:
    from repolearn.jobs import events as job_events_mod

    job = await session.get(Job, job_id)
    if job is None:
        raise AppError("JOB_NOT_FOUND")
    return await job_events_mod.replay(session, job_id, last_event_id)

"""Job Runner（spec §3.11.1–3.11.4）。

三件事各自对应一个真实事故：

1. **心跳**（P1-1）。N6 单节点跑 10 分钟以上是常态（12 课时 × 多轮取证）。若只在
   "节点推进"时写 `heartbeat_at` 且回收阈值是 90 秒，任务会被自己判死 →
   重复执行 → 重复烧 token。因此节点执行期间有一个 15 秒周期的后台任务，
   节点结束即取消；回收阈值只在**心跳本身也停更**时才生效。
2. **reaper**（P1-13）。API 在 N9 之前重启（开发期每天都在发生），
   `course_versions.status='generating'` 的行会永久卡住，同一 `cache_key` 的
   新请求又被 `generation_locks` 挡住 → 这个仓库从此无法再生成课程。
   reaper 必须先删锁再改状态：反序会留下"状态已失败的锁"，同样卡住重建。
3. **并发默认 1**（P1-2）。SQLite 单写者下并发 2 会让两个 Job 的写入互相触发
   `busy_timeout`，表现为"偶发 5 秒卡顿"，比串行更慢且更难查。
"""

from __future__ import annotations

import asyncio
import contextlib
import os
from datetime import timedelta
from typing import Any

from sqlalchemy import select, update

from repolearn.core.clock import utcnow
from repolearn.core.config import settings
from repolearn.core.db import session_scope
from repolearn.core.errors import AppError
from repolearn.core.logging import get_logger
from repolearn.jobs import events as job_events
from repolearn.jobs import queue
from repolearn.models import CourseVersion, GenerationLock, Job

log = get_logger("runner")

WORKER_ID = f"worker-{os.getpid()}"
POLL_INTERVAL_S = 1.0
REAPER_INTERVAL_S = 60.0
ORPHAN_GRACE_S = 300.0


class JobRunner:
    """lifespan 内启动的常驻循环。"""

    def __init__(self) -> None:
        self._stop = asyncio.Event()
        self._tasks: list[asyncio.Task] = []
        self._running: dict[str, asyncio.Task] = {}
        self._semaphore = asyncio.Semaphore(max(1, settings.max_concurrent_jobs))
        self.started_at = utcnow()

    # ---- 生命周期 --------------------------------------------------------
    async def start(self) -> None:
        self._stop.clear()
        self._tasks = [
            asyncio.create_task(self._loop(), name="job-runner"),
            asyncio.create_task(self._reaper_loop(), name="reaper"),
        ]
        log.info("runner_started", worker=WORKER_ID, concurrency=settings.max_concurrent_jobs)

    async def stop(self) -> None:
        self._stop.set()
        for task in self._tasks:
            task.cancel()
        for task in self._running.values():
            task.cancel()
        for task in [*self._tasks, *self._running.values()]:
            with contextlib.suppress(asyncio.CancelledError):
                await task
        self._tasks.clear()
        self._running.clear()
        log.info("runner_stopped", worker=WORKER_ID)

    # ---- 主循环 ----------------------------------------------------------
    async def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                await self._tick()
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 - 主循环不能因单次异常退出
                log.error("runner_tick_failed", error=str(exc))
            with contextlib.suppress(asyncio.TimeoutError):
                await asyncio.wait_for(self._stop.wait(), timeout=POLL_INTERVAL_S)

    async def _tick(self) -> None:
        if len(self._running) >= max(1, settings.max_concurrent_jobs):
            return
        async with session_scope() as session:
            claimed = await queue.claim_next(session, WORKER_ID)
        if claimed is None:
            return
        task = asyncio.create_task(self._execute(claimed), name=f"job-{claimed.id}")
        self._running[claimed.id] = task
        task.add_done_callback(lambda _t, jid=claimed.id: self._running.pop(jid, None))

    # ---- 单任务执行 ------------------------------------------------------
    async def _execute(self, claimed: queue.ClaimedJob) -> None:
        job_id = claimed.id
        async with session_scope() as session:
            await queue.mark_running(session, job_id)
            await job_events.seed_bus_seq(session, job_id)
            await job_events.emit(session, job_id, "job.phase", {"node": None, "phase": "claimed", "progress": 0})

        async def emit(event_type: str, data: dict[str, Any]) -> None:
            async with session_scope() as s:
                await job_events.emit(s, job_id, event_type, data)

        heartbeat_task = asyncio.create_task(self._heartbeat_loop(job_id), name=f"hb-{job_id}")
        try:
            outcome = await self._dispatch(claimed, emit)
            async with session_scope() as session:
                # 取消可能发生在最后一个节点执行期间：此时任务已经跑完，但用户
                # 的意图是"停下"。以 `cancelling` 为准，别把取消覆盖成成功。
                if await queue.is_cancelling(session, job_id):
                    await queue.finish(session, job_id, status="cancelled", message="已取消")
                    await queue.release_locks_for(session, job_id)
                    await self._fail_course(session, claimed.course_version_id, "任务被取消")
                    await job_events.emit(
                        session,
                        job_id,
                        "job.completed",
                        {"status": "cancelled", "courseId": claimed.course_version_id, "details": {}},
                    )
                    return
                await queue.finish(session, job_id, status=outcome.status, message=outcome.message)
                await queue.release_locks_for(session, job_id)
                await job_events.emit(
                    session,
                    job_id,
                    "job.completed",
                    {
                        "status": outcome.status,
                        "courseId": claimed.course_version_id,
                        "details": outcome.details or {},
                    },
                )
            log.info("job_completed", job_id=job_id, status=outcome.status)
        except asyncio.CancelledError:
            async with session_scope() as session:
                await queue.finish(session, job_id, status="cancelled", message="已取消")
                await queue.release_locks_for(session, job_id)
                await self._fail_course(session, claimed.course_version_id, "任务被取消")
            raise
        except AppError as exc:
            status = "failed_budget" if exc.code == "BUDGET_EXCEEDED" else "failed"
            async with session_scope() as session:
                await queue.finish(session, job_id, status=status, error=exc.to_body(), message=exc.message)
                await queue.release_locks_for(session, job_id)
                await self._fail_course(session, claimed.course_version_id, exc.message)
                await job_events.emit(
                    session,
                    job_id,
                    "job.failed",
                    {"code": exc.code, "message": exc.message, "retryable": exc.retryable},
                )
            log.warning("job_failed", job_id=job_id, code=exc.code, message=exc.message)
        except Exception as exc:  # noqa: BLE001 - 未预期异常也必须收敛终态
            async with session_scope() as session:
                await queue.finish(
                    session,
                    job_id,
                    status="failed",
                    error={"code": "INTERNAL", "message": str(exc)[:400]},
                    message="生成过程中出现内部错误",
                )
                await queue.release_locks_for(session, job_id)
                await self._fail_course(session, claimed.course_version_id, str(exc)[:200])
                await job_events.emit(
                    session,
                    job_id,
                    "job.failed",
                    {"code": "INTERNAL", "message": str(exc)[:400], "retryable": True},
                )
            log.error("job_crashed", job_id=job_id, error=str(exc))
        finally:
            heartbeat_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await heartbeat_task

    async def _dispatch(self, claimed: queue.ClaimedJob, emit: Any) -> Any:
        if claimed.kind == "course":
            from repolearn.jobs.handlers import run_course_job

            if not claimed.course_version_id:
                raise AppError("INTERNAL", "课程任务缺少 course_id")
            return await run_course_job(
                job_id=claimed.id,
                course_id=claimed.course_version_id,
                payload=claimed.payload,
                emit=emit,
            )
        if claimed.kind in ("book", "pdf"):
            from repolearn.jobs.book_jobs import run_book_job, run_pdf_job

            if claimed.kind == "book":
                return await run_book_job(job_id=claimed.id, payload=claimed.payload, emit=emit)
            return await run_pdf_job(job_id=claimed.id, payload=claimed.payload, emit=emit)
        raise AppError("INTERNAL", f"未知任务类型：{claimed.kind}")

    async def _heartbeat_loop(self, job_id: str) -> None:
        """心跳 + 取消观察。

        两者必须住在同一个循环里：`request_cancel` 只能把数据库里的状态改成
        `cancelling`，**取消 asyncio 任务需要进程内的句柄**。若没有这个观察点，
        用户点了取消之后任务会一直跑到自然结束，最后 `finish()` 再把
        `cancelling` 覆盖成 `ready` —— 界面上表现为"取消按钮无效"。
        """
        interval = max(3, settings.heartbeat_seconds)
        while True:
            try:
                await asyncio.sleep(interval)
                async with session_scope() as session:
                    await queue.heartbeat(session, job_id)
                    cancelled = await queue.is_cancelling(session, job_id)
                if cancelled:
                    task = self._running.get(job_id)
                    if task is not None:
                        log.info("job_cancel_observed", job_id=job_id)
                        task.cancel()
                    return
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                log.warning("heartbeat_failed", job_id=job_id, error=str(exc))

    async def _fail_course(self, session, course_id: str | None, reason: str) -> None:
        if not course_id:
            return
        course = await session.get(CourseVersion, course_id)
        if course is None or course.status != "generating":
            return
        course.status = "failed"
        course.updated_at = utcnow()
        course.warnings = list(course.warnings or []) + [
            {"code": "GENERATION_FAILED", "message": reason[:400], "severity": "error", "node": "publish_course"}
        ]

    # ---- reaper ----------------------------------------------------------
    async def _reaper_loop(self) -> None:
        # 启动时立刻跑一次：重启后的第一秒就要把僵尸版本收掉
        while not self._stop.is_set():
            try:
                await reap_orphaned_generations()
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                log.error("reaper_failed", error=str(exc))
            with contextlib.suppress(asyncio.TimeoutError):
                await asyncio.wait_for(self._stop.wait(), timeout=REAPER_INTERVAL_S)

    # ---- 测试辅助 --------------------------------------------------------
    async def drain_once(self) -> None:
        """测试用：同步跑一轮 claim（不等后台循环）。"""
        await self._tick()
        if self._running:
            await asyncio.gather(*list(self._running.values()), return_exceptions=True)


async def reap_orphaned_generations(grace_seconds: float = ORPHAN_GRACE_S) -> dict[str, int]:
    """回收僵尸生成版本（spec §3.11.2 P1-13 / T-DB-4）。

    判定：`status='generating'` 且 `updated_at` 早于 `now - job_deadline - grace`
    且没有对应活跃 Job。**先删锁再改状态**。
    """
    now = utcnow()
    cutoff = now - timedelta(milliseconds=settings.job_deadline_ms + grace_seconds * 1000)
    reaped = 0
    locks_released = 0
    async with session_scope() as session:
        stale = (
            await session.execute(
                select(CourseVersion).where(
                    CourseVersion.status == "generating",
                    (CourseVersion.updated_at.is_(None)) | (CourseVersion.updated_at < cutoff),
                )
            )
        ).scalars().all()
        for course in stale:
            active = (
                await session.execute(
                    select(Job.id)
                    .where(
                        Job.course_version_id == course.id,
                        Job.status.in_(queue.ACTIVE_OR_CANCELLING),
                    )
                    .limit(1)
                )
            ).scalar_one_or_none()
            if active is not None:
                continue
            locks = (
                await session.execute(select(GenerationLock).where(GenerationLock.cache_key == course.cache_key))
            ).scalars().all()
            for lock in locks:
                await session.delete(lock)
                locks_released += 1
            await session.flush()
            course.status = "failed"
            course.updated_at = now
            course.warnings = list(course.warnings or []) + [
                {
                    "code": "ORPHANED_GENERATION",
                    "message": "上次生成中断（服务可能重启过），可以重新生成",
                    "severity": "warning",
                    "node": "reaper",
                }
            ]
            reaped += 1
        await session.flush()
    if reaped:
        log.warning("orphans_reaped", courses=reaped, locks=locks_released)
    return {"courses": reaped, "locks": locks_released}


async def requeue_stale_jobs(stale_seconds: int | None = None) -> int:
    """把心跳停更超过阈值的 running Job 放回队列（T-JOB-3）。

    阈值是 `REPOLEARN_JOB_STALE_SECONDS`（默认 90 秒）。因为节点执行期间有 15 秒
    心跳，只有**心跳也停了**才会命中——这正是"误杀正常运行的任务"的防线。
    """
    threshold = utcnow() - timedelta(seconds=stale_seconds or settings.job_stale_seconds)
    async with session_scope() as session:
        result = await session.execute(
            update(Job)
            .where(
                Job.status.in_(("claimed", "running")),
                (Job.heartbeat_at.is_(None)) | (Job.heartbeat_at < threshold),
            )
            .values(status="queued", worker_id=None, node=None, message="检测到任务中断，已重新排队")
        )
        return int(result.rowcount or 0)


_runner: JobRunner | None = None


def get_runner() -> JobRunner:
    global _runner
    if _runner is None:
        _runner = JobRunner()
    return _runner


async def start_runner() -> JobRunner:
    runner = get_runner()
    await runner.start()
    return runner


async def stop_runner() -> None:
    global _runner
    if _runner is not None:
        await _runner.stop()
        _runner = None

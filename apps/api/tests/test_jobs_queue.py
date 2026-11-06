"""任务队列与可靠性（T-JOB-1 / T-JOB-3 / T-JOB-6 / T-DB-4）。

这四条断言对应四个真实事故：
* 重复创建 Job（并发点两下）→ 生成两遍、烧两遍 token；
* 心跳缺失导致正常运行的任务被自己判死 → 重复执行；
* API 重启留下僵尸 `generating` 版本 → 这个仓库从此无法再生成课程；
* 生成锁没释放 → 同 cache_key 的重建永远 409。
"""

from __future__ import annotations

import asyncio
from datetime import timedelta

from sqlalchemy import select

from repolearn.core.clock import utcnow
from repolearn.core.db import session_scope
from repolearn.core.ids import new_id
from repolearn.jobs import queue
from repolearn.jobs.runner import reap_orphaned_generations, requeue_stale_jobs
from repolearn.models import CourseVersion, GenerationLock, Job, Repository


async def _course(cache_key: str = "ck-1", status: str = "generating", age_seconds: int = 0) -> str:
    async with session_scope() as session:
        repo = Repository(
            id=new_id("repository"),
            full_name=f"owner/{cache_key}",
            owner="owner",
            name=cache_key,
            description="",
            stars=0,
            license_spdx="MIT",
            primary_language="Python",
            default_branch="main",
            html_url="",
            is_public=True,
            created_at=utcnow(),
            updated_at=utcnow(),
        )
        session.add(repo)
        await session.flush()
        course = CourseVersion(
            id=new_id("course_version"),
            repository_id=repo.id,
            commit_sha="a" * 40,
            cache_key=cache_key,
            title="t",
            status=status,
            sections=[],
            quality_report={},
            warnings=[],
            blueprint={},
            created_at=utcnow(),
            updated_at=utcnow() - timedelta(seconds=age_seconds),
        )
        session.add(course)
        await session.flush()
        return course.id


async def test_claim_is_atomic_single_winner():
    """T-JOB-1 的队列侧：5 个 worker 抢 1 个 Job，只能有 1 个抢到。"""
    async with session_scope() as session:
        job = await queue.enqueue(session, kind="course", payload={"repo_url": "x"}, cache_key="ck-a")
        job_id = job.id

    async def claim(worker: str):
        async with session_scope() as session:
            return await queue.claim_next(session, worker)

    results = await asyncio.gather(*(claim(f"w{i}") for i in range(5)))
    winners = [r for r in results if r is not None]
    assert len(winners) == 1
    assert winners[0].id == job_id

    async with session_scope() as session:
        row = await session.get(Job, job_id)
        assert row.status == "claimed"
        assert row.attempts == 1
        assert row.heartbeat_at is not None


async def test_heartbeat_then_requeue_only_when_stale():
    """T-JOB-6：有心跳就不该被回收；心跳停了才回收。"""
    async with session_scope() as session:
        job = await queue.enqueue(session, kind="course", payload={})
        job_id = job.id
        await queue.claim_next(session, "w1")

    # 心跳新鲜（模拟节点执行期间的后台心跳）
    async with session_scope() as session:
        await queue.heartbeat(session, job_id)
    assert await requeue_stale_jobs(stale_seconds=90) == 0

    # 把心跳推到阈值之前
    async with session_scope() as session:
        await session.execute(
            Job.__table__.update().where(Job.id == job_id).values(heartbeat_at=utcnow() - timedelta(seconds=600))
        )
    assert await requeue_stale_jobs(stale_seconds=90) == 1
    async with session_scope() as session:
        row = await session.get(Job, job_id)
        assert row.status == "queued"


async def test_reaper_fixes_orphaned_generation_and_releases_lock():
    """T-DB-4：僵尸 `generating` 必须被置 failed，且**先删锁再改状态**。"""
    course_id = await _course(cache_key="ck-orphan", age_seconds=10_000)
    async with session_scope() as session:
        session.add(
            GenerationLock(
                cache_key="ck-orphan",
                job_id="job_gone",
                acquired_at=utcnow(),
                expires_at=utcnow() + timedelta(minutes=30),
            )
        )

    result = await reap_orphaned_generations()
    assert result["courses"] >= 1
    assert result["locks"] >= 1

    async with session_scope() as session:
        course = await session.get(CourseVersion, course_id)
        assert course.status == "failed"
        assert any(w.get("code") == "ORPHANED_GENERATION" for w in (course.warnings or []))
        locks = (await session.execute(select(GenerationLock).where(GenerationLock.cache_key == "ck-orphan"))).scalars().all()
        assert locks == []


async def test_reaper_skips_course_with_active_job():
    course_id = await _course(cache_key="ck-active", age_seconds=10_000)
    async with session_scope() as session:
        await queue.enqueue(session, kind="course", payload={}, course_version_id=course_id, cache_key="ck-active")
    await reap_orphaned_generations()
    async with session_scope() as session:
        course = await session.get(CourseVersion, course_id)
        assert course.status == "generating"


async def test_generation_lock_blocks_second_holder():
    async with session_scope() as session:
        assert await queue.acquire_lock(session, "ck-x", "job_1") is True
    async with session_scope() as session:
        assert await queue.acquire_lock(session, "ck-x", "job_2") is False
        assert await queue.lock_holder(session, "ck-x") == "job_1"


async def test_expired_lock_is_reclaimable():
    async with session_scope() as session:
        session.add(
            GenerationLock(
                cache_key="ck-exp",
                job_id="job_old",
                acquired_at=utcnow() - timedelta(hours=2),
                expires_at=utcnow() - timedelta(hours=1),
            )
        )
    async with session_scope() as session:
        assert await queue.lock_holder(session, "ck-exp") is None
        assert await queue.acquire_lock(session, "ck-exp", "job_new") is True


async def test_idempotency_scope_isolation():
    """T-IDEM-1：同一个 key 用在两个 scope 上互不影响。"""
    async with session_scope() as session:
        await queue.store_idempotency(
            session, scope="courses.create", key="same-key", request_hash="h1", response={"course_id": "c1"}
        )
    async with session_scope() as session:
        assert await queue.check_idempotency(session, scope="books.create", key="same-key", request_hash="h2") is None
        hit = await queue.check_idempotency(session, scope="courses.create", key="same-key", request_hash="h1")
        assert hit == {"course_id": "c1"}


async def test_idempotency_mismatch_raises():
    from repolearn.core.errors import AppError

    async with session_scope() as session:
        await queue.store_idempotency(
            session, scope="courses.create", key="k2", request_hash="hash-a", response={"ok": True}
        )
    async with session_scope() as session:
        try:
            await queue.check_idempotency(session, scope="courses.create", key="k2", request_hash="hash-b")
        except AppError as exc:
            assert exc.code == "IDEMPOTENCY_MISMATCH"
        else:  # pragma: no cover
            raise AssertionError("同键异体必须 422")


async def test_finish_sets_terminal_state():
    async with session_scope() as session:
        job = await queue.enqueue(session, kind="course", payload={})
        job_id = job.id
        await queue.claim_next(session, "w1")
        await queue.finish(session, job_id, status="ready", message="done")
    async with session_scope() as session:
        row = await session.get(Job, job_id)
        assert row.status == "ready"
        assert row.progress == 100
        assert row.finished_at is not None

"""任务队列（spec §3.11.2 / §3.12）。

不引入 Redis，用**条件 UPDATE + rowcount** 做原子 claim：

```sql
UPDATE jobs SET status='claimed', worker_id=?
 WHERE id = (SELECT id FROM jobs WHERE status='queued' AND run_after <= now
             ORDER BY priority, created_at LIMIT 1)
   AND status='queued'
```

`rowcount == 1` 表示"我抢到了"。这是跨方言成立的原子性（SQLite 单写者、PG 行锁），
也是本项目"零依赖启动"能在不引入消息队列的前提下成立的原因。

**幂等键在 `idempotency_keys` 表里**（scope + key），不在 jobs 上（P1-12）。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from repolearn.core.clock import utcnow
from repolearn.core.errors import AppError
from repolearn.core.ids import new_id
from repolearn.core.logging import get_logger
from repolearn.models import GenerationLock, IdempotencyKey, Job

log = get_logger("queue")

ACTIVE_STATUSES = ("queued", "claimed", "running")
#: `cancelling` 也算"还有人在为这份内容干活"：取消是一个正在收敛的过程，
#: 此时把它当终态会让 reaper 立刻把课程判死，用户看到"取消 → 生成失败"的抖动。
ACTIVE_OR_CANCELLING = (*ACTIVE_STATUSES, "cancelling")
TERMINAL_STATUSES = ("ready", "partial", "failed", "failed_budget", "cancelled")


@dataclass
class ClaimedJob:
    id: str
    kind: str
    payload: dict
    course_version_id: str | None
    book_version_id: str | None
    cache_key: str | None
    attempts: int


async def enqueue(
    session: AsyncSession,
    *,
    kind: str,
    payload: dict,
    course_version_id: str | None = None,
    book_version_id: str | None = None,
    cache_key: str | None = None,
    priority: int = 100,
    run_after: datetime | None = None,
) -> Job:
    job = Job(
        id=new_id("job"),
        kind=kind,
        status="queued",
        priority=priority,
        payload=payload,
        course_version_id=course_version_id,
        book_version_id=book_version_id,
        cache_key=cache_key,
        progress=0,
        error={},
        run_after=run_after or utcnow(),
        created_at=utcnow(),
    )
    session.add(job)
    await session.flush()
    log.info("job_enqueued", job_id=job.id, kind=kind, cache_key=cache_key)
    return job


async def claim_next(session: AsyncSession, worker_id: str) -> ClaimedJob | None:
    """原子 claim 一个 queued 任务。没有可领的任务返回 None（不是错误）。"""
    now = utcnow()
    candidate = (
        await session.execute(
            select(Job.id)
            .where(Job.status == "queued")
            .where((Job.run_after.is_(None)) | (Job.run_after <= now))
            .order_by(Job.priority.asc(), Job.created_at.asc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if candidate is None:
        return None
    result = await session.execute(
        update(Job)
        .where(Job.id == candidate, Job.status == "queued")
        .values(
            status="claimed",
            worker_id=worker_id,
            heartbeat_at=now,
            started_at=now,
            attempts=Job.attempts + 1,
        )
    )
    if result.rowcount != 1:
        # 另一个 worker 抢到了。这不是错误，下一次轮询继续。
        return None
    job = await session.get(Job, candidate)
    if job is None:
        return None
    return ClaimedJob(
        id=job.id,
        kind=job.kind,
        payload=dict(job.payload or {}),
        course_version_id=job.course_version_id,
        book_version_id=job.book_version_id,
        cache_key=job.cache_key,
        attempts=job.attempts,
    )


async def mark_running(session: AsyncSession, job_id: str, node: str | None = None) -> None:
    await session.execute(
        update(Job)
        .where(Job.id == job_id)
        .values(status="running", heartbeat_at=utcnow(), node=node, message=None)
    )


async def update_progress(
    session: AsyncSession, job_id: str, *, node: str | None = None, progress: int | None = None, message: str | None = None
) -> None:
    values: dict[str, Any] = {"heartbeat_at": utcnow()}
    if node is not None:
        values["node"] = node
    if progress is not None:
        values["progress"] = max(0, min(100, progress))
    if message is not None:
        values["message"] = message[:480]
    await session.execute(update(Job).where(Job.id == job_id).values(**values))


async def heartbeat(session: AsyncSession, job_id: str) -> None:
    """节点执行期间每 15 秒一次（spec §3.11.2 P1-1）。

    只更新 `heartbeat_at`：如果把 `updated_at` 之类也写进去，回收判定会被
    "心跳"本身干扰，阈值就失效了。
    """
    await session.execute(update(Job).where(Job.id == job_id).values(heartbeat_at=utcnow()))


async def finish(
    session: AsyncSession,
    job_id: str,
    *,
    status: str,
    error: dict | None = None,
    message: str | None = None,
) -> None:
    values: dict[str, Any] = {
        "status": status,
        "finished_at": utcnow(),
        "heartbeat_at": utcnow(),
        "node": None,
    }
    if status in ("ready", "partial"):
        values["progress"] = 100
    if error:
        values["error"] = error
    if message:
        values["message"] = message[:480]
    await session.execute(update(Job).where(Job.id == job_id).values(**values))


async def request_cancel(session: AsyncSession, job_id: str) -> str:
    """请求取消。

    两条路径的语义必须分开，否则"取消"只是一个好看的状态名：

    * `queued` —— 还没有 worker 领走。**当场终结**并释放生成锁，因为这个 Job
      永远不会有人来收尾；留成中间态会让它在列表里永远显示"取消中"。
    * `claimed` / `running` —— 正在跑。只能置 `cancelling`，由 runner 的心跳循环
      观察到之后真正 cancel 掉 asyncio 任务（见 `runner._heartbeat_loop`）。
      这里连 abort 都做不到：DB 层没有那个任务的句柄。
    """
    job = await session.get(Job, job_id)
    if job is None:
        raise AppError("JOB_NOT_FOUND")
    if job.status in TERMINAL_STATUSES:
        return job.status
    if job.status == "queued":
        await session.execute(
            update(Job)
            .where(Job.id == job_id)
            .values(status="cancelled", finished_at=utcnow(), heartbeat_at=utcnow(), message="已取消")
        )
        await release_locks_for(session, job_id)
        return "cancelled"
    await session.execute(update(Job).where(Job.id == job_id).values(status="cancelling", message="正在取消"))
    return "cancelling"


async def is_cancelling(session: AsyncSession, job_id: str) -> bool:
    """runner 的心跳循环用它把"用户点了取消"翻译成"取消 asyncio 任务"。"""
    status = (await session.execute(select(Job.status).where(Job.id == job_id))).scalar_one_or_none()
    return status == "cancelling"


async def retry(session: AsyncSession, job_id: str) -> Job:
    job = await session.get(Job, job_id)
    if job is None:
        raise AppError("JOB_NOT_FOUND")
    return await enqueue(
        session,
        kind=job.kind,
        payload=dict(job.payload or {}),
        course_version_id=job.course_version_id,
        book_version_id=job.book_version_id,
        cache_key=job.cache_key,
        priority=max(1, job.priority - 10),
    )


# --------------------------------------------------------------------------- #
# 幂等键                                                                       #
# --------------------------------------------------------------------------- #


async def check_idempotency(
    session: AsyncSession, *, scope: str, key: str, request_hash: str
) -> dict | None:
    """命中返回首次响应的快照；同键异体抛 `IDEMPOTENCY_MISMATCH`。

    为什么必须比较 `request_hash`：静默返回首次结果会掩盖调用方的 bug
    （用户改了参数却拿到旧结果，这是最难归因的一类"功能不生效"）。
    """
    row = (
        await session.execute(
            select(IdempotencyKey).where(IdempotencyKey.scope == scope, IdempotencyKey.key == key)
        )
    ).scalar_one_or_none()
    if row is None:
        return None
    if row.expires_at is not None and row.expires_at < utcnow():
        await session.delete(row)
        await session.flush()
        return None
    if row.request_hash != request_hash:
        raise AppError(
            "IDEMPOTENCY_MISMATCH",
            details={"scope": scope},
        )
    return dict(row.response_snapshot or {})


async def store_idempotency(
    session: AsyncSession,
    *,
    scope: str,
    key: str,
    request_hash: str,
    response: dict,
    job_id: str | None = None,
    ttl_minutes: int = 10,
) -> None:
    # SAVEPOINT 而不是 `session.rollback()`：调用方在同一个请求事务里刚刚写过
    # repo / commit / course_version / job，整库回滚会把它们一起抹掉，接口随后
    # 返回一个**并不存在**的 job_id。嵌套事务只回滚这一条 INSERT。
    try:
        async with session.begin_nested():
            session.add(
                IdempotencyKey(
                    id=new_id("event"),
                    scope=scope,
                    key=key,
                    request_hash=request_hash,
                    response_snapshot=response,
                    job_id=job_id,
                    created_at=utcnow(),
                    expires_at=utcnow() + timedelta(minutes=ttl_minutes),
                )
            )
    except IntegrityError:
        # 并发同键：另一个请求先写进去了。读回语义由调用方决定，这里只保证
        # 本次请求的其余写入仍然有效。
        log.info("idempotency_conflict", scope=scope)


# --------------------------------------------------------------------------- #
# 生成锁                                                                       #
# --------------------------------------------------------------------------- #


async def acquire_lock(session: AsyncSession, cache_key: str, job_id: str, ttl_minutes: int = 30) -> bool:
    """抢占生成锁。返回 False 表示"同一份内容已有别的 Job 在跑"。

    **必须用 SAVEPOINT**：调用方（`create_course`）在同一个请求事务里刚建好
    repo / commit / course_version / job，这里的 `IntegrityError` 只是"锁被别人
    抢先"这一个事实，不该把那些写入一起回滚掉——否则接口会返回 202 和一个
    根本没提交的 job_id（用户在进度页看到 404，这是最难归因的一类假象）。
    """
    try:
        async with session.begin_nested():
            session.add(
                GenerationLock(
                    cache_key=cache_key,
                    job_id=job_id,
                    acquired_at=utcnow(),
                    expires_at=utcnow() + timedelta(minutes=ttl_minutes),
                )
            )
        return True
    except IntegrityError:
        log.info("lock_conflict", cache_key=cache_key, job_id=job_id)
        return False


async def lock_holder(session: AsyncSession, cache_key: str) -> str | None:
    row = (
        await session.execute(select(GenerationLock).where(GenerationLock.cache_key == cache_key))
    ).scalar_one_or_none()
    if row is None:
        return None
    if row.expires_at < utcnow():
        await session.delete(row)
        await session.flush()
        return None
    return row.job_id


async def active_lock_job(session: AsyncSession, cache_key: str) -> str | None:
    """返回"正在为这份内容干活"的 job_id；僵尸锁会被就地清掉。

    光看锁表是不够的：锁的 TTL 是 30 分钟，而 Job 可能在 3 分钟前就已经
    失败并释放过（进程被杀时不会执行释放逻辑）。把"锁还在、Job 已终结"当成
    冲突，会让这个仓库在 TTL 内彻底无法重新生成——于是这里以 Job 状态为准。
    """
    holder = await lock_holder(session, cache_key)
    if holder is None:
        return None
    status = (await session.execute(select(Job.status).where(Job.id == holder))).scalar_one_or_none()
    if status is None or status in TERMINAL_STATUSES:
        await release_lock(session, cache_key)
        return None
    return holder


async def release_lock(session: AsyncSession, cache_key: str) -> None:
    row = (
        await session.execute(select(GenerationLock).where(GenerationLock.cache_key == cache_key))
    ).scalar_one_or_none()
    if row is not None:
        await session.delete(row)
        await session.flush()


async def release_locks_for(session: AsyncSession, job_id: str) -> int:
    rows = (await session.execute(select(GenerationLock).where(GenerationLock.job_id == job_id))).scalars().all()
    for row in rows:
        await session.delete(row)
    if rows:
        await session.flush()
    return len(rows)

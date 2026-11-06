"""Job 事件落库与补发（spec §5.5）。

`job_events` 是 SSE 的**补发源**：客户端带 `Last-Event-ID` 重连时，服务端从这张表
读 `seq > last` 的事件补发；超出保留窗口（500 条）时不补发，改发一帧
`job.snapshot`（规则 2）——因为"从中间态硬拼"比"重建"更容易出现不一致。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from repolearn.core.clock import utcnow
from repolearn.core.ids import new_id
from repolearn.core.logging import get_logger
from repolearn.models import JobEvent
from repolearn.schemas.job import EventEnvelope
from repolearn.services.event_bus import bus

log = get_logger("job_events")

KEEP_EVENTS = 500


@dataclass
class PersistResult:
    env: EventEnvelope
    persisted: bool


async def emit(
    session: AsyncSession,
    job_id: str,
    event_type: str,
    data: dict[str, Any] | None = None,
    run_id: str | None = None,
    *,
    persist: bool = True,
) -> EventEnvelope:
    """发一条事件：先分配 seq，再落库，再广播。

    顺序不能反：先广播后落库时，客户端可能立刻用这个 seq 重连，而那时库里还没有
    这条记录，于是它会被"补发"逻辑再发一次——表现为事件重复。
    """
    env = bus.build(job_id, event_type, data, run_id)
    if persist:
        session.add(
            JobEvent(
                id=new_id("event"),
                job_id=job_id,
                seq=env.seq,
                type=event_type,
                data=data or {},
                created_at=utcnow(),
            )
        )
        try:
            await session.flush()
        except Exception as exc:  # noqa: BLE001 - 落库失败不能阻断事件流
            log.warning("job_event_persist_failed", job_id=job_id, error=str(exc))
    await bus.publish(env)
    return env


async def max_seq(session: AsyncSession, job_id: str) -> int:
    value = (await session.execute(select(func.max(JobEvent.seq)).where(JobEvent.job_id == job_id))).scalar()
    return int(value or 0)


async def min_seq(session: AsyncSession, job_id: str) -> int:
    value = (await session.execute(select(func.min(JobEvent.seq)).where(JobEvent.job_id == job_id))).scalar()
    return int(value or 0)


async def replay(session: AsyncSession, job_id: str, last_event_id: int) -> tuple[list[EventEnvelope], bool]:
    """返回 (补发事件, 是否需要 snapshot)。

    第二项为 True 表示 `Last-Event-ID` 落在保留窗口之前——此时不能补发，
    必须让前端用 `GET /v1/jobs/{id}` 的快照重建 UI（§5.5 规则 2）。
    """
    lowest = await min_seq(session, job_id)
    if last_event_id > 0 and lowest > 0 and last_event_id + 1 < lowest:
        return [], True
    rows = (
        await session.execute(
            select(JobEvent)
            .where(JobEvent.job_id == job_id, JobEvent.seq > last_event_id)
            .order_by(JobEvent.seq.asc())
            .limit(KEEP_EVENTS)
        )
    ).scalars().all()
    out: list[EventEnvelope] = []
    for row in rows:
        out.append(
            EventEnvelope(
                schemaVersion=1,
                type=row.type,
                seq=row.seq,
                ts=int(row.created_at.timestamp() * 1000) if row.created_at else 0,
                jobId=row.job_id,
                runId=None,
                data=dict(row.data or {}),
            )
        )
    return out, False


async def trim(session: AsyncSession, job_id: str, keep: int = KEEP_EVENTS) -> int:
    """只保留最近 `keep` 条。超出时删最旧的，保证 seq 单调但不无限增长。"""
    total = (
        await session.execute(select(func.count(JobEvent.id)).where(JobEvent.job_id == job_id))
    ).scalar() or 0
    if total <= keep:
        return 0
    cutoff = (
        await session.execute(
            select(JobEvent.seq).where(JobEvent.job_id == job_id).order_by(JobEvent.seq.desc()).offset(keep - 1).limit(1)
        )
    ).scalar()
    if cutoff is None:
        return 0
    result = await session.execute(delete(JobEvent).where(JobEvent.job_id == job_id, JobEvent.seq < int(cutoff)))
    return int(result.rowcount or 0)


async def seed_bus_seq(session: AsyncSession, job_id: str) -> None:
    """进程重启后把 bus 的 seq 对齐到库里的最大值——否则新事件会与旧 seq 冲突。"""
    value = await max_seq(session, job_id)
    if value:
        bus.seed_seq(job_id, value)

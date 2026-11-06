"""Job 事件总线（spec §5.5 / §7.5）。

职责只有一个：把"某个 Job 产生了一条事件"变成"所有正在看这个 Job 的订阅者立刻
收到它"，并且**落库**以便断线续传。

为什么用进程内发布订阅而不是轮询数据库：
轮询要么慢（1 秒一次，首帧延迟就爆了），要么费（100ms 一次，SQLite 单写者被打满）。
进程内 bus 是零延迟的，数据库只作为**补发源**（`Last-Event-ID` 落后时读 `job_events`）。
单进程部署下这是正确的取舍；将来上多 worker 时替换本模块即可，调用方不用改。
"""

from __future__ import annotations

import asyncio
from collections import defaultdict
from dataclasses import dataclass
from typing import Any

from repolearn.core.clock import utcnow
from repolearn.core.logging import get_logger
from repolearn.schemas.job import EventEnvelope

log = get_logger("event_bus")

SCHEMA_VERSION = 1
MAX_BUFFER = 500


@dataclass
class _Hub:
    queue: asyncio.Queue[EventEnvelope]
    ready: bool = True


class EventBus:
    def __init__(self) -> None:
        self._hubs: dict[str, set[asyncio.Queue[EventEnvelope]]] = defaultdict(set)
        self._seq: dict[str, int] = {}
        self._lock = asyncio.Lock()

    # -- 序号 ---------------------------------------------------------------
    def next_seq(self, job_id: str) -> int:
        """`seq` 必须**每一条事件单调递增且从 1 开始**（§5.5 规则 1）。

        不用时间戳近似：同毫秒的多条事件会丢帧，而丢帧的表现是"进度条卡在 60%"。
        """
        current = self._seq.get(job_id, 0) + 1
        self._seq[job_id] = current
        return current

    def seed_seq(self, job_id: str, seq: int) -> None:
        """进程重启后从数据库恢复最大 seq，避免续传时序号回退。"""
        if seq > self._seq.get(job_id, 0):
            self._seq[job_id] = seq

    def last_seq(self, job_id: str) -> int:
        return self._seq.get(job_id, 0)

    # -- 发布/订阅 ----------------------------------------------------------
    async def subscribe(self, job_id: str) -> asyncio.Queue[EventEnvelope]:
        queue: asyncio.Queue[EventEnvelope] = asyncio.Queue(maxsize=MAX_BUFFER)
        async with self._lock:
            self._hubs[job_id].add(queue)
        return queue

    async def unsubscribe(self, job_id: str, queue: asyncio.Queue[EventEnvelope]) -> None:
        async with self._lock:
            self._hubs[job_id].discard(queue)
            if not self._hubs[job_id]:
                self._hubs.pop(job_id, None)

    async def publish(self, env: EventEnvelope) -> None:
        job_id = env.jobId or ""
        if not job_id:
            return
        async with self._lock:
            targets = list(self._hubs.get(job_id, ()))
        for queue in targets:
            try:
                queue.put_nowait(env)
            except asyncio.QueueFull:
                # 慢消费者不能拖垮发布者：丢掉最旧的一条，保证新事件永远可见。
                try:
                    queue.get_nowait()
                    queue.put_nowait(env)
                except (asyncio.QueueEmpty, asyncio.QueueFull):
                    log.warning("event_bus_drop", job_id=job_id, seq=env.seq)

    def subscriber_count(self, job_id: str) -> int:
        return len(self._hubs.get(job_id, ()))

    # -- 构造信封 ------------------------------------------------------------
    def build(
        self,
        job_id: str,
        event_type: str,
        data: dict[str, Any] | None = None,
        run_id: str | None = None,
    ) -> EventEnvelope:
        import time

        return EventEnvelope(
            schemaVersion=SCHEMA_VERSION,
            type=event_type,
            seq=self.next_seq(job_id),
            ts=int(time.time() * 1000),
            jobId=job_id,
            runId=run_id,
            data=data or {},
        )

    async def emit(
        self,
        job_id: str,
        event_type: str,
        data: dict[str, Any] | None = None,
        run_id: str | None = None,
    ) -> EventEnvelope:
        env = self.build(job_id, event_type, data, run_id)
        await self.publish(env)
        return env


def sse_frame(env: EventEnvelope) -> str:
    """SSE 帧：`id:` 必须是 seq，客户端用 `Last-Event-ID` 续传。"""
    import json

    payload = json.dumps(env.model_dump(), ensure_ascii=False)
    return f"id: {env.seq}\nevent: {env.type}\ndata: {payload}\n\n"


KEEPALIVE_FRAME = ": keepalive\n\n"


bus = EventBus()


def now_ms() -> int:
    import time

    return int(time.time() * 1000)


__all__ = [
    "KEEPALIVE_FRAME",
    "MAX_BUFFER",
    "SCHEMA_VERSION",
    "EventBus",
    "bus",
    "now_ms",
    "sse_frame",
    "utcnow",
]

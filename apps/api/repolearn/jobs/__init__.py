"""任务层（spec §3.11）。

`runner` 是唯一的常驻循环；`queue` 管状态机与幂等；`events` 管 SSE 补发；
`handlers`/`book_jobs` 是具体业务。四者之间只通过数据库与 `event_bus` 通信。
"""

from __future__ import annotations

from repolearn.jobs import events, queue
from repolearn.jobs.runner import (
    JobRunner,
    get_runner,
    reap_orphaned_generations,
    requeue_stale_jobs,
    start_runner,
    stop_runner,
)

__all__ = [
    "JobRunner",
    "events",
    "get_runner",
    "queue",
    "reap_orphaned_generations",
    "requeue_stale_jobs",
    "start_runner",
    "stop_runner",
]

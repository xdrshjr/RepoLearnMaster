"""`jobs` 表（spec §6.2 / §3.11）。

状态机：`queued → claimed → running → (ready|partial|failed|failed_budget|cancelled)`。

**幂等键不在本表**（v2 修正，P1-12）：`POST /v1/courses` 与 `POST /v1/books` 都会带
`Idempotency-Key`，客户端复用同一个 UUID 时会把两个不同资源的创建互相踩成 409，
且报错还指向"任务冲突"。幂等的作用域永远是"同一路径模板"，所以键移到了
`idempotency_keys(scope, key)`。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from repolearn.core.db import Base
from repolearn.models._types import ID, JsonCol, OptTs, Ts


class Job(Base):
    __tablename__ = "jobs"
    __table_args__ = (
        Index("ix_jobs_status_priority_created", "status", "priority", "created_at"),
        Index("ix_jobs_cache_key", "cache_key"),
    )

    id: Mapped[ID]
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="queued", nullable=False)
    priority: Mapped[int] = mapped_column(Integer, default=100, nullable=False)
    payload: Mapped[JsonCol] = mapped_column(default=dict)
    course_version_id: Mapped[str | None] = mapped_column(
        String(40), ForeignKey("course_versions.id", ondelete="CASCADE"), nullable=True
    )
    book_version_id: Mapped[str | None] = mapped_column(
        String(40), ForeignKey("book_versions.id", ondelete="CASCADE"), nullable=True
    )
    cache_key: Mapped[str | None] = mapped_column(String(80), nullable=True)
    worker_id: Mapped[str | None] = mapped_column(String(60), nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    progress: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    node: Mapped[str | None] = mapped_column(String(40), nullable=True)
    message: Mapped[str | None] = mapped_column(String(500), nullable=True)
    error: Mapped[JsonCol] = mapped_column(default=dict)
    heartbeat_at: Mapped[OptTs]
    run_after: Mapped[OptTs]
    started_at: Mapped[OptTs]
    finished_at: Mapped[OptTs]
    created_at: Mapped[Ts]

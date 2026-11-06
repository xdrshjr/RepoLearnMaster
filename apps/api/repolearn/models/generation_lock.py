"""`generation_locks` 表（spec §3.10）。

`cache_key` 是主键：同一个 cache_key 同时只允许一个 Job 在生成。reaper（P1-13）
必须**先删锁再改状态**——反序会留下"状态已失败的锁"，同样卡住重建。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from repolearn.core.db import Base
from repolearn.models._types import Ref, Ts, UtcDateTime


class GenerationLock(Base):
    __tablename__ = "generation_locks"

    cache_key: Mapped[str] = mapped_column(String(80), primary_key=True)
    job_id: Mapped[Ref] = mapped_column(String(40), nullable=False)
    acquired_at: Mapped[Ts]
    expires_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)

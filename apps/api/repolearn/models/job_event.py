"""`job_events` 表（spec §6.2 / §5.5）。`UNIQUE(job_id, seq)` 是 SSE 精确续传的基础。"""

from __future__ import annotations

from sqlalchemy import ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from repolearn.core.db import Base
from repolearn.models._types import ID, JsonCol, Ref, Ts


class JobEvent(Base):
    __tablename__ = "job_events"
    __table_args__ = (UniqueConstraint("job_id", "seq", name="ux_job_events_job_seq"),)

    id: Mapped[ID]
    job_id: Mapped[Ref] = mapped_column(
        String(40), ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    type: Mapped[str] = mapped_column(String(40), nullable=False)
    data: Mapped[JsonCol] = mapped_column(default=dict)
    created_at: Mapped[Ts]

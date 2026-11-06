"""`simulated_traces` 表（spec §6.2 / §6.4）。

`certainty_summary` 是诚信约束的落地：`source_fact` 占比 < 40% 时
`quality_report.trace_quality="weak"`，前端要提示"本课时以推演为主"。
"""

from __future__ import annotations

from sqlalchemy import ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from repolearn.core.db import Base
from repolearn.models._types import ID, JsonCol, Ref, Ts


class SimulatedTrace(Base):
    __tablename__ = "simulated_traces"
    __table_args__ = (Index("ix_traces_course_key", "course_version_id", "key"),)

    id: Mapped[ID]
    course_version_id: Mapped[Ref] = mapped_column(
        String(40), ForeignKey("course_versions.id", ondelete="CASCADE"), nullable=False
    )
    lesson_id: Mapped[str | None] = mapped_column(
        String(40), ForeignKey("lessons.id", ondelete="CASCADE"), nullable=True
    )
    key: Mapped[str] = mapped_column(String(40), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    entry_anchor_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    steps: Mapped[JsonCol] = mapped_column(default=list)
    certainty_summary: Mapped[JsonCol] = mapped_column(default=dict)
    created_at: Mapped[Ts]

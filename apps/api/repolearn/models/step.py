"""`steps` 表（spec §6.2 / P1-3）——步骤数据的唯一真源。"""

from __future__ import annotations

from sqlalchemy import ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from repolearn.core.db import Base
from repolearn.models._types import ID, JsonCol, Ref, Ts


class Step(Base):
    __tablename__ = "steps"
    __table_args__ = (
        UniqueConstraint("lesson_id", "order_index", name="ux_steps_lesson_order"),
        Index("ix_steps_lesson_order", "lesson_id", "order_index"),
    )

    id: Mapped[ID]
    lesson_id: Mapped[Ref] = mapped_column(
        String(40), ForeignKey("lessons.id", ondelete="CASCADE"), nullable=False
    )
    order_index: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    timing_source: Mapped[str] = mapped_column(String(12), default="estimated", nullable=False)
    audio_asset_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    focus_file: Mapped[str | None] = mapped_column(String(400), nullable=True)
    focus_line_start: Mapped[int | None] = mapped_column(Integer, nullable=True)
    focus_line_end: Mapped[int | None] = mapped_column(Integer, nullable=True)
    segments: Mapped[JsonCol] = mapped_column(default=list)
    board: Mapped[JsonCol] = mapped_column(default=dict)
    code_notes: Mapped[JsonCol] = mapped_column(default=list)
    certainty: Mapped[JsonCol] = mapped_column(default=dict)
    created_at: Mapped[Ts]

"""`questions` 表（spec §6.2）。`runtime` 记录这次回答由哪条通道产出（kernel/exec/template）。"""

from __future__ import annotations

from sqlalchemy import ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from repolearn.core.db import Base
from repolearn.models._types import ID, JsonCol, OptTs, Ref, Ts


class Question(Base):
    __tablename__ = "questions"
    __table_args__ = (Index("ix_questions_course_lesson", "course_version_id", "lesson_id"),)

    id: Mapped[ID]
    user_id: Mapped[Ref] = mapped_column(
        String(40), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    course_version_id: Mapped[Ref] = mapped_column(
        String(40), ForeignKey("course_versions.id", ondelete="CASCADE"), nullable=False
    )
    lesson_id: Mapped[str | None] = mapped_column(
        String(40), ForeignKey("lessons.id", ondelete="CASCADE"), nullable=True
    )
    file: Mapped[str] = mapped_column(String(400), default="", nullable=False)
    line_start: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    line_end: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    layer: Mapped[str] = mapped_column(String(20), default="deep_dive", nullable=False)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    answer_md: Mapped[str] = mapped_column(Text, default="", nullable=False)
    evidence: Mapped[JsonCol] = mapped_column(default=list)
    runtime: Mapped[str] = mapped_column(String(12), default="template", nullable=False)
    tokens_in: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    tokens_out: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[Ts]
    deleted_at: Mapped[OptTs]

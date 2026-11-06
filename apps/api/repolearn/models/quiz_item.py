"""`quiz_items` 表（spec §6.2）。每题恰好一个 `answer_id`，`evidence` 非空由发布校验保证。"""

from __future__ import annotations

from sqlalchemy import ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from repolearn.core.db import Base
from repolearn.models._types import ID, JsonCol, Ref, Ts


class QuizItem(Base):
    __tablename__ = "quiz_items"
    __table_args__ = (Index("ix_quiz_course_lesson", "course_version_id", "lesson_id"),)

    id: Mapped[ID]
    course_version_id: Mapped[Ref] = mapped_column(
        String(40), ForeignKey("course_versions.id", ondelete="CASCADE"), nullable=False
    )
    lesson_id: Mapped[str | None] = mapped_column(
        String(40), ForeignKey("lessons.id", ondelete="CASCADE"), nullable=True
    )
    stem: Mapped[str] = mapped_column(Text, nullable=False)
    choices: Mapped[JsonCol] = mapped_column(default=list)
    answer_id: Mapped[str] = mapped_column(String(20), nullable=False)
    explanation_md: Mapped[str] = mapped_column(Text, default="", nullable=False)
    evidence: Mapped[JsonCol] = mapped_column(default=list)
    difficulty: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    kind: Mapped[str] = mapped_column(String(16), default="recall", nullable=False)
    created_at: Mapped[Ts]

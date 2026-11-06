"""`user_progress` 表（spec §6.2）。对 `course_versions` 用 RESTRICT，防止误删在用版本。"""

from __future__ import annotations

from sqlalchemy import ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from repolearn.core.db import Base
from repolearn.models._types import ID, OptTs, Ref, Ts


class UserProgress(Base):
    __tablename__ = "user_progress"
    __table_args__ = (
        UniqueConstraint("user_id", "course_version_id", name="ux_progress_user_course"),
        Index("ix_progress_user_updated", "user_id", "updated_at"),
    )

    id: Mapped[ID]
    user_id: Mapped[Ref] = mapped_column(
        String(40), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    course_version_id: Mapped[Ref] = mapped_column(
        String(40), ForeignKey("course_versions.id", ondelete="RESTRICT"), nullable=False
    )
    current_lesson_key: Mapped[str | None] = mapped_column(String(40), nullable=True)
    current_step_index: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    position_ms: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    percent: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    completed_at: Mapped[OptTs]
    created_at: Mapped[Ts]
    updated_at: Mapped[OptTs]

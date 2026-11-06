"""`notes` 表（spec §6.2）。软删列在读取路径上必须被过滤（由 services 的统一助手保证）。"""

from __future__ import annotations

from sqlalchemy import ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from repolearn.core.db import Base
from repolearn.models._types import ID, JsonCol, OptTs, Ref, Ts


class Note(Base):
    __tablename__ = "notes"
    __table_args__ = (Index("ix_notes_user_course", "user_id", "course_version_id"),)

    id: Mapped[ID]
    user_id: Mapped[Ref] = mapped_column(
        String(40), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    course_version_id: Mapped[str | None] = mapped_column(
        String(40), ForeignKey("course_versions.id", ondelete="CASCADE"), nullable=True
    )
    lesson_id: Mapped[str | None] = mapped_column(
        String(40), ForeignKey("lessons.id", ondelete="CASCADE"), nullable=True
    )
    anchor_id: Mapped[str | None] = mapped_column(
        String(40), ForeignKey("source_anchors.id", ondelete="SET NULL"), nullable=True
    )
    body_md: Mapped[str] = mapped_column(String(8000), default="", nullable=False)
    tags: Mapped[JsonCol] = mapped_column(default=list)
    created_at: Mapped[Ts]
    updated_at: Mapped[OptTs]
    deleted_at: Mapped[OptTs]

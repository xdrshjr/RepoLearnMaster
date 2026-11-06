"""`source_anchors` 表（spec §6.2）。

锚点是**可追溯性的唯一凭据**：任何讲解引用了一个不存在的锚点，发布前校验即失败
（N9）。`snippet_hash` 让"源码变了但锚点没变"这件事可被检测（重建时用于增量判断）。
"""

from __future__ import annotations

from sqlalchemy import ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from repolearn.core.db import Base
from repolearn.models._types import ID, Ref, Ts


class SourceAnchor(Base):
    __tablename__ = "source_anchors"
    __table_args__ = (
        Index("ix_anchors_course_file", "course_version_id", "file"),
        Index("ix_anchors_lesson", "lesson_id"),
    )

    id: Mapped[ID]
    course_version_id: Mapped[Ref] = mapped_column(
        String(40), ForeignKey("course_versions.id", ondelete="CASCADE"), nullable=False
    )
    lesson_id: Mapped[str | None] = mapped_column(
        String(40), ForeignKey("lessons.id", ondelete="CASCADE"), nullable=True
    )
    file: Mapped[str] = mapped_column(String(400), nullable=False)
    symbol: Mapped[str | None] = mapped_column(String(200), nullable=True)
    line_start: Mapped[int] = mapped_column(Integer, nullable=False)
    line_end: Mapped[int] = mapped_column(Integer, nullable=False)
    commit_sha: Mapped[str] = mapped_column(String(64), nullable=False)
    kind: Mapped[str] = mapped_column(String(20), default="definition", nullable=False)
    snippet_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[Ts]

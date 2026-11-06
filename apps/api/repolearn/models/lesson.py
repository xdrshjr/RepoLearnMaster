"""`lessons` 表（spec §6.2）。

**单一真源约束**：步骤数据只存在于 `steps` 表；本表的 `playback_meta` 只保留
非步骤字段（files / trace_key / certainty_legend / board_theme）。`PlaybackBundle`
由二者只读拼装，永不回写——这条约束解决的是"播放到第 3 步又跳回第 1 步"这类
极难定位的分叉 bug。
"""

from __future__ import annotations

from sqlalchemy import ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from repolearn.core.db import Base
from repolearn.models._types import ID, JsonCol, Ref, Ts


class Lesson(Base):
    __tablename__ = "lessons"
    __table_args__ = (
        UniqueConstraint("course_version_id", "key", name="ux_lessons_course_key"),
        Index("ix_lessons_course_order", "course_version_id", "order_index"),
    )

    id: Mapped[ID]
    course_version_id: Mapped[Ref] = mapped_column(
        String(40), ForeignKey("course_versions.id", ondelete="CASCADE"), nullable=False
    )
    section_key: Mapped[str] = mapped_column(String(20), nullable=False)
    key: Mapped[str] = mapped_column(String(40), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    goal: Mapped[str | None] = mapped_column(Text, nullable=True)
    minutes: Mapped[int] = mapped_column(Integer, default=6, nullable=False)
    order_index: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    status: Mapped[str] = mapped_column(String(12), default="ready", nullable=False)
    playback_meta: Mapped[JsonCol] = mapped_column(default=dict)
    created_at: Mapped[Ts]

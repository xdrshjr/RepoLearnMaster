"""`book_versions` 表（spec §6.2）。幂等键 = `cache_key`（课程版本 + preset + 模板版本）。"""

from __future__ import annotations

from sqlalchemy import ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from repolearn.core.db import Base
from repolearn.models._types import ID, JsonCol, Ref, Ts


class BookVersion(Base):
    __tablename__ = "book_versions"

    id: Mapped[ID]
    course_version_id: Mapped[Ref] = mapped_column(
        String(40), ForeignKey("course_versions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    cache_key: Mapped[str] = mapped_column(String(80), unique=True, nullable=False)
    preset: Mapped[str] = mapped_column(String(16), default="standard", nullable=False)
    template_version: Mapped[str] = mapped_column(String(20), default="1", nullable=False)
    title: Mapped[str] = mapped_column(String(200), default="", nullable=False)
    subtitle: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="generating", nullable=False)
    word_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    chapter_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    quality: Mapped[JsonCol] = mapped_column(default=dict)
    created_at: Mapped[Ts]

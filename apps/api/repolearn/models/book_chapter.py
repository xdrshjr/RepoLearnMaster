"""`book_chapters` 表（spec §6.2）。`source_refs` 非空且可解析是 T-BOOK-2 的断言。"""

from __future__ import annotations

from sqlalchemy import ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from repolearn.core.db import Base
from repolearn.models._types import ID, JsonCol, Ref, Ts


class BookChapter(Base):
    __tablename__ = "book_chapters"
    __table_args__ = (
        UniqueConstraint("book_version_id", "key", name="ux_book_chapter_key"),
        Index("ix_book_chapters_book_order", "book_version_id", "order_index"),
    )

    id: Mapped[ID]
    book_version_id: Mapped[Ref] = mapped_column(
        String(40), ForeignKey("book_versions.id", ondelete="CASCADE"), nullable=False
    )
    key: Mapped[str] = mapped_column(String(40), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    order_index: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    blocks: Mapped[JsonCol] = mapped_column(default=list)
    source_refs: Mapped[JsonCol] = mapped_column(default=list)
    word_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[Ts]

"""`pdf_exports` 表（spec §6.2，v2 补齐 P0-3）。

`engine` 只有两个合法值：`chromium`（MVP 唯一真引擎）与 `browser-print`
（Chromium 不可用时的降级：提供打印优化 HTML，而不是伪造一个 PDF 文件）。
"""

from __future__ import annotations

from sqlalchemy import ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from repolearn.core.db import Base
from repolearn.models._types import ID, JsonCol, OptTs, Ref, Ts


class PdfExport(Base):
    __tablename__ = "pdf_exports"

    id: Mapped[ID]
    book_version_id: Mapped[Ref] = mapped_column(
        String(40), ForeignKey("book_versions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    cache_key: Mapped[str] = mapped_column(String(80), unique=True, nullable=False)
    engine: Mapped[str] = mapped_column(String(20), default="chromium", nullable=False)
    object_key: Mapped[str | None] = mapped_column(String(300), nullable=True)
    pages: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    bytes: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="queued", nullable=False)
    error: Mapped[JsonCol] = mapped_column(default=dict)
    created_at: Mapped[Ts]
    finished_at: Mapped[OptTs]

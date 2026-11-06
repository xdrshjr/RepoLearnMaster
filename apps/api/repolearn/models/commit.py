"""`commits` 表（spec §6.2）。同一仓库的同一 sha 唯一——这是"复用"的最小单位。"""

from __future__ import annotations

from sqlalchemy import ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from repolearn.core.db import Base
from repolearn.models._types import ID, OptTs, Ref, Ts


class Commit(Base):
    __tablename__ = "commits"
    __table_args__ = (UniqueConstraint("repository_id", "sha", name="ux_commits_repo_sha"),)

    id: Mapped[ID]
    repository_id: Mapped[Ref] = mapped_column(
        String(40), ForeignKey("repositories.id", ondelete="CASCADE"), nullable=False, index=True
    )
    sha: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    committed_at: Mapped[OptTs]
    file_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    tarball_bytes: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    license_note: Mapped[str | None] = mapped_column(String(400), nullable=True)
    created_at: Mapped[Ts]

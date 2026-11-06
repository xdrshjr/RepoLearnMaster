"""`course_versions` 表（spec §6.1 / §6.2）。

**课程聚合根就是这一行**：`API 的 course_id 恒等于 course_versions.id`。没有独立的
`courses` 表——因为 PRD 里"同一仓库的第 2 个版本"是另一门课程内容，不是同一门课的
第 2 版；分成两级会让 URL/权限/进度/书籍/笔记全部需要重映射。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from repolearn.core.db import Base
from repolearn.models._types import ID, JsonCol, OptTs, Ref, Ts


class CourseVersion(Base):
    __tablename__ = "course_versions"
    __table_args__ = (
        Index("ix_course_versions_status_created", "status", "created_at"),
        Index("ix_course_versions_repo_created", "repository_id", "created_at"),
    )

    id: Mapped[ID]
    repository_id: Mapped[Ref] = mapped_column(
        String(40), ForeignKey("repositories.id", ondelete="CASCADE"), nullable=False
    )
    commit_sha: Mapped[str] = mapped_column(String(64), nullable=False)
    # 内容级缓存键：sha256(repo_full_name, commit_sha, policy_version, language)
    cache_key: Mapped[str] = mapped_column(String(80), unique=True, nullable=False, index=True)
    policy_version: Mapped[str] = mapped_column(String(40), default="1", nullable=False)
    language: Mapped[str] = mapped_column(String(10), default="zh", nullable=False)
    title: Mapped[str] = mapped_column(String(200), default="", nullable=False)
    subtitle: Mapped[str | None] = mapped_column(String(400), nullable=True)
    summary_md: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="generating", nullable=False)
    sections: Mapped[JsonCol] = mapped_column(default=list)
    quality_report: Mapped[JsonCol] = mapped_column(default=dict)
    warnings: Mapped[JsonCol] = mapped_column(default=list)
    blueprint: Mapped[JsonCol] = mapped_column(default=dict)
    cover_palette: Mapped[str] = mapped_column(String(20), default="mint", nullable=False)
    lesson_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_minutes: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    owner_user_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    visibility: Mapped[str] = mapped_column(String(12), default="public", nullable=False)
    created_at: Mapped[Ts]
    updated_at: Mapped[OptTs]
    published_at: Mapped[OptTs]
    deleted_at: Mapped[OptTs]

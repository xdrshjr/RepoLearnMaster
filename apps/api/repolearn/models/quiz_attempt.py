"""`quiz_attempts` 表（spec §6.2，v2 新增 P0-3）。

`UNIQUE(user_id, quiz_item_id)` **就是** T-QUIZ-1「重复提交幂等」的实现：
`INSERT ... ON CONFLICT DO NOTHING` 之后读回首次结果并返回 `replayed:true`。

为什么必须落表而不能靠前端去重：recap 的答题统计、`/v1/metrics` 的正确率、
能力雷达三项都从这张表聚合——前端去重会让统计随刷新漂移。
"""

from __future__ import annotations

from sqlalchemy import Boolean, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from repolearn.core.db import Base
from repolearn.models._types import ID, OptTs, Ref


class QuizAttempt(Base):
    __tablename__ = "quiz_attempts"
    __table_args__ = (
        UniqueConstraint("user_id", "quiz_item_id", name="ux_quiz_attempt_user_item"),
        Index("ix_quiz_attempt_course", "course_version_id", "submitted_at"),
    )

    id: Mapped[ID]
    user_id: Mapped[Ref] = mapped_column(
        String(40), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    quiz_item_id: Mapped[Ref] = mapped_column(
        String(40), ForeignKey("quiz_items.id", ondelete="CASCADE"), nullable=False
    )
    course_version_id: Mapped[Ref] = mapped_column(
        String(40), ForeignKey("course_versions.id", ondelete="CASCADE"), nullable=False
    )
    choice_id: Mapped[str] = mapped_column(String(20), nullable=False)
    correct: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    submitted_at: Mapped[OptTs]

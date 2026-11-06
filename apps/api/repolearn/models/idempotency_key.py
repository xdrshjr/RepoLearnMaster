"""`idempotency_keys` 表（spec §6.2，v2 新增 P1-12）。

三个字段各自解决一个真实事故：
* `scope` 取**路径模板**（`courses.create` / `books.create` / `pdf.create`），不是完整
  URL——路径里的 id 会把同一逻辑操作算成不同 scope，于是幂等失效；
* `request_hash` = 请求体规范化后的 sha256：同键不同体直接 422 `IDEMPOTENCY_MISMATCH`。
  静默返回首次结果会掩盖调用方的 bug（这是幂等键的经典陷阱）；
* `response_snapshot` 存首次响应体，保证"重放"返回**逐字节相同**的结果，而不是
  重新查一遍库（那时状态可能已经变了）。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Index, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from repolearn.core.db import Base
from repolearn.models._types import ID, JsonCol, OptTs, Ts


class IdempotencyKey(Base):
    __tablename__ = "idempotency_keys"
    __table_args__ = (
        UniqueConstraint("scope", "key", name="ux_idempotency_scope_key"),
        Index("ix_idempotency_expires", "expires_at"),
    )

    id: Mapped[ID]
    scope: Mapped[str] = mapped_column(String(40), nullable=False)
    key: Mapped[str] = mapped_column(String(120), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    response_snapshot: Mapped[JsonCol] = mapped_column(default=dict)
    job_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    created_at: Mapped[Ts]
    expires_at: Mapped[OptTs]

"""`cost_ledger` 表（spec §3.13 / §6.2）。成本门禁（job 级 ≤ 0.35 USD）的计量基础。"""

from __future__ import annotations

from sqlalchemy import Float, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from repolearn.core.db import Base
from repolearn.models._types import ID, Ts


class CostLedger(Base):
    __tablename__ = "cost_ledger"
    __table_args__ = (Index("ix_cost_ledger_created", "created_at"),)

    id: Mapped[ID]
    job_id: Mapped[str | None] = mapped_column(
        String(40), nullable=True, index=True
    )
    role: Mapped[str] = mapped_column(String(20), default="writer", nullable=False)
    provider: Mapped[str] = mapped_column(String(40), default="", nullable=False)
    model_id: Mapped[str] = mapped_column(String(160), default="", nullable=False)
    tokens_in: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    tokens_out: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    usd: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    created_at: Mapped[Ts]

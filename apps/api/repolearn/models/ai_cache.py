"""`ai_cache` 表（spec §3.10）。键 = sha256(prompt_version, model_id, inputs_digest)。"""

from __future__ import annotations

from sqlalchemy import Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from repolearn.core.db import Base
from repolearn.models._types import JsonCol, OptTs, Ts


class AiCache(Base):
    __tablename__ = "ai_cache"

    key: Mapped[str] = mapped_column(String(80), primary_key=True)
    response_json: Mapped[JsonCol] = mapped_column(default=dict)
    tokens_in: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    tokens_out: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    model_id: Mapped[str] = mapped_column(String(160), default="", nullable=False)
    created_at: Mapped[Ts]
    expires_at: Mapped[OptTs]

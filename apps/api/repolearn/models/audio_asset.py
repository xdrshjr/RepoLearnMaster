"""`audio_assets` 表（spec §3.8）。

缓存键 `UNIQUE(provider, voice, speed, text_hash)` 是成本控制的关键：
同一句话在 10 个课时里只合成一次。
"""

from __future__ import annotations

from sqlalchemy import Float, Index, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from repolearn.core.db import Base
from repolearn.models._types import ID, Ts


class AudioAsset(Base):
    __tablename__ = "audio_assets"
    __table_args__ = (
        UniqueConstraint("provider", "voice", "speed", "text_hash", name="ux_audio_cache_key"),
        Index("ix_audio_text_hash", "text_hash"),
    )

    id: Mapped[ID]
    provider: Mapped[str] = mapped_column(String(40), nullable=False)
    voice: Mapped[str] = mapped_column(String(120), nullable=False)
    speed: Mapped[float] = mapped_column(Float, default=1.0, nullable=False)
    text_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    object_key: Mapped[str] = mapped_column(String(300), nullable=False)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    duration_source: Mapped[str] = mapped_column(String(16), default="estimated", nullable=False)
    bytes: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[Ts]

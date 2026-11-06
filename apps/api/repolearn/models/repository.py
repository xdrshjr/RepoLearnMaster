"""`repositories` 表（spec §6.2）。`full_name` 是 `owner/name`，全局唯一。"""

from __future__ import annotations

from sqlalchemy import Boolean, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from repolearn.core.db import Base
from repolearn.models._types import ID, OptTs, Ts


class Repository(Base):
    __tablename__ = "repositories"

    id: Mapped[ID]
    full_name: Mapped[str] = mapped_column(String(200), unique=True, nullable=False)
    owner: Mapped[str] = mapped_column(String(120), nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    description: Mapped[str | None] = mapped_column(String(1200), nullable=True)
    stars: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    license_spdx: Mapped[str | None] = mapped_column(String(80), nullable=True)
    primary_language: Mapped[str | None] = mapped_column(String(60), nullable=True)
    default_branch: Mapped[str] = mapped_column(String(120), default="main", nullable=False)
    html_url: Mapped[str | None] = mapped_column(String(400), nullable=True)
    is_public: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[Ts]
    updated_at: Mapped[OptTs]

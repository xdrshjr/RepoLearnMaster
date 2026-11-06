"""`users` 表（spec §6.2）。MVP 自动创建 `usr_local`，但所有查询仍走 user_id 过滤。"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, String
from sqlalchemy.orm import Mapped, mapped_column

from repolearn.core.db import Base
from repolearn.models._types import ID, Name, Ts


class User(Base):
    __tablename__ = "users"

    id: Mapped[ID]
    handle: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    display_name: Mapped[Name] = mapped_column(String(200), nullable=False)
    is_local: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[Ts]

"""`setting_revisions` 表（spec §6.2）。

`payload` **不含任何密文**（P2-2）：只存 `{profile_id, provider, protocol, base_url,
model_id, roles{...}}` 这类引用与分配。否则"回滚到 rev 3"会把 rev 3 当时那把已被
轮换掉的密钥重新写回生效位——轮换密钥之后这是真实的安全回退。
"""

from __future__ import annotations

from sqlalchemy import Boolean, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from repolearn.core.db import Base
from repolearn.models._types import ID, JsonCol, Ts


class SettingRevision(Base):
    __tablename__ = "setting_revisions"

    id: Mapped[ID]
    rev: Mapped[int] = mapped_column(Integer, unique=True, nullable=False)
    summary: Mapped[str] = mapped_column(String(300), default="", nullable=False)
    changes: Mapped[JsonCol] = mapped_column(default=list)
    payload: Mapped[JsonCol] = mapped_column(default=dict)
    author: Mapped[str] = mapped_column(String(60), default="local", nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[Ts]

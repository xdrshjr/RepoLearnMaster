"""`llm_profiles` 表（spec §6.2 / §3.6.3）。

**`active` 必须由数据库保证唯一**（部分唯一索引）。激活 profile 有两条并发可达的
路径（`POST /v1/settings/profiles/{id}/activate` 与 `POST /v1/setup/commit`），没有
约束时两者交错会留下两个 `active=true` 的行，此时 `setup/state` 的判定、resolver
取哪个 profile、Doctor 显示哪个都会变成"看查询顺序"。

索引写在迁移里：`CREATE UNIQUE INDEX ux_llm_profiles_active ON llm_profiles(active) WHERE active = 1`
（SQLite 与 PG 同一句 SQL）。
"""

from __future__ import annotations

from sqlalchemy import Boolean, LargeBinary, String
from sqlalchemy.orm import Mapped, mapped_column

from repolearn.core.db import Base
from repolearn.models._types import ID, JsonCol, Name, OptTs, Ts


class LlmProfile(Base):
    __tablename__ = "llm_profiles"

    id: Mapped[ID]
    label: Mapped[Name] = mapped_column(String(200), nullable=False)
    provider: Mapped[str] = mapped_column(String(40), nullable=False)
    protocol: Mapped[str] = mapped_column(String(40), nullable=False)
    base_url: Mapped[str | None] = mapped_column(String(400), nullable=True)
    api_key_ciphertext: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    api_key_last4: Mapped[str] = mapped_column(String(8), default="", nullable=False)
    org: Mapped[str | None] = mapped_column(String(120), nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    last_probe: Mapped[JsonCol] = mapped_column(default=dict)
    roles: Mapped[JsonCol] = mapped_column(default=dict)
    created_at: Mapped[Ts]
    rotated_at: Mapped[OptTs]

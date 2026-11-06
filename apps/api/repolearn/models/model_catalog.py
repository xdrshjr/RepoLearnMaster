"""`model_catalog` 表（spec §3.7.1）。

探测结论缓存 7 天：没有它，每次启动都会把所有 provider 的 `/models` 重新打一遍。
`capabilities` 是"多模态能力"唯一的真源 —— 向导里 vision 角色能不能选，
以及 N4/N5 要不要走图片理解，都读这一列。
"""

from __future__ import annotations

from sqlalchemy import Float, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from repolearn.core.db import Base
from repolearn.models._types import ID, JsonCol, Name, OptTs, Ts


class ModelCatalog(Base):
    __tablename__ = "model_catalog"
    __table_args__ = (UniqueConstraint("provider", "model_id", name="ux_model_catalog_provider_model"),)

    id: Mapped[ID]
    provider: Mapped[str] = mapped_column(String(40), nullable=False)
    model_id: Mapped[str] = mapped_column(String(160), nullable=False)
    display_name: Mapped[Name] = mapped_column(String(200), nullable=False)
    capabilities: Mapped[JsonCol] = mapped_column(default=dict)
    context_window: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    price_in: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    price_out: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    probed_at: Mapped[OptTs]
    created_at: Mapped[Ts]

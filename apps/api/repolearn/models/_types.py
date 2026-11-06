"""模型层公共构件。

为什么单独一个文件：26 张表如果各自写一遍 `id = mapped_column(String, primary_key=True)`，
它们迟早会写得不一样（有的 32 长度、有的 64）。把"ID 是什么形状、JSON 列怎么存、
时间怎么写"收敛到一处，是让 §6.1 的约定**可执行**而不是"文档里说的"。

方言差异（spec §6.7）：
* JSON → SQLite 存 TEXT，PG 存 JSONB（`with_variant`）；
* 时间 → 应用层统一 `utcnow()` 写入，不用 DB 默认函数。
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated, Any

from sqlalchemy import JSON, DateTime, String, Text, TypeDecorator
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import mapped_column

from repolearn.core.clock import utcnow


class UtcDateTime(TypeDecorator):
    """始终以 UTC 往返的时间列。

    这不是洁癖，是一个真实崩溃点的修复：**SQLite 不存时区**。写进去的是
    `2026-11-06T10:00:00+00:00`，读出来是 naive 的 `2026-11-06 10:00:00`。
    于是任何 `row.expires_at < utcnow()` 都会抛
    `TypeError: can't compare offset-naive and offset-aware datetimes` ——
    而这段比较正好出现在幂等键过期、生成锁过期、心跳回收、僵尸版本回收这四处，
    也就是**所有可靠性逻辑**。

    修法只有两条：在每个比较点手写 `as_utc(...)`（漏一处就是线上 500），
    或在类型层一次性抹平（这里选的）。写入时去掉 tzinfo（内容仍是 UTC 时间，
    信息无损），读出时补回 UTC。
    """

    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect: Any) -> datetime | None:  # noqa: ANN401
        if value is None:
            return None
        if value.tzinfo is None:
            return value
        return value.astimezone(timezone.utc).replace(tzinfo=None)

    def process_result_value(self, value: datetime | None, dialect: Any) -> datetime | None:  # noqa: ANN401
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)


# 前缀 ID（ULID）长度为 4（prefix+_）+ 26 = 30；留到 40 以容纳未来格式。
ID = Annotated[str, mapped_column(String(40), primary_key=True)]
Ref = Annotated[str, mapped_column(String(40))]
Name = Annotated[str, mapped_column(String(200))]
TextCol = Annotated[str, mapped_column(Text)]
Ts = Annotated[datetime, mapped_column(UtcDateTime, default=utcnow, nullable=False)]

#: 仅用于不可查询的载荷（prompt / board / quality_report）。
JsonCol = Annotated[Any, mapped_column(JSON().with_variant(JSONB, "postgresql"))]

#: 可空时间戳（published_at / deleted_at / finished_at / heartbeat_at）。
OptTs = Annotated[datetime | None, mapped_column(UtcDateTime, default=None, nullable=True)]


def utcnow_default() -> datetime:
    return utcnow()

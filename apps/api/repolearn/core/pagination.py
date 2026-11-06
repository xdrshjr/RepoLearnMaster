"""HTTP 层的小工具：分页游标、JSON 列、时间序列化。

放在 core 而不是 services，是因为 router / services / CLI 都要用同一套语义：
一个 `limit` 上限、一种游标格式、一种时间格式。分散实现的话，"分页跳行"
这种 bug 会以三种不同的形态出现。
"""

from __future__ import annotations

import base64
import json
from datetime import datetime
from typing import Any

DEFAULT_LIMIT = 20
MAX_LIMIT = 50


def clamp_limit(value: int | None, default: int = DEFAULT_LIMIT, maximum: int = MAX_LIMIT) -> int:
    """搜索态强制 `limit ≤ 50`（spec §8.2 搜索策略）；普通列表也用它。"""
    if value is None or value <= 0:
        return default
    return min(value, maximum)


def encode_cursor(created_at: datetime | None, row_id: str) -> str | None:
    """不透明游标：`created_at|id` 的 base64。用 offset 会在并发插入时跳行。"""
    if created_at is None:
        return None
    raw = f"{created_at.strftime('%Y-%m-%dT%H:%M:%S.%f')}|{row_id}"
    return base64.urlsafe_b64encode(raw.encode("utf-8")).decode("ascii")


def decode_cursor(cursor: str | None) -> tuple[datetime, str] | None:
    if not cursor:
        return None
    try:
        raw = base64.urlsafe_b64decode(cursor.encode("ascii")).decode("utf-8")
        ts, _, row_id = raw.partition("|")
        return datetime.fromisoformat(ts), row_id
    except Exception:  # noqa: BLE001 - 坏游标当"从头开始"，不是 500
        return None


def json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))

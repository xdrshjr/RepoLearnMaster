"""可注入时钟。

`utcnow()` 是唯一的时间来源。把它做成函数而不是到处 `datetime.now(timezone.utc)`，
是为了让"预算超时/心跳回收/reaper 判定"这类依赖时间的逻辑能在测试里被推进，
而不是靠 `sleep`（那会让测试既慢又不稳）。
"""

from __future__ import annotations

import time
from datetime import datetime, timezone

_offset_seconds: float = 0.0


def utcnow() -> datetime:
    if _offset_seconds:
        return datetime.fromtimestamp(time.time() + _offset_seconds, tz=timezone.utc)
    return datetime.now(timezone.utc)


def monotonic_ms() -> float:
    """单调时钟；预算与超时只能用它，墙钟跳变会让预算瞬间失效。"""
    return time.monotonic() * 1000.0


def iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def advance(seconds: float) -> None:
    """测试辅助：把"当前时间"往前推。"""
    global _offset_seconds
    _offset_seconds += seconds


def reset() -> None:
    global _offset_seconds
    _offset_seconds = 0.0

"""ID 生成器。

全项目只有这一处生成 ID：`<prefix>_<ulid>`。ULID 的价值是**字典序即时间序**，
游标分页可以直接按 id 排序而不需要额外的 created_at 索引（spec §6.1）。
这里手写 ULID（48bit 时间戳 + 80bit 随机）而不引依赖：只有 20 行，且避免
为一个纯函数增加一个需要跟随升级的包。
"""

from __future__ import annotations

import os
import time

_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"  # Crockford base32（去掉 ILOU）

PREFIX = {
    "user": "usr",
    "repository": "rep",
    "commit": "cmt",
    "course_version": "crs",
    "lesson": "lsn",
    "step": "stp",
    "anchor": "anc",
    "trace": "trc",
    "quiz": "qz",
    "book": "bok",
    "chapter": "chp",
    "pdf": "pdf",
    "job": "job",
    "profile": "prf",
    "revision": "rev",
    "event": "evt",
    "note": "not",
    "question": "qst",
    "audio": "aud",
}


def _encode(value: int, length: int) -> str:
    out = []
    for _ in range(length):
        out.append(_ALPHABET[value & 0x1F])
        value >>= 5
    return "".join(reversed(out))


def ulid() -> str:
    ts = int(time.time() * 1000) & ((1 << 48) - 1)
    rand = int.from_bytes(os.urandom(10), "big")
    return _encode(ts, 10) + _encode(rand, 16)


def new_id(kind: str) -> str:
    prefix = PREFIX.get(kind, kind[:3])
    return f"{prefix}_{ulid()}"


def is_valid_id(value: str, kind: str | None = None) -> bool:
    if not isinstance(value, str) or "_" not in value:
        return False
    prefix, _, body = value.partition("_")
    if len(body) != 26 or any(ch not in _ALPHABET for ch in body):
        return False
    return kind is None or prefix == PREFIX.get(kind, kind[:3])

"""对象存储（spec §6.6）。

布局：
```
var/objects/mirrors/<sha8>/      只读仓库镜像（LRU 2GB）
var/objects/audio/<hh>/<hash>.mp3
var/objects/pdf/<book>/<preset>-v<template>.pdf
var/objects/diagrams/<course>/<key>.svg
var/objects/artifacts/<job>/<node>/<key>.json   ← LangGraph 状态外置产物
```

三条设计决定：
1. **内容寻址**：文件名的 hash 就是内容 hash，因此 `ETag` 天然成立（内容变则 ETag 变），
   也就天然满足 §5.2 的 `If-None-Match → 304`。
2. **`Range` 支持在读取侧**：`read_range()` 返回 `(bytes, start, end, total)`，
   由 router 负责拼 `206/416`。把 HTTP 语义留在 router，存储层只认字节区间。
3. **路径装配只在这里**：所有 `var/objects/...` 字符串都必须来自本模块，
   否则"契约里写 /api/objects、磁盘上写 var/objects"这类混用迟早会出现（P1-4）。
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any, BinaryIO

from repolearn.core.config import settings
from repolearn.core.logging import get_logger

log = get_logger("object_store")

KINDS = ("mirrors", "audio", "pdf", "diagrams", "artifacts")
_SAFE_NAME = re.compile(r"^[A-Za-z0-9._\-/]+$")
_SAFE_HASH = re.compile(r"^[a-f0-9]{8,64}$")


class ObjectMissing(Exception):
    def __init__(self, key: str) -> None:
        super().__init__(f"object not found: {key}")
        self.key = key


@dataclass
class RangeResult:
    data: bytes
    start: int
    end: int
    total: int


def _root() -> Path:
    return settings.object_path


def content_hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _validate(kind: str, key: str) -> None:
    if kind not in KINDS:
        raise ValueError(f"unknown object kind: {kind}")
    if not key or ".." in key or key.startswith("/") or "\\" in key:
        raise ValueError(f"invalid object key: {key}")
    if not _SAFE_NAME.match(key):
        raise ValueError(f"unsafe characters in object key: {key}")


def path_for(kind: str, key: str) -> Path:
    _validate(kind, key)
    return _root() / kind / key


def exists(kind: str, key: str) -> bool:
    try:
        return path_for(kind, key).is_file()
    except ValueError:
        return False


def size(kind: str, key: str) -> int:
    p = path_for(kind, key)
    return p.stat().st_size if p.is_file() else 0


def put(kind: str, key: str, data: bytes | str) -> str:
    """写入并返回 key。文本按 UTF-8 落盘（产物 JSON 一律 UTF-8）。"""
    payload = data.encode("utf-8") if isinstance(data, str) else data
    p = path_for(kind, key)
    p.parent.mkdir(parents=True, exist_ok=True)
    # 先写临时文件再 rename：中途崩溃不会留下"半个文件"，而半个 JSON 会被
    # 下游当成"产物损坏"，排查成本远高于多一次 os.replace。
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_bytes(payload)
    os.replace(tmp, p)
    return key


def put_content_addressed(kind: str, data: bytes, ext: str = "") -> str:
    digest = content_hash(data)
    key = f"{digest[:2]}/{digest}{ext}"
    put(kind, key, data)
    return key


def get(kind: str, key: str) -> bytes:
    p = path_for(kind, key)
    if not p.is_file():
        raise ObjectMissing(key)
    return p.read_bytes()


def get_json(kind: str, key: str) -> Any:
    return json.loads(get(kind, key).decode("utf-8"))


def put_json(kind: str, key: str, payload: Any) -> str:
    return put(kind, key, json.dumps(payload, ensure_ascii=False))


def etag_for(kind: str, key: str) -> str:
    """内容寻址存储天然满足"内容变则 ETag 变"（§5.2）。"""
    p = path_for(kind, key)
    if not p.is_file():
        raise ObjectMissing(key)
    if _SAFE_HASH.match(p.stem):
        return f'"{p.stem[:32]}"'
    h = hashlib.sha256()
    with p.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return f'"{h.hexdigest()[:32]}"'


def read_range(kind: str, key: str, start: int | None = None, end: int | None = None) -> RangeResult:
    """按字节区间读取。区间非法时**抛 ValueError**，由 router 转成 416。

    这里不做 `bytes=0-` 这类语法解析——那是 HTTP 的事。存储层只接受已经
    解析好的整数，这样"越界"只有一种表达方式。
    """
    p = path_for(kind, key)
    if not p.is_file():
        raise ObjectMissing(key)
    total = p.stat().st_size
    if start is None:
        return RangeResult(data=p.read_bytes(), start=0, end=max(0, total - 1), total=total)
    if start < 0 or start >= total:
        raise ValueError(f"range start {start} out of bounds (total={total})")
    actual_end = total - 1 if end is None else min(end, total - 1)
    if actual_end < start:
        raise ValueError(f"range end {actual_end} before start {start}")
    with p.open("rb") as fh:
        fh.seek(start)
        data = fh.read(actual_end - start + 1)
    return RangeResult(data=data, start=start, end=actual_end, total=total)


def public_url(kind: str, key: str) -> str:
    """对外（浏览器）地址：**永远同源** `/api/objects/...`（spec §5.3 P1-4）。"""
    return f"/api/objects/{kind}/{key}"


def internal_url(kind: str, key: str) -> str:
    """BFF → API 的地址。只出现在 BFF 里，不出现在契约里。"""
    return f"/v1/objects/{kind}/{key}"


def open_stream(kind: str, key: str) -> BinaryIO:
    p = path_for(kind, key)
    if not p.is_file():
        raise ObjectMissing(key)
    return p.open("rb")


def remove(kind: str, key: str) -> bool:
    try:
        p = path_for(kind, key)
    except ValueError:
        return False
    if p.is_file():
        p.unlink()
        return True
    return False


def list_keys(kind: str) -> list[str]:
    base = _root() / kind
    if not base.exists():
        return []
    return sorted(str(p.relative_to(base)).replace("\\", "/") for p in base.rglob("*") if p.is_file())


def mirror_dir(sha8: str) -> Path:
    _validate("mirrors", sha8)
    return _root() / "mirrors" / sha8


def clear_mirror(sha8: str) -> None:
    d = mirror_dir(sha8)
    if d.exists():
        shutil.rmtree(d, ignore_errors=True)


def prune_mirrors(max_bytes: int = 2 * 1024 * 1024 * 1024) -> dict[str, int]:
    """镜像 LRU 清理（spec §6.6 / T-OPS-1）。

    按 mtime 从旧到新删，直到总量回到 max_bytes 之下。**只删镜像**：
    音频与 PDF 是内容寻址并被数据库引用的，误删会直接产生 404。
    """
    base = _root() / "mirrors"
    if not base.exists():
        return {"removed_dirs": 0, "removed_bytes": 0}
    entries: list[tuple[float, Path, int]] = []
    total = 0
    for child in base.iterdir():
        if not child.is_dir():
            continue
        sz = sum(f.stat().st_size for f in child.rglob("*") if f.is_file())
        total += sz
        entries.append((child.stat().st_mtime, child, sz))
    removed_dirs = 0
    removed_bytes = 0
    for _mtime, path, sz in sorted(entries):
        if total <= max_bytes:
            break
        shutil.rmtree(path, ignore_errors=True)
        total -= sz
        removed_dirs += 1
        removed_bytes += sz
    return {"removed_dirs": removed_dirs, "removed_bytes": removed_bytes}


def artifact_key(job_id: str, node: str, name: str) -> str:
    """LangGraph 状态外置产物的 key（spec §3.4：state 里只留引用）。"""
    safe_node = re.sub(r"[^A-Za-z0-9_\-]", "_", node)
    safe_name = re.sub(r"[^A-Za-z0-9_\-.]", "_", name)
    return f"{job_id}/{safe_node}/{safe_name}"

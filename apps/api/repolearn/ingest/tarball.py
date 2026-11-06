"""tarball 解包（spec §3.4 N3 / R3）。

Windows 上的三个坑，每个都对应一段代码：
1. **文件名编码**：GitHub tarball 的路径可能含 UTF-8 中文/emoji，`tarfile` 直接解会
   在 Windows 上按 locale 解码失败 → 统一用 `tarfile.open(fileobj=..., mode="r:gz")`
   并逐条 `extractfile()` 自己写盘（不调 `extractall`，那条路不接受我们的路径策略）。
2. **长路径**：260 字符限制 → `guard.check_path` 已把路径压到 180 以内。
3. **符号链接/设备文件**：`extractall` 会老老实实创建它们 → 我们只接受普通文件。
"""

from __future__ import annotations

import io
import tarfile
from dataclasses import dataclass, field
from pathlib import Path

from repolearn.core.errors import AppError
from repolearn.core.logging import get_logger
from repolearn.ingest.guard import GuardStats, accumulate, should_keep

log = get_logger("tarball")


@dataclass
class ExtractResult:
    root: Path
    files: list[str] = field(default_factory=list)
    stats: GuardStats = field(default_factory=GuardStats)
    blocked: list[str] = field(default_factory=list)


def _strip_first_component(name: str) -> str:
    """GitHub tarball 的所有路径都以 `<owner>-<repo>-<sha>/` 开头，去掉它。"""
    parts = name.split("/", 1)
    return parts[1] if len(parts) == 2 else ""


def extract_tarball(data: bytes, dest: Path) -> ExtractResult:
    dest = dest.resolve()
    dest.mkdir(parents=True, exist_ok=True)
    result = ExtractResult(root=dest)
    try:
        tar = tarfile.open(fileobj=io.BytesIO(data), mode="r:gz")
    except tarfile.TarError as exc:
        raise AppError("PROVIDER_UNAVAILABLE", f"仓库压缩包无法解析：{exc}", retryable=False) from exc

    with tar:
        for member in tar:
            if not member.isfile():
                # 目录由写文件时自动创建；符号链接/硬链接/设备文件一律跳过。
                if member.issym() or member.islnk():
                    result.stats.blocked += 1
                    if len(result.blocked) < 20:
                        result.blocked.append(f"SYMLINK: {member.name}")
                continue
            rel = _strip_first_component(member.name)
            if not rel:
                continue
            decision = should_keep(rel, member.size)
            accumulate(result.stats, decision, member.size)
            if not decision.ok:
                if len(result.blocked) < 20:
                    result.blocked.append(f"{decision.code}: {decision.reason} ({rel})")
                continue
            if result.stats.truncated:
                break
            src = tar.extractfile(member)
            if src is None:
                continue
            target = dest / decision.rel_path
            try:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(src.read())
            except OSError as exc:
                log.warning("extract_write_failed", path=decision.rel_path, error=str(exc))
                continue
            result.files.append(decision.rel_path)
    log.info(
        "extract_done",
        accepted=result.stats.accepted,
        blocked=result.stats.blocked,
        bytes=result.stats.bytes,
    )
    return result

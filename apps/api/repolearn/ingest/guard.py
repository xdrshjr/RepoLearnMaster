"""仓库内容安全过滤（spec §3.12 / T-SEC-2）。

**仓库内容是不可信输入**。这个文件是唯一允许把外部字节写进镜像的地方，
因此所有"路径长什么样"的判定都集中在这里：

* 绝对路径、`..`、空字节、Windows 设备名（`CON`/`NUL`/`COM1`…）、
  符号链接/junction、可执行文件、超大文件；
* 文件名 sanitize：保留 `[A-Za-z0-9._-]`，其余转义为 `_`。理由是 Windows 上
  中文/emoji 文件名会在解包与 tree-sitter 之间产生编码不一致，而"转义"是
  唯一不会在三个环节里各错一次的方案；
* 路径总长限制 180 字符（R3：Windows 260 字符限制 + 镜像根前缀的余量）。
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import PurePosixPath

MAX_PATH_LEN = 180
MAX_FILE_BYTES = 2 * 1024 * 1024  # 单文件 2 MB；再大就不是"用来读的代码"了
MAX_FILES = 4000

BLOCKED_EXT = {
    ".exe", ".dll", ".so", ".dylib", ".bin", ".o", ".a", ".lib", ".class",
    ".jar", ".msi", ".bat", ".cmd", ".com", ".scr", ".ps1", ".vbs", ".apk",
    ".dmg", ".iso", ".whl", ".egg", ".pt", ".pth", ".onnx", ".safetensors",
    ".zip", ".tar", ".gz", ".bz2", ".xz", ".7z", ".rar",
}

BINARY_EXT = {
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico", ".bmp", ".tiff",
    ".mp3", ".wav", ".ogg", ".mp4", ".mov", ".avi", ".woff", ".woff2",
    ".ttf", ".otf", ".eot", ".pdf", ".psd", ".ai",
}

IGNORED_DIRS = {
    ".git", ".hg", ".svn", "node_modules", "__pycache__", ".venv", "venv",
    "dist", "build", ".next", ".nuxt", ".mypy_cache", ".pytest_cache",
    ".ruff_cache", "target", "vendor", ".idea", ".vscode", ".gradle",
    "coverage", "htmlcov", ".tox", "Pods",
}

_WINDOWS_DEVICE = re.compile(r"^(con|prn|aux|nul|com[1-9]|lpt[1-9])(\..*)?$", re.IGNORECASE)
_UNSAFE_CHARS = re.compile(r"[^A-Za-z0-9._\-]")


@dataclass
class GuardDecision:
    ok: bool
    rel_path: str = ""
    reason: str = ""
    code: str = ""


@dataclass
class GuardStats:
    accepted: int = 0
    blocked: int = 0
    bytes: int = 0
    blocked_reasons: list[str] = field(default_factory=list)
    truncated: bool = False

    def as_warnings(self) -> list[dict]:
        out: list[dict] = []
        if self.blocked:
            out.append(
                {
                    "code": "INGEST_BLOCKED_PATH",
                    "message": f"跳过 {self.blocked} 个不安全/不支持的文件",
                    "severity": "info",
                    "node": "fetch_repo",
                }
            )
        if self.truncated:
            out.append(
                {
                    "code": "REPO_TRUNCATED",
                    "message": f"仓库文件数超过上限 {MAX_FILES}，只取前 {MAX_FILES} 个",
                    "severity": "warning",
                    "node": "fetch_repo",
                }
            )
        return out


def sanitize_name(name: str) -> str:
    """把文件名转义成 ASCII 安全形态，保留原扩展名。"""
    p = PurePosixPath(name)
    stem = _UNSAFE_CHARS.sub("_", p.stem) or "file"
    suffix = _UNSAFE_CHARS.sub("_", p.suffix) if p.suffix else ""
    return f"{stem}{suffix}"[:120]


def check_path(rel_path: str) -> GuardDecision:
    """校验一个仓库内相对路径是否允许落盘。"""
    raw = (rel_path or "").replace("\\", "/").strip()
    if not raw:
        return GuardDecision(False, code="EMPTY", reason="empty path")
    if "\x00" in raw:
        return GuardDecision(False, code="NULL_BYTE", reason="null byte")
    if raw.startswith("/") or re.match(r"^[A-Za-z]:", raw):
        return GuardDecision(False, code="ABSOLUTE", reason="absolute path")
    parts = [p for p in raw.split("/") if p not in ("", ".")]
    if any(p == ".." for p in parts):
        return GuardDecision(False, code="TRAVERSAL", reason="parent traversal")
    for part in parts:
        if _WINDOWS_DEVICE.match(part):
            return GuardDecision(False, code="DEVICE_NAME", reason=f"reserved device name: {part}")
        if part in IGNORED_DIRS:
            return GuardDecision(False, code="IGNORED_DIR", reason=f"ignored dir: {part}")
    # 先按**原始**长度判定，再 sanitize。反过来的话，`sanitize_name` 的 120 字符截断
    # 会把一条 200 字符的路径"修好"，于是两个不同的超长文件被截成同一个名字——
    # 症状是"明明有这个文件，镜像里却只有另一个文件的内容"。
    if len(raw) > MAX_PATH_LEN:
        return GuardDecision(False, code="PATH_TOO_LONG", reason=f"path longer than {MAX_PATH_LEN}")
    safe_parts = [sanitize_name(p) for p in parts]
    safe = "/".join(safe_parts)
    if len(safe) > MAX_PATH_LEN:
        return GuardDecision(False, code="PATH_TOO_LONG", reason=f"path longer than {MAX_PATH_LEN}")
    ext = PurePosixPath(safe).suffix.lower()
    if ext in BLOCKED_EXT:
        return GuardDecision(False, code="BLOCKED_EXT", reason=f"blocked extension {ext}")
    return GuardDecision(True, rel_path=safe)


def is_text_file(rel_path: str) -> bool:
    ext = PurePosixPath(rel_path).suffix.lower()
    return ext not in BINARY_EXT


def is_symlink(path: str) -> bool:
    """符号链接与 Windows junction/reparse point 都要拦（spec §3.12）。"""
    try:
        if os.path.islink(path):
            return True
        if os.name == "nt":
            attrs = os.stat(path, follow_symlinks=False).st_file_attributes
            return bool(attrs & 0x400)  # FILE_ATTRIBUTE_REPARSE_POINT
    except OSError:
        return False
    return False


def should_keep(rel_path: str, size: int) -> GuardDecision:
    """完整判定：路径 + 体积 + 文本性。"""
    decision = check_path(rel_path)
    if not decision.ok:
        return decision
    if not is_text_file(decision.rel_path):
        return GuardDecision(False, code="BINARY", reason="binary/media file")
    if size > MAX_FILE_BYTES:
        return GuardDecision(False, code="TOO_LARGE", reason=f"file larger than {MAX_FILE_BYTES} bytes")
    return decision


def accumulate(stats: GuardStats, decision: GuardDecision, size: int = 0) -> None:
    if decision.ok:
        stats.accepted += 1
        stats.bytes += size
        if stats.accepted > MAX_FILES:
            stats.truncated = True
    else:
        stats.blocked += 1
        if len(stats.blocked_reasons) < 20:
            stats.blocked_reasons.append(f"{decision.code}: {decision.reason}")

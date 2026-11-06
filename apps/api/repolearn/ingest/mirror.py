"""镜像管理（spec §3.4 N3 / §6.6）。

镜像 = `var/objects/mirrors/<sha8>/` 下的一份只读副本。为什么坚持"落盘镜像"而不是
每次现拉：N4（分析）、N6（写课时）、N7（校验锚点）与行内提问都要反复按文件读源码；
每读一次都打一次 GitHub，既慢又会把限额烧光。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from repolearn.core.config import settings
from repolearn.core.logging import get_logger
from repolearn.services import object_store

log = get_logger("mirror")

CORE_EXTS = {".py", ".ts", ".tsx", ".js", ".jsx", ".go", ".rs", ".java", ".md"}


@dataclass
class MirrorInfo:
    sha8: str
    path: Path
    file_count: int
    bytes: int
    reused: bool


def mirror_path(sha: str) -> Path:
    return object_store.mirror_dir(sha[:8])


def exists(sha: str) -> bool:
    p = mirror_path(sha)
    return p.is_dir() and any(p.iterdir())


def stat_mirror(sha: str) -> MirrorInfo:
    p = mirror_path(sha)
    if not p.is_dir():
        return MirrorInfo(sha8=sha[:8], path=p, file_count=0, bytes=0, reused=False)
    files = [f for f in p.rglob("*") if f.is_file()]
    return MirrorInfo(
        sha8=sha[:8],
        path=p,
        file_count=len(files),
        bytes=sum(f.stat().st_size for f in files),
        reused=True,
    )


def read_file(sha: str, rel_path: str, max_bytes: int = 512 * 1024) -> str:
    """读镜像内文件。**路径必须仍在镜像根内**——Kernel 侧有同样的校验，两侧都要有：

    只在一侧做校验意味着"绕过另一侧"就是一条可用的攻击路径。
    """
    from repolearn.ingest.guard import check_path

    decision = check_path(rel_path)
    if not decision.ok:
        raise ValueError(f"路径被拒绝：{decision.reason}")
    root = mirror_path(sha).resolve()
    target = (root / decision.rel_path).resolve()
    if not str(target).startswith(str(root)):
        raise ValueError("路径越界")
    if not target.is_file():
        raise FileNotFoundError(decision.rel_path)
    return target.read_bytes()[:max_bytes].decode("utf-8", "ignore")


def line_count(sha: str, rel_path: str) -> int:
    try:
        text = read_file(sha, rel_path)
    except (ValueError, FileNotFoundError):
        return 0
    return text.count("\n") + (0 if text.endswith("\n") else 1)


def list_files(sha: str) -> list[dict]:
    """镜像文件清单（供 N3 的 tree 与锚点校验使用）。"""
    base = mirror_path(sha)
    out: list[dict] = []
    if not base.exists():
        return out
    for path in sorted(base.rglob("*")):
        if not path.is_file():
            continue
        rel = str(path.relative_to(base)).replace("\\", "/")
        ext = path.suffix.lower()
        out.append(
            {
                "path": rel,
                "size": path.stat().st_size,
                "lang": _lang_of(ext),
                "is_core": ext in CORE_EXTS,
            }
        )
    return out


def _lang_of(ext: str) -> str:
    return {
        ".py": "python",
        ".ts": "typescript",
        ".tsx": "typescript",
        ".js": "javascript",
        ".jsx": "javascript",
        ".go": "go",
        ".rs": "rust",
        ".java": "java",
        ".md": "markdown",
        ".json": "json",
        ".toml": "toml",
        ".yaml": "yaml",
        ".yml": "yaml",
    }.get(ext, "text")


def ensure_readonly(sha: str) -> None:
    """尽力把镜像目录置为只读（Windows 下只能去掉写位，POSIX 下去掉 w）。

    这是**防御纵深**而不是安全边界：真正的边界是"没有任何代码路径执行仓库内容"。
    但如果有人未来加了 `subprocess`，只读镜像会让它立刻失败而不是静默得逞。
    """
    base = mirror_path(sha)
    if not base.exists():
        return
    import os
    import stat

    for path in base.rglob("*"):
        try:
            if path.is_file():
                mode = path.stat().st_mode
                path.chmod(mode & ~stat.S_IWUSR & ~stat.S_IWGRP & ~stat.S_IWOTH)
        except OSError:
            continue
    if not settings.env == "development":
        log.info("mirror_readonly", sha8=sha[:8])

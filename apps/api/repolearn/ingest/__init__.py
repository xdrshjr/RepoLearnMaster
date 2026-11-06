"""仓库摄取层。

对外只有一个编排入口 `fetch_and_mirror()`：N1 归一 → N2 解析 commit → N3 下载+解包。
把三步合成一个函数，是因为它们共享同一个"失败就整体失败"的语义——单独暴露
`download()` 只会诱导调用方漏掉 guard 校验。
"""

from __future__ import annotations

from dataclasses import dataclass

from repolearn.core.errors import AppError
from repolearn.core.logging import get_logger
from repolearn.ingest.github import (
    CommitMeta,
    RepoMeta,
    RepoRef,
    download_tarball,
    fetch_repo_meta,
    list_tree,
    parse_repo_url,
    resolve_commit,
)
from repolearn.ingest.mirror import ensure_readonly, exists, mirror_path, stat_mirror
from repolearn.ingest.tarball import ExtractResult, extract_tarball

__all__ = [
    "CommitMeta",
    "ExtractResult",
    "RepoMeta",
    "RepoRef",
    "fetch_and_mirror",
    "fetch_repo_meta",
    "list_tree",
    "mirror_exists",
    "mirror_path",
    "mirror_stat",
    "parse_repo_url",
    "resolve_commit",
]

log = get_logger("ingest")


def mirror_exists(sha: str) -> bool:
    return exists(sha)


def mirror_stat(sha: str):
    return stat_mirror(sha)


@dataclass
class IngestOutcome:
    ref: RepoRef
    meta: RepoMeta
    commit: CommitMeta
    extraction: ExtractResult | None
    reused: bool


async def fetch_and_mirror(repo_url: str, wanted_ref: str | None = None) -> IngestOutcome:
    ref = parse_repo_url(repo_url)
    meta = await fetch_repo_meta(ref)
    if meta.is_private:
        raise AppError("REPO_FORBIDDEN", "该仓库是私有仓库", hint="私有仓库不在当前版本范围内")
    commit = await resolve_commit(ref, meta.default_branch, wanted_ref or ref.ref)
    if not commit.sha:
        raise AppError("PROVIDER_UNAVAILABLE", "未能解析出 Commit SHA")

    if exists(commit.sha):
        info = stat_mirror(commit.sha)
        log.info("mirror_reused", sha8=commit.sha[:8], files=info.file_count)
        return IngestOutcome(ref=ref, meta=meta, commit=commit, extraction=None, reused=True)

    data = await download_tarball(ref, commit.sha)
    commit.extra["tarball_bytes"] = len(data)
    result = extract_tarball(data, mirror_path(commit.sha))
    commit.file_count = len(result.files)
    ensure_readonly(commit.sha)
    log.info("mirror_ready", sha8=commit.sha[:8], files=len(result.files), blocked=result.stats.blocked)
    return IngestOutcome(ref=ref, meta=meta, commit=commit, extraction=result, reused=False)

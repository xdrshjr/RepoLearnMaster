"""GitHub 接入（spec §3.4 N1/N2/N3）。

只做三件事：解析 URL、取仓库元数据、取 tarball。**不执行任何仓库代码**。

两个"稳健"设计：
1. **URL 解析比正则更宽**：`https://github.com/o/r`、`o/r`、`git@github.com:o/r.git`、
   带 `/tree/ref` 与 `.git` 后缀、带尾部斜杠都要能认。用户粘贴什么形状都不该报错。
2. **限流是数据不是异常**：`RATE_LIMITED` 带上重置时间与"配置 token"的可执行提示，
   否则用户只会看到"生成失败"。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from urllib.parse import urlparse

from repolearn.core.config import settings
from repolearn.core.errors import AppError
from repolearn.core.logging import get_logger
from repolearn.providers.http import new_client, request_with_retry

log = get_logger("github")

API = "https://api.github.com"
_OWNER_REPO = re.compile(r"^[A-Za-z0-9_.\-]+/[A-Za-z0-9_.\-]+$")


@dataclass
class RepoRef:
    full_name: str
    owner: str
    name: str
    ref: str | None = None


@dataclass
class RepoMeta:
    full_name: str
    owner: str
    name: str
    description: str | None
    stars: int
    license_spdx: str | None
    primary_language: str | None
    default_branch: str
    html_url: str
    size_kb: int = 0
    is_private: bool = False


@dataclass
class CommitMeta:
    sha: str
    committed_at: str | None = None
    message: str = ""
    file_count: int = 0
    extra: dict = field(default_factory=dict)


def parse_repo_url(raw: str) -> RepoRef:
    """把各种形状的仓库地址归一成 `owner/name`（+ 可选 ref）。

    宽松解析是有意的：这个输入框是产品的入口，它报错的成本远高于多试几种形状。
    """
    text = (raw or "").strip()
    if not text:
        raise AppError("REPO_NOT_FOUND", "仓库地址不能为空", hint="粘贴形如 https://github.com/owner/repo 的地址")
    text = text.rstrip("/")
    if text.startswith("git@"):
        text = text.replace(":", "/", 1).replace("git@", "https://", 1)
    if text.startswith("github.com/"):
        text = f"https://{text}"
    if "://" in text:
        parsed = urlparse(text)
        if parsed.netloc.lower() not in ("github.com", "www.github.com"):
            raise AppError(
                "REPO_NOT_FOUND",
                "目前只支持 GitHub 仓库",
                hint="形如 https://github.com/owner/repo",
            )
        parts = [p for p in parsed.path.split("/") if p]
    else:
        parts = [p for p in text.split("/") if p]
    if len(parts) < 2:
        raise AppError("REPO_NOT_FOUND", "无法从地址中解析出 owner/repo", hint="形如 owner/repo")
    owner, name = parts[0], parts[1]
    if name.endswith(".git"):
        name = name[:-4]
    ref: str | None = None
    if len(parts) >= 4 and parts[2] in ("tree", "blob", "commit"):
        ref = parts[3]
    full = f"{owner}/{name}"
    if not _OWNER_REPO.match(full):
        raise AppError("REPO_NOT_FOUND", f"仓库名不合法：{full}", hint="仓库名只能包含字母、数字、-、_、.")
    return RepoRef(full_name=full, owner=owner, name=name, ref=ref)


def _headers() -> dict[str, str]:
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "RepoLearn/0.1",
    }
    if settings.github_token:
        headers["Authorization"] = f"Bearer {settings.github_token}"
    return headers


def _map_github_error(status: int, body: str) -> AppError:
    if status == 404:
        return AppError("REPO_NOT_FOUND", details={"status": status})
    if status in (401, 403) and "rate limit" in body.lower():
        return AppError(
            "RATE_LIMITED",
            "GitHub 接口限流",
            hint="在 .env 配置 REPOLEARN_GITHUB_TOKEN 可将限额提升到 5000 次/小时；当前未配置时为 60 次/小时",
        )
    if status in (401, 403):
        return AppError("REPO_FORBIDDEN", details={"status": status})
    return AppError("PROVIDER_UNAVAILABLE", f"GitHub 返回 {status}", details={"body": body[:200]})


async def fetch_repo_meta(ref: RepoRef) -> RepoMeta:
    url = f"{API}/repos/{ref.full_name}"
    async with new_client(timeout_read=20.0) as client:
        resp = await request_with_retry(client, "GET", url, headers=_headers(), attempts=3)
        data = resp.json()
    lic = data.get("license") or {}
    return RepoMeta(
        full_name=str(data.get("full_name", ref.full_name)),
        owner=str((data.get("owner") or {}).get("login", ref.owner)),
        name=str(data.get("name", ref.name)),
        description=data.get("description"),
        stars=int(data.get("stargazers_count", 0) or 0),
        license_spdx=lic.get("spdx_id") if isinstance(lic, dict) else None,
        primary_language=data.get("language"),
        default_branch=str(data.get("default_branch", "main")),
        html_url=str(data.get("html_url", f"https://github.com/{ref.full_name}")),
        size_kb=int(data.get("size", 0) or 0),
        is_private=bool(data.get("private", False)),
    )


async def resolve_commit(ref: RepoRef, branch: str, wanted_ref: str | None = None) -> CommitMeta:
    """取 HEAD（或指定 ref）的 sha。网络错误退避重试 3 次（spec §3.4 N2）。"""
    target = wanted_ref or branch
    url = f"{API}/repos/{ref.full_name}/commits/{target}"
    async with new_client(timeout_read=20.0) as client:
        try:
            resp = await request_with_retry(client, "GET", url, headers=_headers(), attempts=3)
        except Exception as exc:  # noqa: BLE001
            raise AppError("PROVIDER_UNAVAILABLE", f"无法获取 Commit：{exc}") from exc
        data = resp.json()
    commit = data.get("commit") or {}
    author = commit.get("author") or {}
    files = data.get("files") or []
    return CommitMeta(
        sha=str(data.get("sha", "")),
        committed_at=author.get("date"),
        message=str(commit.get("message", ""))[:400],
        file_count=len(files) if isinstance(files, list) else 0,
        extra={"html_url": data.get("html_url")},
    )


async def download_tarball(ref: RepoRef, sha: str, max_bytes: int | None = None) -> bytes:
    """下载 tarball。超限抛 `REPO_TOO_LARGE`——先判 `Content-Length` 再流式下载，
    避免"先下 500MB 再告诉用户太大"。"""
    limit = (max_bytes or settings.max_repo_mb * 1024 * 1024)
    url = f"{API}/repos/{ref.full_name}/tarball/{sha}"
    async with new_client(timeout_read=120.0) as client:
        async with client.stream("GET", url, headers=_headers()) as resp:
            if resp.status_code >= 400:
                body = (await resp.aread()).decode("utf-8", "ignore")
                raise _map_github_error(resp.status_code, body)
            declared = resp.headers.get("content-length")
            if declared and declared.isdigit() and int(declared) > limit:
                raise AppError(
                    "REPO_TOO_LARGE",
                    f"仓库压缩包约 {int(declared) // (1024 * 1024)} MB，超过上限 {limit // (1024 * 1024)} MB",
                    details={"declared_bytes": int(declared)},
                )
            buf = bytearray()
            async for chunk in resp.aiter_bytes():
                buf.extend(chunk)
                if len(buf) > limit:
                    raise AppError(
                        "REPO_TOO_LARGE",
                        f"仓库压缩包超过上限 {(limit) // (1024 * 1024)} MB",
                        details={"limit_bytes": limit},
                    )
            return bytes(buf)


async def list_tree(ref: RepoRef, sha: str) -> list[dict]:
    """Git Trees API。tarball 超限时的降级路径：只挑核心文件（spec §3.4 N3）。"""
    url = f"{API}/repos/{ref.full_name}/git/trees/{sha}?recursive=1"
    async with new_client(timeout_read=30.0) as client:
        resp = await request_with_retry(client, "GET", url, headers=_headers(), attempts=2)
        data = resp.json()
    out: list[dict] = []
    for item in (data.get("tree") or []) if isinstance(data, dict) else []:
        if not isinstance(item, dict) or item.get("type") != "blob":
            continue
        out.append({"path": item.get("path", ""), "size": int(item.get("size", 0) or 0), "sha": item.get("sha", "")})
    return out


async def fetch_raw_file(ref: RepoRef, sha: str, path: str, max_bytes: int = 512 * 1024) -> str:
    url = f"{API}/repos/{ref.full_name}/contents/{path}?ref={sha}"
    headers = {**_headers(), "Accept": "application/vnd.github.raw"}
    async with new_client(timeout_read=30.0) as client:
        resp = await request_with_retry(client, "GET", url, headers=headers, attempts=2)
        return resp.text[:max_bytes]


def rate_limit_hint(remaining: int | None = None) -> str:
    if settings.github_token:
        return f"已配置 GitHub Token，剩余额度 {remaining if remaining is not None else '未知'}"
    return "未配置 REPOLEARN_GITHUB_TOKEN，限额 60 次/小时；配置后可提升到 5000 次/小时"

"""GitHub 接入（spec §3.4 N1/N2/N3）。

只做三件事：解析 URL、取仓库元数据、取 tarball。**不执行任何仓库代码**。

三个"稳健"设计：
1. **URL 解析比正则更宽**：`https://github.com/o/r`、`o/r`、`git@github.com:o/r.git`、
   带 `/tree/ref` 与 `.git` 后缀、带尾部斜杠都要能认。用户粘贴什么形状都不该报错。
2. **限流是数据不是异常**：`RATE_LIMITED` 带上重置时间与"配置 token"的可执行提示，
   否则用户只会看到"生成失败"。
3. **端点可配置，但端点的返回值不可信**（hardening spec §3.2.1 红线 B）。
   允许用户把端点指向自建 GHE，等于允许一个**会返回任意 JSON 的服务器**参与产品
   链路。三条校验缺一不可：
   * 出站字段白名单——只要我们要的那几个字段，`html_url` 还要过 scheme+host 校验
     （它会被前端渲染成 `<a href>`，一个返回 `javascript:alert(1)` 的端点就是一条
     存储型 XSS）；
   * 重定向逐跳校验——真实 GitHub 的 tarball 会 302 到 codeload，所以不能关掉
     跟随；但**每一跳**的 host 都必须在白名单里，否则 302 就是一条 SSRF 通道；
   * 体积双检——`Content-Length` 与实际收到的字节都要查，不能只信 `/repos` 里
     那个 `size` 字段（端点可以声称 1KB 实际发 1GB）。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from urllib.parse import urlparse

from repolearn.core.config import settings
from repolearn.core.errors import AppError
from repolearn.core.logging import get_logger
from repolearn.providers.base import LlmError
from repolearn.providers.http import new_client, request_with_retry

log = get_logger("github")

_OWNER_REPO = re.compile(r"^[A-Za-z0-9_.\-]+/[A-Za-z0-9_.\-]+$")
_SHA_RE = re.compile(r"[0-9a-f]{40,64}")

#: 重定向跳数上限。真实链路是 `api.github.com → codeload.github.com` 一跳；
#: 给到 3 是给 GHE 的镜像层留余量，再往上就没有正当理由了。
MAX_REDIRECT_HOPS = 3


def _api() -> str:
    """端点基址**每次现取**而不是模块常量。

    保留函数形式是为了两件事：① 测试可以 monkeypatch 配置后立刻生效（模块常量
    会把它钉死在 import 时刻）；② 指向 GHE 的部署不需要改代码，只需要改 `.env`。
    """
    return settings.github_api


def _web() -> str:
    return settings.github_web


def _allowed_hosts() -> frozenset[str]:
    return settings.github_allowed_hosts


def _http_allowed() -> bool:
    """是否允许 `http://` 形式的仓库地址。

    默认只允许 https：明文传输会把仓库地址与 token 暴露在同一网络的旁观者面前。
    两种例外都是"明示配置"而不是"自动放宽"：`REPOLEARN_ENV=test`（E2E 用
    `http://127.0.0.1:9911` 的假 GitHub），或者 web base 自身就是 `http://`
    （自建内网 GHE 常见形态）。
    """
    if str(settings.env).lower() in {"test", "dev", "development"}:
        return True
    return _web().startswith("http://") or _api().startswith("http://")


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
    但**host 必须属于配置的端点**——放宽成"任意 host 都行"就是 SSRF 的前兆。
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
        if parsed.scheme not in ("http", "https"):
            raise AppError(
                "REPO_NOT_FOUND",
                f"不支持的协议：{parsed.scheme}",
                hint="只接受 http(s)；企业自建 GHE 请在 .env 配置 REPOLEARN_GITHUB_WEB_BASE",
            )
        if parsed.scheme == "http" and not _http_allowed():
            raise AppError(
                "REPO_NOT_FOUND",
                "只接受 https 仓库地址",
                hint="改用 https 地址；若这是内网 GHE，请在 .env 把 REPOLEARN_GITHUB_WEB_BASE 设为对应的 http 地址",
            )
        if parsed.netloc.lower() not in _allowed_hosts():
            raise AppError(
                "REPO_NOT_FOUND",
                "目前只支持 GitHub 仓库",
                hint=f"形如 {_web()}/owner/repo；自建 GHE 请配置 REPOLEARN_GITHUB_WEB_BASE（当前允许：{', '.join(sorted(_allowed_hosts()))}）",
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
        return AppError("REPO_NOT_FOUND", details={"status": status, "endpoint": _api()})
    if status in (401, 403) and "rate limit" in body.lower():
        return AppError(
            "RATE_LIMITED",
            "GitHub 接口限流",
            hint=f"在 .env 配置 REPOLEARN_GITHUB_TOKEN 可将限额提升到 5000 次/小时；端点 {_api()}；未配置 token 时为 60 次/小时",
        )
    if status in (401, 403):
        return AppError("REPO_FORBIDDEN", details={"status": status, "endpoint": _api()})
    return AppError("PROVIDER_UNAVAILABLE", f"GitHub 返回 {status}", details={"body": body[:200], "endpoint": _api()})


# --------------------------------------------------------------------------- #
# 不可信响应的三道闸                                                           #
# --------------------------------------------------------------------------- #


def safe_html_url(candidate: object, *, full_name: str) -> str:
    """把端点返回的 `html_url` 变成**我们敢渲染成链接**的值。

    它会被前端写成 `<a href>`，所以 `javascript:alert(1)`、以及指向未配置域的
    钓鱼链接都必须被替换掉。替换目标不是空字符串（那会让页面没有链接），而是
    用配置的 web base 拼装——这个值完全由服务端配置决定，端点无法影响。
    """
    fallback = f"{_web()}/{full_name}"
    if not isinstance(candidate, str) or not candidate.strip():
        return fallback
    parsed = urlparse(candidate.strip())
    if parsed.scheme not in ("http", "https"):
        log.warning("html_url_rejected", reason="scheme", value=candidate[:80])
        return fallback
    if parsed.netloc.lower() not in _allowed_hosts():
        log.warning("html_url_rejected", reason="host", value=candidate[:80])
        return fallback
    return candidate.strip()


def _check_redirects(resp) -> None:
    """逐跳校验重定向落点。

    `httpx` 打开 `follow_redirects` 后不会替我们判断"这一跳去了哪里"，而真实
    GitHub 的 tarball 又**必须**跟随（302 → codeload）。折中做法：跟随，但把
    `resp.history` 里每一跳的 host 都过一遍白名单，跳数也设上限。
    """
    history = getattr(resp, "history", None) or []
    if len(history) > MAX_REDIRECT_HOPS:
        raise AppError(
            "REPO_NOT_FOUND",
            f"重定向次数过多（{len(history)} 跳 > {MAX_REDIRECT_HOPS}）",
            hint="GitHub 端点配置可能有误：正常 tarball 只有 1 跳",
            details={"hops": len(history), "endpoint": _api()},
        )
    allowed = _allowed_hosts()
    for hop in history:
        host = urlparse(str(hop.url)).netloc.lower()
        if host and host not in allowed:
            raise AppError(
                "REPO_NOT_FOUND",
                f"重定向到未配置的域：{host}",
                hint="只允许重定向到已配置的 GitHub 端点；如果你用的是自建镜像，请把它的域加进 REPOLEARN_GITHUB_*_BASE（或不要用它）",
                details={"host": host, "allowed": sorted(allowed)},
            )


def _unreachable(exc: Exception) -> AppError:
    """网络层失败（连不上/超时）→ 可执行的 hint。

    与 `_map_github_error` 分开：那个函数接收的是**端点回了什么**，这里连响应都
    没有。混在一起会把"DNS 解析不了"报成"GitHub 返回 0"。
    """
    return AppError(
        "PROVIDER_UNAVAILABLE",
        f"GitHub 端点不可达：{_api()}",
        hint="检查网络，或确认 .env 里的 REPOLEARN_GITHUB_API_BASE 指向一个真的 GitHub（自建 GHE 形如 https://host/api/v3）",
        details={"endpoint": _api(), "error": str(exc)[:200]},
    )


def _raise_mapped(exc: LlmError) -> None:
    """把 `request_with_retry` 抛出的 `LlmError` 翻译成本产品的错误码。

    这一步不能省：`LlmError` 继承 `Exception` 而不是 `AppError`，漏翻译的话
    "仓库不存在"会被当成"端点不可达"，更糟的是 `except AppError` 的调用方
    （`repo_service.resolve`）接不住它，于是 `/v1/repos/resolve` 直接 500。
    `PROVIDER_UNAVAILABLE` 带 HTTP 状态时用 `_map_github_error` 的语义映射，
    没有状态（网络/超时）时交给 `_unreachable`。
    """
    if exc.status is None:
        raise _unreachable(exc) from exc
    raise _map_github_error(int(exc.status), exc.message) from exc


def _too_large(measured: int, limit: int) -> AppError:
    mb = 1024 * 1024
    return AppError(
        "REPO_TOO_LARGE",
        f"仓库压缩包实测 {measured / mb:.1f} MB，超过上限 {limit / mb:.0f} MB",
        hint="换一个更轻量的仓库，或调大 .env 里的 REPOLEARN_MAX_REPO_MB",
        details={"measured_bytes": measured, "limit_bytes": limit},
    )


# --------------------------------------------------------------------------- #
# 出站调用（五个站点全部读配置）                                               #
# --------------------------------------------------------------------------- #


async def fetch_repo_meta(ref: RepoRef) -> RepoMeta:
    url = f"{_api()}/repos/{ref.full_name}"
    async with new_client(timeout_read=20.0) as client:
        try:
            resp = await request_with_retry(client, "GET", url, headers=_headers(), attempts=3)
        except AppError:
            raise
        except LlmError as exc:  # 端点回了 4xx/5xx：按语义映射，不要一律报"不可达"
            _raise_mapped(exc)
        except Exception as exc:  # noqa: BLE001 - 端点不可达要给可执行的 hint
            raise _unreachable(exc) from exc
        # `/repos` 正常不重定向，但"正常"不是信任理由：端点由用户配置，能返回任意
        # 跳转。逐跳校验的成本是一行，漏掉的成本是一条 SSRF。
        _check_redirects(resp)
        data = resp.json()
    if not isinstance(data, dict):
        raise AppError("PROVIDER_UNAVAILABLE", "GitHub 返回的不是对象", details={"endpoint": _api()})
    # 出站字段白名单：只取这 10 个，其余（clone_url/archive_url/avatar_url/…）
    # 一律丢弃。多取一个字段就是多一条"前端把它当链接渲染"的潜在注入面。
    lic = data.get("license") or {}
    owner = data.get("owner") or {}
    return RepoMeta(
        full_name=str(data.get("full_name") or ref.full_name),
        owner=str(owner.get("login") or ref.owner) if isinstance(owner, dict) else ref.owner,
        name=str(data.get("name") or ref.name),
        description=str(data["description"]) if data.get("description") is not None else None,
        stars=int(data.get("stargazers_count", 0) or 0),
        license_spdx=lic.get("spdx_id") if isinstance(lic, dict) else None,
        primary_language=str(data["language"]) if data.get("language") is not None else None,
        default_branch=str(data.get("default_branch") or "main"),
        html_url=safe_html_url(data.get("html_url"), full_name=ref.full_name),
        size_kb=int(data.get("size", 0) or 0),
        is_private=bool(data.get("private", False)),
    )


async def resolve_commit(ref: RepoRef, branch: str, wanted_ref: str | None = None) -> CommitMeta:
    """取 HEAD（或指定 ref）的 sha。网络错误退避重试 3 次（spec §3.4 N2）。"""
    target = wanted_ref or branch
    url = f"{_api()}/repos/{ref.full_name}/commits/{target}"
    async with new_client(timeout_read=20.0) as client:
        try:
            resp = await request_with_retry(client, "GET", url, headers=_headers(), attempts=3)
        except AppError:
            raise
        except LlmError as exc:
            _raise_mapped(exc)
        except Exception as exc:  # noqa: BLE001
            raise _unreachable(exc) from exc
        _check_redirects(resp)
        data = resp.json()
    if not isinstance(data, dict):
        raise AppError("PROVIDER_UNAVAILABLE", "Commit 响应不是对象", details={"endpoint": _api()})
    sha = str(data.get("sha") or "")
    if not _SHA_RE.fullmatch(sha):
        # 这个 sha 会成为镜像目录名、缓存键成分与 URL 片段。让它自由通过等于把
        # 路径穿越与缓存投毒的入口交给端点。40 或 64 位小写十六进制之外一律拒绝。
        raise AppError(
            "PROVIDER_UNAVAILABLE",
            "Commit SHA 格式非法",
            hint="端点返回的 sha 不是 40/64 位十六进制；自建镜像需要返回与 GitHub 一致的格式",
            details={"endpoint": _api(), "sha_prefix": sha[:12]},
        )
    commit = data.get("commit") or {}
    author = (commit.get("author") or {}) if isinstance(commit, dict) else {}
    files = data.get("files") or []
    return CommitMeta(
        sha=sha,
        committed_at=author.get("date") if isinstance(author, dict) else None,
        message=str(commit.get("message", ""))[:400] if isinstance(commit, dict) else "",
        file_count=len(files) if isinstance(files, list) else 0,
        # `html_url` 同样要清洗：它可能被前端渲染。
        extra={"html_url": safe_html_url(data.get("html_url"), full_name=ref.full_name)},
    )


async def download_tarball(ref: RepoRef, sha: str, max_bytes: int | None = None) -> bytes:
    """下载 tarball。超限抛 `REPO_TOO_LARGE`。

    三道体积闸：① `Content-Length`（有则必查，避免"先下 500 MB 再告诉用户太大"）；
    ② 流式累计字节（`Content-Length` 可以撒谎或干脆不给）；③ 解包期累计由
    `ingest/tarball.py` 负责（压缩比极高时压缩后体积说明不了展开后的代价）。
    重定向逐跳校验见 `_check_redirects`。
    """
    limit = (max_bytes or settings.max_repo_mb * 1024 * 1024)
    url = f"{_api()}/repos/{ref.full_name}/tarball/{sha}"
    async with new_client(timeout_read=120.0) as client:
        async with client.stream("GET", url, headers=_headers()) as resp:
            if resp.status_code >= 400:
                body = (await resp.aread()).decode("utf-8", "ignore")
                raise _map_github_error(resp.status_code, body)
            _check_redirects(resp)
            declared = resp.headers.get("content-length")
            if declared and declared.isdigit() and int(declared) > limit:
                raise _too_large(int(declared), limit)
            buf = bytearray()
            async for chunk in resp.aiter_bytes():
                buf.extend(chunk)
                if len(buf) > limit:
                    raise _too_large(len(buf), limit)
            return bytes(buf)


async def list_tree(ref: RepoRef, sha: str) -> list[dict]:
    """Git Trees API。tarball 超限时的降级路径：只挑核心文件（spec §3.4 N3）。"""
    url = f"{_api()}/repos/{ref.full_name}/git/trees/{sha}?recursive=1"
    async with new_client(timeout_read=30.0) as client:
        resp = await request_with_retry(client, "GET", url, headers=_headers(), attempts=2)
        _check_redirects(resp)
        data = resp.json()
    out: list[dict] = []
    for item in (data.get("tree") or []) if isinstance(data, dict) else []:
        if not isinstance(item, dict) or item.get("type") != "blob":
            continue
        out.append({"path": item.get("path", ""), "size": int(item.get("size", 0) or 0), "sha": item.get("sha", "")})
    return out


async def fetch_raw_file(ref: RepoRef, sha: str, path: str, max_bytes: int = 512 * 1024) -> str:
    url = f"{_api()}/repos/{ref.full_name}/contents/{path}?ref={sha}"
    headers = {**_headers(), "Accept": "application/vnd.github.raw"}
    async with new_client(timeout_read=30.0) as client:
        resp = await request_with_retry(client, "GET", url, headers=headers, attempts=2)
        _check_redirects(resp)
        return resp.text[:max_bytes]


def rate_limit_hint(remaining: int | None = None) -> str:
    if settings.github_token:
        return f"已配置 GitHub Token，剩余额度 {remaining if remaining is not None else '未知'}；端点 {_api()}"
    return (
        f"未配置 REPOLEARN_GITHUB_TOKEN，端点 {_api()}，限额 60 次/小时；"
        "配置后可提升到 5000 次/小时"
    )

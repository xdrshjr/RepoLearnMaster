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
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
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

#: `/repos` 与 `/commits` 的进程内缓存时长（秒）。
#:
#: 未配置 token 时配额只有 **60 次/小时**，而一次"点生成"就要用掉 `/repos` +
#: `/commits` 两格。用户在 UI 上连点两下、或者首页输入框触发一次 resolve 再点
#: 生成，就会把同一份元数据取两遍——这不是"多花一点配额"，而是把本来就紧张的
#: 60 格按倍数烧掉。60 秒足够覆盖"点开→看一眼→点生成"这个动作，又短到不会
#: 让刚推的新 commit 长期看不见（键里还带着 ref）。
#:
#: 只缓存**成功**结果，且缓存的是已经过白名单清洗的 dataclass——端点返回的
#: 原始 JSON 不会进缓存（否则"三次校验"就只对第一次请求生效）。
CACHE_TTL_SECONDS = 60.0
_CACHE_MAX_ENTRIES = 128
_cache: dict[tuple[str, ...], tuple[float, object]] = {}


def reset_github_cache() -> None:
    """清空缓存。测试要"每次都真打端点"时用它（或把 `CACHE_TTL_SECONDS` 置 0）。"""
    _cache.clear()


def _cache_get(key: tuple[str, ...]):
    entry = _cache.get(key)
    if entry is None:
        return None
    expires_at, value = entry
    if expires_at <= time.monotonic():
        _cache.pop(key, None)
        return None
    log.info("github_cache_hit", key="/".join(key))
    return value


def _cache_put(key: tuple[str, ...], value) -> None:
    ttl = float(CACHE_TTL_SECONDS)
    if ttl <= 0:
        return
    if len(_cache) >= _CACHE_MAX_ENTRIES:
        now = time.monotonic()
        for stale in [k for k, (exp, _) in _cache.items() if exp <= now]:
            _cache.pop(stale, None)
        if len(_cache) >= _CACHE_MAX_ENTRIES:
            # 上限是"别让它无界增长"的护栏，不是 LRU 实现：满了直接清空，
            # 代价只是下一轮重新取一次。
            _cache.clear()
    _cache[key] = (time.monotonic() + ttl, value)


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


def _map_github_error(status: int, body: str, headers=None) -> AppError:
    """HTTP 状态 + **响应头** → 本产品的错误码。

    v1 只看 body 里有没有 "rate limit"，于是三件事都错了：
    * 401 `Bad credentials`（token 过期/写错）被报成"无权访问该仓库"，用户去查仓库权限；
    * 403 私有仓库与 403 限流都落在同一个 `REPO_FORBIDDEN`；
    * 限流只说"稍后重试"，不说**还剩多少额度、几点重置**——而这两个数字就在
      `X-RateLimit-Remaining` / `X-RateLimit-Reset` 里，不说等于让用户自己猜。
    """
    info = _rate_info(headers)
    text = (body or "").lower()
    if _looks_rate_limited(status, text, info):
        return AppError(
            "RATE_LIMITED",
            "GitHub 接口限流",
            hint=_rate_limit_hint(info),
            details={"status": status, "endpoint": _api(), **_rate_details(info)},
        )
    if status == 404:
        return AppError("REPO_NOT_FOUND", details={"status": status, "endpoint": _api()})
    if status == 401 or (status == 403 and any(m in text for m in _AUTH_MARKERS)):
        return AppError(
            "INVALID_KEY",
            "GitHub Token 无效或已过期",
            hint=(
                "检查 .env 里的 REPOLEARN_GITHUB_TOKEN 是否被撤销/复制时多了空格/已过期，"
                "改完必须重启 API；也可以先把这一行留空（未认证 60 次/小时）确认是不是 token 本身的问题"
            ),
            details={"status": status, "endpoint": _api()},
        )
    if status == 403:
        return AppError("REPO_FORBIDDEN", details={"status": status, "endpoint": _api()})
    return AppError("PROVIDER_UNAVAILABLE", f"GitHub 返回 {status}", details={"body": body[:200], "endpoint": _api()})


# --------------------------------------------------------------------------- #
# 限流响应头 → 一句可执行的话                                                  #
# --------------------------------------------------------------------------- #

#: GitHub 限流的两种形态：primary（配额耗尽，403 + `X-RateLimit-Remaining: 0`）
#: 与 secondary（突发流量，429 或 403 + `Retry-After`）。两种都要能被认出来。
_RATE_LIMIT_MARKERS = ("rate limit", "ratelimit", "abuse detection", "too many requests")
#: token 本身有问题时 GitHub 的措辞（**不是**权限不足，别混为一谈）。
_AUTH_MARKERS = ("bad credentials", "requires authentication", "invalid token", "unauthorized")


@dataclass(frozen=True)
class RateInfo:
    limit: int | None = None
    remaining: int | None = None
    reset_at: datetime | None = None
    retry_after: float | None = None


def _int_header(headers, name: str) -> int | None:
    try:
        raw = headers.get(name) if headers else None
    except Exception:  # noqa: BLE001 - 头部不可枚举不该让错误处理本身失败
        return None
    if raw is None or str(raw).strip() == "":
        return None
    try:
        return int(str(raw).strip())
    except (TypeError, ValueError):
        return None


def _rate_info(headers) -> RateInfo:
    """从响应头读 GitHub 的配额事实。读不到就返回全 None（不猜）。"""
    reset_raw = _int_header(headers, "x-ratelimit-reset")
    reset_at = None
    if reset_raw is not None:
        try:
            reset_at = datetime.fromtimestamp(reset_raw, tz=UTC).astimezone()
        except (OverflowError, OSError, ValueError):
            reset_at = None
    retry_after = None
    try:
        raw_retry = headers.get("retry-after") if headers else None
    except Exception:  # noqa: BLE001
        raw_retry = None
    if raw_retry not in (None, ""):
        try:
            retry_after = float(str(raw_retry).strip())
        except (TypeError, ValueError):
            retry_after = None
    return RateInfo(
        limit=_int_header(headers, "x-ratelimit-limit"),
        remaining=_int_header(headers, "x-ratelimit-remaining"),
        reset_at=reset_at,
        retry_after=retry_after,
    )


def _looks_rate_limited(status: int, text: str, info: RateInfo) -> bool:
    """判断这个失败是不是限流。

    三个依据，任意一个成立即可：状态 429；`X-RateLimit-Remaining: 0`；body 里
    出现限流措辞。只看 body 是不够的——自建 GHE/镜像的 body 可以是任意文案，
    而 `Remaining: 0` 是结构化的、不会说谎。
    """
    if status not in (403, 429):
        return False
    if status == 429:
        return True
    if info.remaining == 0:
        return True
    return any(marker in (text or "") for marker in _RATE_LIMIT_MARKERS)


def _when_retryable(info: RateInfo) -> str:
    """把"什么时候能重试"变成一句人话；没有依据时**明确说没有**。"""
    if info.retry_after is not None:
        return f"{max(int(round(info.retry_after)), 1)} 秒后"
    if info.reset_at is not None:
        wait_min = max(int((info.reset_at - datetime.now(tz=info.reset_at.tzinfo)).total_seconds() // 60), 1)
        return f"{info.reset_at:%H:%M} 之后（约 {wait_min} 分钟后）"
    return ""


def _rate_details(info: RateInfo) -> dict:
    return {
        "rate_limit": info.limit,
        "rate_remaining": info.remaining,
        "rate_reset_at": info.reset_at.isoformat() if info.reset_at else None,
        "retry_after_s": info.retry_after,
        "token_configured": bool(settings.github_token),
    }


def _rate_limit_hint(info: RateInfo) -> str:
    """限流提示的**唯一**来源（错误响应、doctor、日志都走它，避免三处各说一套）。"""
    parts: list[str] = []
    if settings.github_token:
        parts.append("已配置 REPOLEARN_GITHUB_TOKEN（上限 5000 次/小时）")
    else:
        parts.append("未配置 REPOLEARN_GITHUB_TOKEN（未认证上限 60 次/小时）")
    if info.remaining is not None and info.limit is not None:
        parts.append(f"剩余 {info.remaining}/{info.limit}")
    elif info.remaining is not None:
        parts.append(f"剩余 {info.remaining}")
    when = _when_retryable(info)
    if when:
        parts.append(f"{when}可重试")
    else:
        parts.append("重置时间未在响应头中给出，可到 https://api.github.com/rate_limit 查询")
    parts.append(f"端点 {_api()}")
    if not settings.github_token:
        parts.append("在 .env 填 REPOLEARN_GITHUB_TOKEN 后重启 API 可提升到 5000 次/小时")
    return "；".join(parts)


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
    # 头部要一起传：限流的"还剩多少、几点重置"只在响应头里。
    raise _map_github_error(int(exc.status), exc.message, getattr(exc, "headers", None)) from exc


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


async def _get_json(url: str, *, headers: dict[str, str], attempts: int, timeout_read: float):
    """GET 一次 JSON，并把三类失败翻译成本产品错误码。

    抽出来的唯一理由：`list_tree` / `fetch_raw_file` v1 漏了这段翻译，于是端点
    回 403 时 `LlmError` 一路穿到 API 层变成 **500 INTERNAL**——用户看到"服务内部
    错误，可重试"，而真实原因是限流或 token 无效（github.py 自己的 docstring
    早就记过这个坑，只是当时只修了两个函数）。
    """
    async with new_client(timeout_read=timeout_read) as client:
        try:
            resp = await request_with_retry(client, "GET", url, headers=headers, attempts=attempts)
        except AppError:
            raise
        except LlmError as exc:  # 端点回了 4xx/5xx：按语义映射，不要一律报"不可达"
            _raise_mapped(exc)
        except Exception as exc:  # noqa: BLE001 - 端点不可达要给可执行的 hint
            raise _unreachable(exc) from exc
        # 正常不重定向，但"正常"不是信任理由：端点由用户配置，能返回任意跳转。
        # 逐跳校验的成本是一行，漏掉的成本是一条 SSRF。
        _check_redirects(resp)
        return resp


async def fetch_repo_meta(ref: RepoRef) -> RepoMeta:
    key = ("meta", ref.full_name)
    cached = _cache_get(key)
    if isinstance(cached, RepoMeta):
        return cached
    resp = await _get_json(
        f"{_api()}/repos/{ref.full_name}", headers=_headers(), attempts=3, timeout_read=20.0
    )
    data = resp.json()
    if not isinstance(data, dict):
        raise AppError("PROVIDER_UNAVAILABLE", "GitHub 返回的不是对象", details={"endpoint": _api()})
    # 出站字段白名单：只取这 10 个，其余（clone_url/archive_url/avatar_url/…）
    # 一律丢弃。多取一个字段就是多一条"前端把它当链接渲染"的潜在注入面。
    lic = data.get("license") or {}
    owner = data.get("owner") or {}
    meta = RepoMeta(
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
    _cache_put(key, meta)
    return meta


async def resolve_commit(ref: RepoRef, branch: str, wanted_ref: str | None = None) -> CommitMeta:
    """取 HEAD（或指定 ref）的 sha。网络错误退避重试 3 次（spec §3.4 N2）。"""
    target = wanted_ref or branch
    key = ("commit", ref.full_name, target)
    cached = _cache_get(key)
    if isinstance(cached, CommitMeta):
        return cached
    resp = await _get_json(
        f"{_api()}/repos/{ref.full_name}/commits/{target}",
        headers=_headers(),
        attempts=3,
        timeout_read=20.0,
    )
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
    out = CommitMeta(
        sha=sha,
        committed_at=author.get("date") if isinstance(author, dict) else None,
        message=str(commit.get("message", ""))[:400] if isinstance(commit, dict) else "",
        file_count=len(files) if isinstance(files, list) else 0,
        # `html_url` 同样要清洗：它可能被前端渲染。
        extra={"html_url": safe_html_url(data.get("html_url"), full_name=ref.full_name)},
    )
    _cache_put(key, out)
    return out


async def download_tarball(ref: RepoRef, sha: str, max_bytes: int | None = None) -> bytes:
    """下载 tarball。超限抛 `REPO_TOO_LARGE`。

    三道体积闸：① `Content-Length`（有则必查，避免"先下 500 MB 再告诉用户太大"）；
    ② 流式累计字节（`Content-Length` 可以撒谎或干脆不给）；③ 解包期累计由
    `ingest/tarball.py` 负责（压缩比极高时压缩后体积说明不了展开后的代价）。
    重定向逐跳校验见 `_check_redirects`。

    tarball **不进缓存**：它可能有几十 MB，而缓存的目的是省配额（tarball 走
    `api.github.com` 的 tarball 端点，不占 API 配额的那部分是 codeload 的重定向），
    把大对象塞进进程内存换来的是内存风险而不是配额收益。
    """
    limit = (max_bytes or settings.max_repo_mb * 1024 * 1024)
    url = f"{_api()}/repos/{ref.full_name}/tarball/{sha}"
    async with new_client(timeout_read=120.0) as client:
        async with client.stream("GET", url, headers=_headers()) as resp:
            if resp.status_code >= 400:
                body = (await resp.aread()).decode("utf-8", "ignore")
                # 头部要传：限流的"剩余额度/重置时间"只在头里。
                raise _map_github_error(resp.status_code, body, resp.headers)
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
    resp = await _get_json(
        f"{_api()}/repos/{ref.full_name}/git/trees/{sha}?recursive=1",
        headers=_headers(),
        attempts=2,
        timeout_read=30.0,
    )
    data = resp.json()
    out: list[dict] = []
    for item in (data.get("tree") or []) if isinstance(data, dict) else []:
        if not isinstance(item, dict) or item.get("type") != "blob":
            continue
        out.append({"path": item.get("path", ""), "size": int(item.get("size", 0) or 0), "sha": item.get("sha", "")})
    return out


async def fetch_raw_file(ref: RepoRef, sha: str, path: str, max_bytes: int = 512 * 1024) -> str:
    resp = await _get_json(
        f"{_api()}/repos/{ref.full_name}/contents/{path}?ref={sha}",
        headers={**_headers(), "Accept": "application/vnd.github.raw"},
        attempts=2,
        timeout_read=30.0,
    )
    return resp.text[:max_bytes]


def rate_limit_hint(remaining: int | None = None) -> str:
    """限流提示（不带响应头时的形态）。

    带响应头的路径走 `_rate_limit_hint(RateInfo)`——那里能说出"剩余 N/M、几点重置"。
    这个函数保留给 doctor / 日志这类拿不到响应的地方。
    """
    return _rate_limit_hint(RateInfo(limit=None, remaining=remaining))


def token_diagnostics() -> dict:
    """`REPOLEARN_GITHUB_TOKEN` 的**可公开**诊断信息（doctor 用）。

    只放指纹（前 4 + 后 4）与长度，不放明文：这块信息要显示在一个
    "我到底读到的是哪一个 token"的排查面板上，而那个面板的截图经常被贴进
    issue。

    `padded=True` 是一个真实存在的故障：`REPOLEARN_GITHUB_TOKEN= ghp_xxx`
    （等号后多一个空格）能通过 dotenv 解析，于是 GitHub 收到
    `Authorization: Bearer  ghp_xxx` 并回 401 `Bad credentials`——用户看到的
    是"token 无效"，而 token 本身是好的。这里把它指出来。
    """
    raw = settings.github_token or ""
    token = raw.strip()
    if not token:
        return {"configured": False, "fingerprint": None, "padded": False, "length": 0}
    if len(token) <= 12:
        fingerprint = f"{token[:2]}…{token[-2:]}"
    else:
        fingerprint = f"{token[:4]}…{token[-4:]}"
    return {
        "configured": True,
        "fingerprint": fingerprint,
        "padded": raw != token,
        "length": len(token),
    }

"""本机已登录凭据的发现链（解决"未认证 60 次/小时"）。

## 为什么需要这个模块

GitHub 对未认证调用的上限是 **60 次/小时/IP**，这是服务端硬规则，代码提高不了。
而一台开发机**很可能早就登录过 GitHub**：`gh auth login` 存过 OAuth token，
Git Credential Manager 存过 HTTPS 密码（其实就是 PAT）。产品此前只认 `.env`，
于是用户面前只剩"配 token → 重启 API → 导入"这一条路，而实际故障现场是：

    RATE_LIMITED  未配置 REPOLEARN_GITHUB_TOKEN（未认证上限 60 次/小时）；剩余 0/60

屏幕上的建议全都对，但它没有回答"我机器上明明登录了 GitHub，为什么还要我再配一次"。
这个模块就是那个回答：**有现成的就用现成的**。

## 优先级（先命中先用）

1. `REPOLEARN_GITHUB_TOKEN`（`.env`）——显式配置永远最高优先，可覆盖任何自动发现
2. `GH_TOKEN` / `GITHUB_TOKEN` 环境变量——CI 与 GitHub Actions 的惯例
3. `gh auth token`——GitHub CLI 已登录
4. `git credential fill`——Git Credential Manager / 系统钥匙串（Windows 上装了 Git 通常就有）
5. `gh` 的 `hosts.yml`——CLI 存在但不在 PATH 上的情况
6. `~/.git-credentials`——`credential.helper=store` 的明文凭据

## 三条硬规则

* **只对官方 api.github.com 生效**。自建 GHE / 本地假端点的 host 不在白名单里时直接
  跳过：把自己 github.com 的 token 发给一个用户可配置的端点，是一次凭据外泄
  （这与 `parse_repo_url` 的 SSRF 红线是同一条思路）。
* **绝不交互**。`git credential fill` 在缺少凭据时会调 Git Credential Manager，
  而 GCM 会**弹窗**——在 API 进程里弹窗等于把整个进程挂死。因此固定传
  `GIT_TERMINAL_PROMPT=0` / `GCM_INTERACTIVE=never` / `GIT_ASKPASS=echo`，
  并给每次调用 5 秒超时，失败一律当作"没有 token"（fail-closed）。
* **绝不明文外泄**。token 只活在内存里；日志与 doctor 只拿得到"来源 + 指纹"
  （`ghp_…6789`）。`_looks_like_token` 存在的另一个理由是：`git credential fill`
  在参数不对时会往 stdout 打一段 usage 文本，不做形状校验的话，那段中文/英文说明
  就会被当成 Bearer token 发出去——症状是"突然 401，而我什么都没改"。
"""

from __future__ import annotations

import asyncio
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse

from repolearn.core.logging import get_logger

log = get_logger("github_auth")

#: 单次探测的超时（秒）。超过就当这个来源不存在：宁可退回 60 次/小时，也不要
#: 让一次导入在"读钥匙串"上卡半分钟。
PROBE_TIMEOUT_S = 5.0

#: 官方站点的 host。只有指向它时才允许把本机凭据发出去。
OFFICIAL_API_HOST = "api.github.com"
OFFICIAL_WEB_HOST = "github.com"

#: token 的形状。GitHub 的几种前缀（ghp_/gho_/ghu_/ghs_/ghr_/github_pat_）+ 老式
#: 40 位十六进制；这里只做"看起来像凭据"的粗校验，真正的裁决权在 GitHub（它会回 401）。
_TOKEN_RE = re.compile(r"^(?:gh[pousr]_[A-Za-z0-9]{16,}|github_pat_[A-Za-z0-9_]{20,}|[0-9a-f]{40})$")

#: 子进程环境的"绝不交互"三件套。缺一个都可能弹窗。
_NONINTERACTIVE_ENV = {
    "GIT_TERMINAL_PROMPT": "0",
    "GIT_ASKPASS": "echo",
    "GCM_INTERACTIVE": "never",
    "SSH_ASKPASS": "echo",
    "GH_PROMPT_DISABLED": "1",
    "GH_NO_UPDATE_NOTIFIER": "1",
}


@dataclass(frozen=True)
class TokenSource:
    """一次发现的结果。

    `tried` 是**给用户看的**：全都失败时，`未配置 token` 这句话本身没有信息量，
    "已尝试 .env / GH_TOKEN / gh CLI / Git Credential Manager / hosts.yml / .git-credentials"
    才能让人知道下一步该修哪一环。
    """

    token: str = ""
    source: str = "none"
    tried: tuple[str, ...] = field(default_factory=tuple)
    skipped_reason: str = ""

    @property
    def configured(self) -> bool:
        return bool(self.token)

    def fingerprint(self) -> str | None:
        """前 4 + 后 4。短到不可能是凭据，长到足以分辨"我读到的是哪一个"。"""
        if not self.token:
            return None
        if len(self.token) <= 12:
            return f"{self.token[:2]}…{self.token[-2:]}"
        return f"{self.token[:4]}…{self.token[-4:]}"


_state: TokenSource | None = None
#: 缓存键：显式 token + 端点 + 开关 + 环境。任何一个变了，缓存立刻作废。
#:
#: 没有这条，`token_diagnostics()` 会返回"改配置之前"的结论——症状是 doctor 面板
#: 说"已配置"，而实际请求已经换了端点；或者反过来，你在 .env 里填了 token 重启
#: 之前的进程却仍说没有。缓存是为了省子进程，不是为了忽略配置。
_state_key: tuple[str, str, str, bool, str] | None = None


def _current_key() -> tuple[str, str, str, bool, str]:
    from repolearn.core.config import settings

    return (
        (settings.github_token or "").strip(),
        settings.github_api,
        settings.github_web,
        bool(getattr(settings, "github_token_autodiscover", True)),
        str(settings.env).lower(),
    )


def reset_token_cache() -> None:
    """清缓存（测试与 `cli github-token --refresh` 用）。"""
    global _state, _state_key
    _state = None
    _state_key = None


def _looks_like_token(value: str) -> bool:
    return bool(_TOKEN_RE.match((value or "").strip()))


def _run(argv: list[str], *, stdin: str = "") -> str:
    """跑一个短命令并返回 stdout；任何失败都返回空串。

    不用 `shell=True`：这些命令的参数是固定的，shell 只会多一条注入面。
    """
    exe = shutil.which(argv[0])
    if exe is None:
        return ""
    env = {**os.environ, **_NONINTERACTIVE_ENV}
    try:
        proc = subprocess.run(  # noqa: S603 - 固定参数、无 shell、有超时
            [exe, *argv[1:]],
            input=stdin,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=PROBE_TIMEOUT_S,
            env=env,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        log.info("github_token_probe_failed", source=argv[0], error=str(exc)[:160])
        return ""
    if proc.returncode != 0:
        log.info("github_token_probe_nonzero", source=argv[0], code=proc.returncode)
        return ""
    return (proc.stdout or "").strip()


def _from_env_names() -> tuple[str, str]:
    for name in ("GH_TOKEN", "GITHUB_TOKEN"):
        value = (os.environ.get(name) or "").strip()
        if _looks_like_token(value):
            return value, f"env:{name}"
    return "", ""


def _from_gh_cli() -> tuple[str, str]:
    value = _run(["gh", "auth", "token"]).strip().splitlines()
    candidate = (value[0] if value else "").strip()
    return (candidate, "gh-cli") if _looks_like_token(candidate) else ("", "")


def _from_git_credential(host: str) -> tuple[str, str]:
    """问 Git Credential Manager 要密码。

    真实机器上 `git credential fill` 回答的 `password=` 就是 PAT（GCM 把 token
    存在 Windows 凭据管理器里）。`username=` 可能是 `x-access-token` 或用户名，
    与认证无关，我们只要 password。
    """
    out = _run(["git", "credential", "fill"], stdin=f"protocol=https\nhost={host}\n\n")
    for line in out.splitlines():
        key, _, value = line.partition("=")
        if key.strip() == "password":
            candidate = value.strip()
            if _looks_like_token(candidate):
                return candidate, "git-credential"
    return "", ""


def _gh_hosts_files() -> list[Path]:
    files: list[Path] = []
    appdata = os.environ.get("APPDATA")
    if appdata:
        files.append(Path(appdata) / "GitHub CLI" / "hosts.yml")
    xdg = os.environ.get("XDG_CONFIG_HOME")
    if xdg:
        files.append(Path(xdg) / "gh" / "hosts.yml")
    files.append(Path.home() / ".config" / "gh" / "hosts.yml")
    return files


def _from_gh_hosts(host: str) -> tuple[str, str]:
    """从 `gh` 的 hosts.yml 里抠 token。

    不引入 yaml 依赖：这个文件的结构是固定缩进的键值对（`github.com:` 下若干行，
    其中一行 `oauth_token: gho_...`），用两行正则比多一个依赖更划算，且失败时
    只是"没找到"而不是抛异常。
    """
    for path in _gh_hosts_files():
        try:
            if not path.is_file():
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        current_host = ""
        for line in text.splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            if not line.startswith((" ", "\t")) and stripped.endswith(":"):
                current_host = stripped[:-1]
                continue
            if current_host == host and stripped.startswith("oauth_token:"):
                candidate = stripped.split(":", 1)[1].strip().strip("'\"")
                if _looks_like_token(candidate):
                    return candidate, "gh-hosts"
    return "", ""


def _from_git_credentials_file(host: str) -> tuple[str, str]:
    path = Path.home() / ".git-credentials"
    try:
        if not path.is_file():
            return "", ""
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return "", ""
    for line in text.splitlines():
        parsed = urlparse(line.strip())
        if parsed.hostname != host or not parsed.password:
            continue
        candidate = parsed.password.strip()
        if _looks_like_token(candidate):
            return candidate, "git-credentials-file"
    return "", ""


def _endpoint_allows_local_credentials() -> tuple[bool, str]:
    """当前端点是否是官方 GitHub（只有它是安全的收件人）。"""
    from repolearn.core.config import settings

    api_host = (urlparse(settings.github_api).hostname or "").lower()
    web_host = (urlparse(settings.github_web).hostname or "").lower()
    if api_host != OFFICIAL_API_HOST or web_host != OFFICIAL_WEB_HOST:
        return False, f"端点 {api_host or '?'} 不是官方 GitHub，已跳过本机凭据发现（避免把 github.com 的 token 发给自定义端点）"
    if not getattr(settings, "github_token_autodiscover", True):
        return False, "REPOLEARN_GITHUB_TOKEN_AUTODISCOVER=0，已跳过本机凭据发现"
    if str(settings.env).lower() == "test":
        # 测试必须确定性：否则在开发机上跑测试会真的去读钥匙串。
        return False, "REPOLEARN_ENV=test，已跳过本机凭据发现"
    return True, ""


def resolve_token(force: bool = False) -> TokenSource:
    """按优先级找 token（结果缓存；`force=True` 重新探测）。"""
    global _state, _state_key

    key = _current_key()
    if _state is not None and not force and _state_key == key:
        return _state
    _state_key = key

    from repolearn.core.config import settings

    tried: list[str] = []

    explicit = (settings.github_token or "").strip()
    tried.append("REPOLEARN_GITHUB_TOKEN")
    if explicit:
        _state = TokenSource(token=explicit, source=".env", tried=tuple(tried))
        return _state

    allowed, reason = _endpoint_allows_local_credentials()
    if not allowed:
        _state = TokenSource(tried=tuple(tried), skipped_reason=reason)
        log.info("github_token_discovery_skipped", reason=reason)
        return _state

    for name, probe in (
        ("GH_TOKEN/GITHUB_TOKEN", _from_env_names),
        ("gh auth token", _from_gh_cli),
        ("git credential fill", lambda: _from_git_credential(OFFICIAL_WEB_HOST)),
        ("gh hosts.yml", lambda: _from_gh_hosts(OFFICIAL_WEB_HOST)),
        ("~/.git-credentials", lambda: _from_git_credentials_file(OFFICIAL_WEB_HOST)),
    ):
        tried.append(name)
        try:
            token, source = probe()
        except Exception as exc:  # noqa: BLE001 - 发现链任何一环失败都不该影响主流程
            log.info("github_token_source_error", source=name, error=str(exc)[:160])
            continue
        if token:
            _state = TokenSource(token=token, source=source, tried=tuple(tried))
            # 只记来源，不记值。
            log.info("github_token_source", source=source)
            return _state

    _state = TokenSource(tried=tuple(tried))
    log.warning("github_token_not_found", tried=", ".join(tried))
    return _state


async def warm_up_token() -> TokenSource:
    """启动时预热一次：把子进程挪到线程里，避免阻塞事件循环。"""
    return await asyncio.to_thread(resolve_token)


def describe_failure(source: TokenSource) -> str:
    """给 error hint / doctor 用的一句话：为什么没有 token，试过什么。"""
    if source.skipped_reason:
        return source.skipped_reason
    return "已尝试：" + "、".join(source.tried)


def _which(name: str) -> str:
    return shutil.which(name) or ""


def local_tooling() -> dict[str, str]:
    """本机装了哪些可被发现的凭据来源（doctor 展示"该怎么修"时用到）。"""
    return {
        "gh": _which("gh"),
        "git": _which("git"),
        "platform": sys.platform,
    }

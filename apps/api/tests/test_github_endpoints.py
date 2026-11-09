"""GitHub 接入点与**不可信端点**的防护（hardening spec §7.2：T-GH-1..6）。

这一组用例守的是 P0-3：允许用户把端点指向自建 GHE，等于允许一个"会返回任意 JSON
的服务器"参与产品链路。三条攻击面必须在**允许自定义端点的同时**就修掉，不能推到
"以后加固"——一旦上线了可配置端点却没有清洗，等于把 XSS 直接发给用户：

* 端点返回 `html_url: "javascript:alert(1)"` → 存储型 XSS（它会被渲染成 `<a href>`）；
* tarball 302 到内网地址 → 通过重定向绕过 host 白名单的 SSRF；
* 端点声称 1KB、实际发 2× 上限的字节 → 磁盘写满。

`T-GH-1..3` 是"配置真的生效"，`T-GH-4..6` 是"端点的返回值不被信任"。
"""

from __future__ import annotations

import io
import tarfile
import time

import httpx
import pytest
import respx

from repolearn.core.config import settings
from repolearn.core.errors import AppError
from repolearn.ingest import github as gh
from repolearn.ingest.tarball import extract_tarball

BASE = "http://127.0.0.1:9911"


@pytest.fixture(autouse=True)
def _no_cached_github_calls():
    """每个用例都从空缓存开始。

    `fetch_repo_meta` / `resolve_commit` 有 60 秒进程内缓存（省 60 次/小时的配额），
    而测试里"同一个 owner/repo"会在多条用例间重复出现。不清缓存的话，第二条
    用例会拿到第一条的响应——症状是"mock 明明设好了却没被调用"，最难查的那种。

    凭据解析也有一层缓存（`github_auth._state`）：不清的话，改过
    `settings.github_token` 之后 `token_diagnostics()` 仍然会返回上一个用例的结果。
    """
    from repolearn.ingest.github_auth import reset_token_cache

    gh.reset_github_cache()
    reset_token_cache()
    yield
    gh.reset_github_cache()
    reset_token_cache()


@pytest.fixture()
def configured(monkeypatch):
    """把两个 base 指到假端点（配置层，不 patch 请求函数本身）。"""
    monkeypatch.setattr(settings, "github_api_base", BASE)
    monkeypatch.setattr(settings, "github_web_base", BASE)
    return settings


def _tarball(files: dict[str, bytes], prefix: str = "o-r-sha") -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for name, data in files.items():
            info = tarfile.TarInfo(f"{prefix}/{name}")
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return buf.getvalue()


# --------------------------------------------------------------------------- #
# T-GH-1 / 2 / 3                                                              #
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_all_outbound_calls_use_configured_base(configured):
    """T-GH-1：五个出站函数都打到配置的端点。任何一个写死常量都会让 CI 变成网络依赖。"""
    tarball = _tarball({"a.py": b"print(1)\n"})
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        path = request.url.path
        if path.endswith("/tarball/" + "a" * 64):
            return httpx.Response(200, content=tarball)
        if "/commits/" in path:
            return httpx.Response(200, json={"sha": "a" * 64, "commit": {"author": {"date": "2026-01-01T00:00:00Z"}}})
        if "/git/trees/" in path:
            return httpx.Response(200, json={"tree": [{"path": "a.py", "type": "blob", "size": 9, "sha": "b"}]})
        if "/contents/" in path:
            return httpx.Response(200, text="print(1)\n")
        return httpx.Response(
            200,
            json={
                "full_name": "o/r",
                "default_branch": "main",
                "html_url": f"{BASE}/o/r",
                "size": 1,
                "stargazers_count": 3,
            },
        )

    with respx.mock(assert_all_called=False) as mock:
        mock.route(url__startswith=BASE).mock(side_effect=handler)
        ref = gh.parse_repo_url(f"{BASE}/o/r")
        meta = await gh.fetch_repo_meta(ref)
        commit = await gh.resolve_commit(ref, "main")
        data = await gh.download_tarball(ref, commit.sha)
        tree = await gh.list_tree(ref, commit.sha)
        text = await gh.fetch_raw_file(ref, commit.sha, "a.py")

    assert meta.full_name == "o/r"
    assert commit.sha == "a" * 64
    assert data and tree and text
    assert len(seen) == 5
    for url in seen:
        assert url.startswith(BASE), url


def test_parse_repo_url_accepts_configured_host(configured):
    """T-GH-2（前半）：配置的 host 可以被解析；官方 host 也仍然可用。"""
    assert gh.parse_repo_url(f"{BASE}/owner/repo").full_name == "owner/repo"
    assert gh.parse_repo_url("https://github.com/owner/repo").full_name == "owner/repo"


def test_parse_repo_url_rejects_unknown_host(configured):
    """T-GH-2（后半）：任意 host 都放行就是 SSRF 的前兆。"""
    with pytest.raises(AppError) as exc:
        gh.parse_repo_url("https://evil.example/owner/repo")
    assert exc.value.code == "REPO_NOT_FOUND"
    assert "REPOLEARN_GITHUB_WEB_BASE" in (exc.value.hint or "")


def test_rate_limit_error_mentions_endpoint(configured):
    """T-GH-3：限流提示里必须能看到"到底打的是哪个端点"。"""
    hint = gh.rate_limit_hint()
    assert BASE in hint
    err = gh._map_github_error(403, "API rate limit exceeded")
    assert err.code == "RATE_LIMITED"
    assert BASE in (err.hint or "")


# --------------------------------------------------------------------------- #
# T-GH-7..12：限流的**结构化**事实（响应头），不是 body 文案                 #
# --------------------------------------------------------------------------- #


def _rate_headers(*, remaining: str = "0", limit: str = "60", reset_in: int = 900, retry_after: str | None = None):
    headers = {
        "x-ratelimit-limit": limit,
        "x-ratelimit-remaining": remaining,
        "x-ratelimit-reset": str(int(time.time()) + reset_in),
    }
    if retry_after is not None:
        headers["retry-after"] = retry_after
    return headers


def test_rate_limit_hint_reports_remaining_and_reset(configured):
    """T-GH-7：403 + `X-RateLimit-*` → RATE_LIMITED，且 hint 说出剩余额度与重置时间。

    这是用户实际遇到的那个报错：`GET /repos/{owner}/{repo}` 回
    `403 rate limit exceeded`。v1 的提示只说"配置 token"，不说"60 格已经用光、
    14:05 之后才恢复"，于是用户唯一能做的就是反复重试。
    """
    err = gh._map_github_error(403, "API rate limit exceeded", _rate_headers())
    assert err.code == "RATE_LIMITED"
    assert err.retryable is True
    assert err.status == 429
    hint = err.hint or ""
    assert "剩余 0/60" in hint, hint
    assert "可重试" in hint, hint
    assert BASE in hint, hint
    # 结构化字段进 details，前端/日志不必再解析中文提示
    assert err.details["rate_remaining"] == 0
    assert err.details["rate_limit"] == 60
    assert err.details["rate_reset_at"]


def test_secondary_rate_limit_uses_retry_after(configured):
    """T-GH-8：`Retry-After` 优先于 `X-RateLimit-Reset`（secondary limit 的形态）。"""
    err = gh._map_github_error(429, "You have exceeded a secondary rate limit", _rate_headers(retry_after="42"))
    assert err.code == "RATE_LIMITED"
    assert "42 秒后" in (err.hint or ""), err.hint
    assert err.details["retry_after_s"] == 42.0


def test_bad_credentials_maps_to_invalid_key(configured):
    """T-GH-9：401 → INVALID_KEY（"token 无效"），**不是** REPO_FORBIDDEN（"仓库私有"）。

    这两件事的下一步动作完全不同：前者去改 .env，后者去换仓库。混成一个码，
    用户就只能两件事都试一遍。
    """
    err = gh._map_github_error(401, '{"message":"Bad credentials"}')
    assert err.code == "INVALID_KEY"
    assert err.status == 401
    assert "REPOLEARN_GITHUB_TOKEN" in (err.hint or "")
    # 403 上的 bad credentials 同样按鉴权失败处理（GitHub 两种状态都用过）
    assert gh._map_github_error(403, "Bad credentials").code == "INVALID_KEY"


def test_plain_forbidden_stays_repo_forbidden(configured):
    """T-GH-10：既不是限流也不是鉴权失败的 403 仍然走 REPO_FORBIDDEN。"""
    err = gh._map_github_error(403, '{"message":"Forbidden"}')
    assert err.code == "REPO_FORBIDDEN"


@pytest.mark.asyncio
async def test_raw_file_and_tree_translate_errors(configured):
    """T-GH-11：`list_tree` / `fetch_raw_file` 必须抛 AppError，不能漏出 LlmError。

    漏了翻译的后果不是"错误码不好看"：`LlmError` 继承 `Exception` 而不是 `AppError`，
    路由层的 `except AppError` 接不住它，于是限流变成 **500 INTERNAL「服务内部错误，
    可重试」**——用户按提示重试，继续 500。
    """
    ref = gh.parse_repo_url(f"{BASE}/o/r")
    with respx.mock(assert_all_called=False) as mock:
        mock.route(url__startswith=BASE).mock(
            return_value=httpx.Response(
                403, json={"message": "API rate limit exceeded"}, headers=_rate_headers()
            )
        )
        with pytest.raises(AppError) as tree_exc:
            await gh.list_tree(ref, "a" * 40)
        with pytest.raises(AppError) as raw_exc:
            await gh.fetch_raw_file(ref, "a" * 40, "a.py")
        with pytest.raises(AppError) as tarball_exc:
            await gh.download_tarball(ref, "a" * 40)
    for exc in (tree_exc, raw_exc, tarball_exc):
        assert exc.value.code == "RATE_LIMITED"
        assert "剩余 0/60" in (exc.value.hint or "")


@pytest.mark.asyncio
async def test_exhausted_quota_is_not_retried(configured):
    """T-GH-12：`X-RateLimit-Remaining: 0` 时不做退避重试。

    重试只会在同一格配额上再撞一次 403，代价是用户多等 1~3 秒才看到同一句话；
    而 `request_with_retry` 的 `attempts=3` 会让"点一次生成"变成 3 次请求。
    """
    seen = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal seen
        seen += 1
        return httpx.Response(429, json={"message": "API rate limit exceeded"}, headers=_rate_headers())

    with respx.mock(assert_all_called=False) as mock:
        mock.route(url__startswith=BASE).mock(side_effect=handler)
        with pytest.raises(AppError):
            await gh.fetch_repo_meta(gh.parse_repo_url(f"{BASE}/o/r"))
    assert seen == 1, seen


# --------------------------------------------------------------------------- #
# T-GH-13/14：60 秒缓存（省配额）                                              #
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_meta_and_commit_are_cached(configured):
    """T-GH-13：同一仓库 60 秒内只打一次 `/repos`、一次 `/commits`。

    未配置 token 时配额是 60 次/小时，而"首页输地址看一眼 → 点生成"会用同一份
    元数据请求两次。缓存是这里唯一不牺牲正确性的省法。
    """
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        if "/commits/" in request.url.path:
            return httpx.Response(200, json={"sha": "a" * 40, "commit": {"author": {"date": "2026-01-01T00:00:00Z"}}})
        return httpx.Response(
            200,
            json={"full_name": "o/r", "default_branch": "main", "html_url": f"{BASE}/o/r"},
        )

    with respx.mock(assert_all_called=False) as mock:
        mock.route(url__startswith=BASE).mock(side_effect=handler)
        ref = gh.parse_repo_url(f"{BASE}/o/r")
        first = await gh.fetch_repo_meta(ref)
        second = await gh.fetch_repo_meta(ref)
        assert first is second  # 同一个对象：真的走了缓存
        await gh.resolve_commit(ref, "main")
        await gh.resolve_commit(ref, "main")
    assert len([c for c in calls if "/commits/" in c]) == 1, calls
    assert len([c for c in calls if c.endswith("/repos/o/r")]) == 1, calls


@pytest.mark.asyncio
async def test_cache_ttl_zero_disables_caching(configured, monkeypatch):
    """T-GH-14：`CACHE_TTL_SECONDS=0` 关掉缓存；失败结果**永不**进缓存。"""
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        return httpx.Response(200, json={"full_name": "o/r", "default_branch": "main"})

    monkeypatch.setattr(gh, "CACHE_TTL_SECONDS", 0.0)
    with respx.mock(assert_all_called=False) as mock:
        mock.route(url__startswith=BASE).mock(side_effect=handler)
        ref = gh.parse_repo_url(f"{BASE}/o/r")
        await gh.fetch_repo_meta(ref)
        await gh.fetch_repo_meta(ref)
    assert len(calls) == 2

    # 失败不进缓存：第一次 403，第二次必须真的再打一次并成功
    monkeypatch.setattr(gh, "CACHE_TTL_SECONDS", 60.0)
    gh.reset_github_cache()
    responses = [
        httpx.Response(403, json={"message": "Forbidden"}),
        httpx.Response(200, json={"full_name": "o/r", "default_branch": "main"}),
    ]
    with respx.mock(assert_all_called=False) as mock:
        mock.route(url__startswith=BASE).mock(side_effect=lambda request: responses.pop(0))
        ref = gh.parse_repo_url(f"{BASE}/o/r")
        with pytest.raises(AppError):
            await gh.fetch_repo_meta(ref)
        meta = await gh.fetch_repo_meta(ref)
    assert meta.full_name == "o/r"


def test_token_diagnostics_never_leaks_the_token(configured, monkeypatch):
    """T-GH-15：doctor 的 token 诊断只给指纹，且能指出"等号后多了空格"。"""
    monkeypatch.setattr(settings, "github_token", "ghp_" + "a" * 32 + "6789")
    info = gh.token_diagnostics()
    assert info["configured"] is True
    assert info["fingerprint"] == "ghp_…6789"
    assert info["length"] == 40
    assert info["padded"] is False
    assert "a" * 8 not in info["fingerprint"]

    monkeypatch.setattr(settings, "github_token", "  ghp_abc  ")
    padded = gh.token_diagnostics()
    assert padded["configured"] is True
    assert padded["padded"] is True  # 真实故障：Bearer 里带空格 → 401 Bad credentials

    monkeypatch.setattr(settings, "github_token", "")
    assert gh.token_diagnostics()["configured"] is False


# --------------------------------------------------------------------------- #
# T-GH-4 / 5 / 6                                                              #
# --------------------------------------------------------------------------- #


def test_evil_html_url_is_sanitised(configured):
    """T-GH-4：`javascript:` 的 `html_url` 必须被替换成配置拼装值。

    它会被前端渲染成 `<a href>`——这是唯一一条"端点可以直接把脚本塞进用户页面"
    的路径，因此判据是 scheme **且** host，而不是"看起来像 URL"。
    """
    assert gh.safe_html_url("javascript:alert(1)", full_name="o/r") == f"{BASE}/o/r"
    assert gh.safe_html_url("https://evil.example/o/r", full_name="o/r") == f"{BASE}/o/r"
    assert gh.safe_html_url(f"{BASE}/o/r", full_name="o/r") == f"{BASE}/o/r"
    assert gh.safe_html_url(None, full_name="o/r") == f"{BASE}/o/r"


def test_cross_host_redirect_rejected(configured):
    """T-GH-5：跨域 302 被拒；同域（含 codeload）跟随。

    真 GitHub 的 tarball 会 302 到 codeload，所以不能关掉 `follow_redirects`；
    取而代之的是用 `response.history` 校验**每一跳**。
    """

    class _Hop:
        def __init__(self, url: str) -> None:
            self.url = url

    class _Resp:
        def __init__(self, hops: list[str]) -> None:
            self.history = [_Hop(url) for url in hops]

    with pytest.raises(AppError) as exc:
        gh._check_redirects(_Resp([f"{BASE}/start", "http://169.254.169.254/"]))
    assert exc.value.code == "REPO_NOT_FOUND"
    assert "重定向到未配置的域" in exc.value.message

    # 同域跳转放行
    gh._check_redirects(_Resp([f"{BASE}/start", f"{BASE}/codeload/x"]))
    # 官方 codeload 也放行
    gh._check_redirects(_Resp(["https://api.github.com/start", "https://codeload.github.com/x"]))

    with pytest.raises(AppError):
        gh._check_redirects(_Resp([f"{BASE}/1", f"{BASE}/2", f"{BASE}/3", f"{BASE}/4", f"{BASE}/5"]))


@pytest.mark.asyncio
async def test_oversize_tarball_rejected(configured, tmp_path):
    """T-GH-6：体积双检——`Content-Length` 与解包累计都要拦，且不留半份镜像。"""
    # ① 下载期：Content-Length 就超了
    with respx.mock(assert_all_called=False) as mock:
        mock.route(url__startswith=BASE).mock(
            return_value=httpx.Response(200, content=b"x" * 64, headers={"content-length": str(10 * 1024 * 1024)})
        )
        with pytest.raises(AppError) as exc:
            await gh.download_tarball(gh.parse_repo_url(f"{BASE}/o/r"), "a" * 64, max_bytes=1024)
        assert exc.value.code == "REPO_TOO_LARGE"
        assert "measured_bytes" in exc.value.details

    # ② 解包期：压缩包很小，但解包后超限（压缩比可以任意高，端点不必撒谎）
    payload = _tarball({"big.py": b"y" * 4096})
    dest = tmp_path / "mirror"
    with pytest.raises(AppError) as exc:
        extract_tarball(payload, dest, max_bytes=1024)
    assert exc.value.code == "REPO_TOO_LARGE"
    assert exc.value.details["limit_bytes"] == 1024
    # 超限时已写出的文件被删掉：留下半份镜像会让下一次运行命中"镜像已存在"，
    # 然后拿一堆残缺文件去生成课程。
    assert list(dest.rglob("*")) == [] or all(p.is_dir() for p in dest.rglob("*"))

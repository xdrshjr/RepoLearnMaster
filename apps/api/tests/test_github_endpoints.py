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

import httpx
import pytest
import respx

from repolearn.core.config import settings
from repolearn.core.errors import AppError
from repolearn.ingest import github as gh
from repolearn.ingest.tarball import extract_tarball

BASE = "http://127.0.0.1:9911"


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

"""本机 GitHub 凭据发现链（T-GHA-1..8）。

这组用例守的是一条真实故障：`.env` 没配 token，而机器上其实早就用
`gh auth login` / Git Credential Manager 登录过 GitHub，于是用户看到
`未认证上限 60 次/小时；剩余 0/60`，却没有任何提示告诉他"你本机的凭据可以用"。

同时守三条**红线**，它们比"能取到 token"更重要：

* 绝不把本机 github.com 的凭据发往可配置的自定义端点（凭据外泄）；
* 绝不交互（`git credential fill` 缺失凭据时会弹 GCM 窗口，等于挂死 API 进程）；
* 绝不把非凭据文本当 token（`git credential fill` 参数不对时会往 stdout 打 usage）。
"""

from __future__ import annotations

import subprocess

import pytest

from repolearn.core.config import settings
from repolearn.ingest import github_auth as ga

GHO = "gho_" + "a" * 36
GHP = "ghp_" + "b" * 36


@pytest.fixture(autouse=True)
def _clean():
    """每个用例从空缓存 + 官方端点 + 生产环境语义开始（测试默认禁用发现）。"""
    ga.reset_token_cache()
    yield
    ga.reset_token_cache()


@pytest.fixture()
def official(monkeypatch):
    """把端点设成官方站点，并打开自动发现（测试环境默认是关的）。"""
    monkeypatch.setattr(settings, "github_api_base", "https://api.github.com")
    monkeypatch.setattr(settings, "github_web_base", "https://github.com")
    monkeypatch.setattr(settings, "github_token", "")
    monkeypatch.setattr(settings, "github_token_autodiscover", True)
    monkeypatch.setattr(settings, "env", "development")
    monkeypatch.delenv("GH_TOKEN", raising=False)
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    return settings


# --------------------------------------------------------------------------- #
# 优先级                                                                       #
# --------------------------------------------------------------------------- #


def test_env_file_token_wins_everything(official, monkeypatch):
    """T-GHA-1：`.env` 的显式值永远最高优先——自动发现不得覆盖用户的选择。"""
    monkeypatch.setattr(settings, "github_token", GHP)
    monkeypatch.setenv("GH_TOKEN", GHO)
    monkeypatch.setattr(ga, "_from_gh_cli", lambda: (GHO, "gh-cli"))
    src = ga.resolve_token()
    assert src.token == GHP
    assert src.source == ".env"
    assert src.configured is True


def test_env_var_used_when_dotenv_empty(official, monkeypatch):
    """T-GHA-2：`GH_TOKEN` / `GITHUB_TOKEN` 次之（CI 与 Actions 的惯例）。"""
    monkeypatch.setenv("GH_TOKEN", GHO)
    monkeypatch.setattr(ga, "_from_gh_cli", lambda: ("", ""))
    src = ga.resolve_token()
    assert src.token == GHO
    assert src.source == "env:GH_TOKEN"


def test_gh_cli_is_third(official, monkeypatch):
    """T-GHA-3：没有环境变量时用 `gh auth token`。"""
    monkeypatch.setattr(ga, "_from_gh_cli", lambda: (GHO, "gh-cli"))
    src = ga.resolve_token()
    assert src.source == "gh-cli"
    assert src.token == GHO


def test_git_credential_is_used_when_cli_absent(official, monkeypatch):
    """T-GHA-4：没有 gh 时落到 Git Credential Manager（本机实测可用的一条）。"""
    monkeypatch.setattr(ga, "_from_gh_cli", lambda: ("", ""))
    monkeypatch.setattr(ga, "_from_git_credential", lambda host: (GHO, "git-credential"))
    src = ga.resolve_token()
    assert src.source == "git-credential"
    assert src.token == GHO


def test_all_sources_fail_lists_what_was_tried(official, monkeypatch):
    """T-GHA-5：全都失败时，`tried` 必须能说明"还差哪一环"。

    只说"未配置 token"对用户是无信息量的——他需要知道产品已经替他去问过
    .env / GH_TOKEN / gh CLI / GCM / hosts.yml / .git-credentials。
    """
    for name in ("_from_env_names", "_from_gh_cli", "_from_git_credential", "_from_gh_hosts", "_from_git_credentials_file"):
        monkeypatch.setattr(ga, name, lambda *a, **k: ("", ""))
    src = ga.resolve_token(force=True)
    assert src.configured is False
    joined = " ".join(src.tried)
    for expected in ("REPOLEARN_GITHUB_TOKEN", "GH_TOKEN", "gh auth token", "git credential", "hosts.yml", ".git-credentials"):
        assert expected in joined, joined
    assert "已尝试" in ga.describe_failure(src)


# --------------------------------------------------------------------------- #
# 三条红线                                                                     #
# --------------------------------------------------------------------------- #


def test_custom_endpoint_never_receives_local_credentials(official, monkeypatch):
    """T-GHA-6（红线）：自建端点 / 假 GitHub 一律跳过发现，绝不外发本机凭据。

    端点来自 `.env`（用户可改成任意地址）。把 github.com 的 token 发过去，等于
    把凭据交给一个我们无法验证的服务器——与 `parse_repo_url` 的 SSRF 红线同源。
    """
    monkeypatch.setattr(settings, "github_api_base", "https://ghe.example.com/api/v3")
    monkeypatch.setattr(settings, "github_web_base", "https://ghe.example.com")
    called: list[str] = []
    monkeypatch.setattr(ga, "_from_gh_cli", lambda: (called.append("gh") or (GHO, "gh-cli")))
    src = ga.resolve_token(force=True)
    assert src.configured is False
    assert called == []  # 连探测都不该发生
    assert "不是官方 GitHub" in src.skipped_reason


def test_autodiscover_can_be_disabled(official, monkeypatch):
    """T-GHA-7：`REPOLEARN_GITHUB_TOKEN_AUTODISCOVER=0` 时完全不碰本机。"""
    monkeypatch.setattr(settings, "github_token_autodiscover", False)
    monkeypatch.setattr(ga, "_from_gh_cli", lambda: (GHO, "gh-cli"))
    assert ga.resolve_token(force=True).configured is False


def test_test_env_skips_discovery(monkeypatch):
    """T-GHA-8：`REPOLEARN_ENV=test` 时跳过发现。

    没有这一条，整个 pytest 套件会在开发机上真的去读钥匙串：结果既不可复现，
    也会让"某个用例忽然拿到真 token 去打真 GitHub"这种事故成为可能。
    """
    monkeypatch.setattr(settings, "github_api_base", "https://api.github.com")
    monkeypatch.setattr(settings, "github_web_base", "https://github.com")
    monkeypatch.setattr(settings, "github_token", "")
    monkeypatch.setattr(settings, "github_token_autodiscover", True)
    monkeypatch.setattr(settings, "env", "test")
    assert ga.resolve_token(force=True).configured is False


# --------------------------------------------------------------------------- #
# 子进程：非交互、超时、垃圾输出                                                #
# --------------------------------------------------------------------------- #


def test_subprocess_is_noninteractive():
    """T-GHA-9：子进程环境必须钉死"绝不交互"，否则 GCM 会弹窗挂死 API。"""
    captured: dict[str, object] = {}

    class _Proc:
        returncode = 0
        stdout = "gho_ok\n"
        stderr = ""

    def fake_run(cmd, **kwargs):  # noqa: ANN001
        captured.update(kwargs)
        captured["cmd"] = cmd
        return _Proc()

    import shutil as _shutil

    original = _shutil.which
    _shutil.which = lambda name: f"C:/fake/{name}.exe"  # type: ignore[assignment]
    monkey_module = pytest.MonkeyPatch()
    monkey_module.setattr(subprocess, "run", fake_run)
    try:
        ga._run(["gh", "auth", "token"])
    finally:
        monkey_module.undo()
        _shutil.which = original  # type: ignore[assignment]

    env = captured["env"]
    assert env["GIT_TERMINAL_PROMPT"] == "0"
    assert env["GCM_INTERACTIVE"] == "never"
    assert env["GH_PROMPT_DISABLED"] == "1"
    assert captured["timeout"] == ga.PROBE_TIMEOUT_S
    assert captured["check"] is False


def test_run_never_raises_on_timeout(monkeypatch):
    """T-GHA-10：子进程超时/不存在都只是"这个来源没有"，不是异常。"""

    def boom(*a, **k):  # noqa: ANN002, ANN003
        raise subprocess.TimeoutExpired(cmd="gh", timeout=5)

    import shutil as _shutil

    original = _shutil.which
    _shutil.which = lambda name: "C:/fake/x.exe"  # type: ignore[assignment]
    monkeypatch.setattr(subprocess, "run", boom)
    try:
        assert ga._run(["gh", "auth", "token"]) == ""
    finally:
        _shutil.which = original  # type: ignore[assignment]

    monkeypatch.setattr(_shutil, "which", lambda name: None)
    assert ga._run(["definitely-not-installed"]) == ""


def test_git_credential_output_is_validated(official, monkeypatch):
    """T-GHA-11：`git credential fill` 的 usage 文本不能被当成 token。

    参数不对时它会往 stdout 打一段说明。不做形状校验的话，那段英文会被塞进
    `Authorization: Bearer`，症状是"突然 401，而我没改任何东西"。
    """
    monkeypatch.setattr(ga, "_from_gh_cli", lambda: ("", ""))
    monkeypatch.setattr(
        ga,
        "_run",
        lambda argv, stdin="": "usage: git credential <fill|approve|reject>\nfatal: helper failed\n",
    )
    src = ga.resolve_token(force=True)
    assert src.configured is False


def test_git_credential_parses_password_line(official, monkeypatch):
    """T-GHA-12：真实形状（protocol/host/username/password 四行）能取出 password。"""
    monkeypatch.setattr(ga, "_from_gh_cli", lambda: ("", ""))
    monkeypatch.setattr(
        ga,
        "_run",
        lambda argv, stdin="": f"protocol=https\nhost=github.com\nusername=x-access-token\npassword={GHO}\n",
    )
    src = ga.resolve_token(force=True)
    assert src.token == GHO
    assert src.source == "git-credential"


def test_gh_hosts_yml_is_parsed(official, monkeypatch, tmp_path):
    """T-GHA-13：`gh` 不在 PATH 上时，也能从它自己的 hosts.yml 拿到 oauth_token。"""
    hosts = tmp_path / "hosts.yml"
    hosts.write_text(
        "github.com:\n"
        "    user: someone\n"
        "    oauth_token: " + GHO + "\n"
        "    git_protocol: https\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(ga, "_gh_hosts_files", lambda: [hosts])
    token, source = ga._from_gh_hosts("github.com")
    assert token == GHO
    assert source == "gh-hosts"


def test_git_credentials_file_is_parsed(official, monkeypatch, tmp_path):
    """T-GHA-14：`~/.git-credentials`（credential.helper=store）也能用。"""
    path = tmp_path / ".git-credentials"
    path.write_text(f"https://x-access-token:{GHO}@github.com\n", encoding="utf-8")
    monkeypatch.setattr(ga.Path, "home", staticmethod(lambda: tmp_path))
    token, source = ga._from_git_credentials_file("github.com")
    assert token == GHO
    assert source == "git-credentials-file"


# --------------------------------------------------------------------------- #
# 指纹与出站头                                                                  #
# --------------------------------------------------------------------------- #


def test_fingerprint_never_reveals_the_token(official, monkeypatch):
    """T-GHA-15：指纹只有前 4 后 4，长度也照样能分辨"读到了哪一个"。"""
    monkeypatch.setattr(ga, "_from_gh_cli", lambda: (GHO, "gh-cli"))
    src = ga.resolve_token(force=True)
    assert src.fingerprint() == "gho_…aaaa"
    assert "a" * 20 not in src.fingerprint()


def test_headers_carry_bearer_from_discovered_token(official, monkeypatch):
    """T-GHA-16：出站请求真的带上了自动发现的 token（不只是 doctor 好看）。"""
    from repolearn.ingest import github as gh

    monkeypatch.setattr(ga, "_from_gh_cli", lambda: (GHO, "gh-cli"))
    ga.reset_token_cache()
    headers = gh._headers()
    assert headers["Authorization"] == f"Bearer {GHO}"


def test_rate_limit_hint_names_the_source(official, monkeypatch):
    """T-GHA-17：限流提示必须说出"用的是哪个来源"，否则用户不知道该改哪一处。"""
    from repolearn.ingest import github as gh

    monkeypatch.setattr(ga, "_from_gh_cli", lambda: (GHO, "gh-cli"))
    ga.reset_token_cache()
    hint = gh.rate_limit_hint()
    assert "gh-cli" in hint
    assert "5000" in hint

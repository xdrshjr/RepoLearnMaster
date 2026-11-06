"""离线假 GitHub 的行为契约（spec §4.1 第 5/16 行、§7.2 `T-FGX-1`/`T-FGX-2`）。

这里测的是**假端点自己**，不是产品。原因很直接：`T-GH-1..6` 与 real-backend E2E 都
把结论押在"假端点长成 GitHub 的样子"上。假端点一旦悄悄变样（少了 `Content-Length`、
tar 顶层目录写错、限流开关不生效），那批用例会从"证明产品正确"退化成"证明桩正确"，
而它们仍然全绿。所以这一层要独立钉住：状态码、关键字段、tarball 形状、三个对抗性
开关。

两条硬约束：

* **不联网、不开浏览器**：只连 `127.0.0.1` 上自己起的线程服务器，端口用 `0` 让系统
  分配（`--port 0`），并发跑 pytest 也不会撞端口。
* **必须收尾**：每个用例都在 `_serve()` 的 `finally` 里 `shutdown()` + `server_close()`，
  否则 `ThreadingHTTPServer` 的线程会成为"pytest 跑完了进程却不退出"的经典原因。
"""

from __future__ import annotations

import importlib.util
import io
import json
import sys
import tarfile
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import httpx
import pytest

from repolearn.core.config import REPO_ROOT

FIXTURES = REPO_ROOT / "tests" / "fixtures" / "github"
SNAPSHOTS = REPO_ROOT / "tests" / "fixtures" / "repos"
SNAP_V1 = SNAPSHOTS / "tiny_v1"
SNAP_V2 = SNAPSHOTS / "tiny_v2"
OWNER = "microsoft"
NAME = "autogen"


# --------------------------------------------------------------------------- 工具
def _load_fake():
    """按路径加载脚本模块。

    `scripts/` 不是包（没有 `__init__.py`），也不在 `pythonpath` 里；用 importlib 按
    文件加载是唯一不污染 `sys.path`、也不会与 `repolearn` 撞名的办法。

    **必须先登记进 `sys.modules`**：脚本里有 `from __future__ import annotations`，
    `@dataclass` 在处理字符串注解时要按 `cls.__module__` 回查模块字典；只
    `exec_module()` 而没登记，会得到 `AttributeError: 'NoneType' object has no attribute
    '__dict__'`——一个看起来像脚本自己坏了、其实是加载方式不对的报错。
    """
    path = REPO_ROOT / "scripts" / "fake_github.py"
    spec = importlib.util.spec_from_file_location("fake_github", path)
    assert spec is not None and spec.loader is not None, path
    module = importlib.util.module_from_spec(spec)
    sys.modules["fake_github"] = module
    spec.loader.exec_module(module)
    return module


def _fixture(name: str) -> dict:
    path = FIXTURES / name
    assert path.is_file(), f"缺少夹具 {path}（先跑 python scripts/gen_fixtures.py）"
    return json.loads(path.read_text(encoding="utf-8"))


def _sha_v1() -> str:
    return _fixture("commit_v1.json")["sha"]


def _sha_v2() -> str:
    return _fixture("commit_v2.json")["sha"]


def _snapshot_paths(root: Path) -> set[str]:
    return {p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file()}


def _tarball_names(data: bytes) -> list[str]:
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tar:
        return [member.name for member in tar if member.isfile()]


@contextmanager
def _serve(argv: list[str]) -> Iterator[tuple[object, str]]:
    """在线程里起假端点，产出 `(模块, base_url)`。退出时务必关掉。"""
    fake = _load_fake()
    server = fake.make_server(fake.parse_args(["--port", "0", *argv]))
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield fake, f"http://127.0.0.1:{port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=10)


def _base_args() -> list[str]:
    return [
        "--fixture",
        str(FIXTURES),
        "--snapshot",
        str(SNAP_V1),
        "--snapshot-v2",
        str(SNAP_V2),
        "--second-commit",
        _sha_v2(),
        "--sha",
        _sha_v1(),
        "--owner",
        OWNER,
        "--name",
        NAME,
    ]


# --------------------------------------------------------------------------- T-FGX-1
def test_routes_shape():
    """`T-FGX-1`：5 条路由的状态码 + 关键字段，外加 tarball 的文件数与顶层前缀。"""
    sha_v1, sha_v2 = _sha_v1(), _sha_v2()
    with _serve(_base_args()) as (_, base), httpx.Client(timeout=20.0) as client:
        # 1) /healthz —— 编排器的就绪信号（只认 stdout 那行会在慢机器上假就绪）
        health = client.get(f"{base}/healthz")
        assert health.status_code == 200
        assert health.json() == {"ok": True, "sha": sha_v1}

        # 2) /repos/{o}/{r} —— 元数据按参数注入（full_name/owner/name/html_url）
        meta = client.get(f"{base}/repos/{OWNER}/{NAME}")
        assert meta.status_code == 200
        body = meta.json()
        assert body["full_name"] == f"{OWNER}/{NAME}"
        assert body["owner"]["login"] == OWNER
        assert body["name"] == NAME
        assert body["default_branch"] == "main"  # 来自 repo.json，不是参数
        assert body["html_url"] == f"{base}/{OWNER}/{NAME}"
        assert body["license"]["spdx_id"] == "MIT"
        assert body["clone_url"].endswith(".git")  # 端点会多给字段，产品必须丢掉

        # 3) /repos/{o}/{r}/commits/{ref} —— --second-commit 生效时 HEAD 已指向 v2
        head = client.get(f"{base}/repos/{OWNER}/{NAME}/commits/main")
        assert head.status_code == 200
        payload = head.json()
        assert payload["sha"] == sha_v2
        assert payload["commit"]["author"]["date"] == _fixture("commit_v2.json")["commit"]["author"]["date"]
        statuses = {item["status"] for item in payload["files"]}
        # 快照对比的现场：1 modified + 1 added + 1 removed（T-UPG-2 依赖同一个形状）
        assert statuses == {"added", "modified", "removed"}
        pinned = client.get(f"{base}/repos/{OWNER}/{NAME}/commits/{sha_v1}")
        assert pinned.json()["sha"] == sha_v1  # 显式请求旧 sha 仍拿到 v1

        # 4) /git/trees/<sha>?recursive=1
        tree = client.get(f"{base}/repos/{OWNER}/{NAME}/git/trees/{sha_v1}", params={"recursive": "1"})
        assert tree.status_code == 200
        tree_body = tree.json()
        assert tree_body["sha"] == sha_v1
        assert tree_body["truncated"] is False
        assert {item["path"] for item in tree_body["tree"]} == _snapshot_paths(SNAP_V1)
        assert all(item["type"] == "blob" and item["size"] > 0 for item in tree_body["tree"])

        # 5) /contents/<path>?ref=<sha> —— 原文返回（Accept: application/vnd.github.raw 的等价物）
        raw = client.get(f"{base}/repos/{OWNER}/{NAME}/contents/tiny/agent.py", params={"ref": sha_v1})
        assert raw.status_code == 200
        assert raw.headers["content-type"].startswith("text/plain")
        assert raw.text == (SNAP_V1 / "tiny" / "agent.py").read_text(encoding="utf-8")
        missing_file = client.get(f"{base}/repos/{OWNER}/{NAME}/contents/tiny/router.py", params={"ref": sha_v1})
        assert missing_file.status_code == 404  # v1 里还没有 router.py

        # 6) /tarball/<sha> —— 现造 tar.gz：文件数 = 快照文件数，顶层前缀 {owner}-{name}-{sha}
        tarball = client.get(f"{base}/repos/{OWNER}/{NAME}/tarball/{sha_v1}")
        assert tarball.status_code == 200
        assert tarball.headers["content-type"] == "application/x-gzip"
        assert int(tarball.headers["content-length"]) == len(tarball.content)
        names_v1 = _tarball_names(tarball.content)
        prefix_v1 = f"{OWNER}-{NAME}-{sha_v1}/"
        assert len(names_v1) == len(_snapshot_paths(SNAP_V1))
        assert all(name.startswith(prefix_v1) for name in names_v1)
        assert {name.split("/", 1)[1] for name in names_v1} == _snapshot_paths(SNAP_V1)

        # 同一个 sha 两次下载必须字节一致（tarball 里不能混进当前时间）
        assert client.get(f"{base}/repos/{OWNER}/{NAME}/tarball/{sha_v1}").content == tarball.content

        tarball_v2 = client.get(f"{base}/repos/{OWNER}/{NAME}/tarball/{sha_v2}")
        assert tarball_v2.status_code == 200
        names_v2 = {name.split("/", 1)[1] for name in _tarball_names(tarball_v2.content)}
        assert names_v2 == _snapshot_paths(SNAP_V2)
        assert "tiny/router.py" in names_v2 and "tiny/bus.py" not in names_v2

        # 任一不匹配 → 404 {"message": "Not Found"}（产品的 _map_github_error 靠它走 REPO_NOT_FOUND）
        unknown = client.get(f"{base}/repos/{OWNER}/{NAME}/branches")
        assert unknown.status_code == 404
        assert unknown.json() == {"message": "Not Found"}
        unknown_sha = client.get(f"{base}/repos/{OWNER}/{NAME}/tarball/{'9' * 40}")
        assert unknown_sha.status_code == 404


def test_served_by_a_real_socket():
    """产品侧的 httpx 会真的握手、真的读 `Content-Length`：这条用例把"它不是桩"钉住。

    只断言一件事：响应头里有真实的 HTTP 版本与长度头。打桩（respx / ASGITransport）
    给不出这两个头，而 `T-GH-5/6` 恰恰依赖它们。
    """
    with _serve(_base_args()) as (_, base), httpx.Client(timeout=20.0) as client:
        response = client.get(f"{base}/healthz")
        assert response.http_version in ("HTTP/1.1", "HTTP/1.0")
        assert response.headers["content-length"] == str(len(response.content))


# --------------------------------------------------------------------------- T-FGX-2
def test_rate_limit_switch():
    """`T-FGX-2`：`--rate-limit-first 1` 时第一次 403 且 body 含 `rate limit`，第二次成功。

    **这条用例为什么测得到限流分支（别随手给 4xx 加重试）**：产品侧
    `ingest/github.py` 的出站调用只对 5xx / 超时 / 429 重试，4xx 一律直接映射错误码
    （`providers/http.py::classify_status` 里 403 → `INVALID_KEY`，`retryable=False`）。
    GitHub 的限流是 **403 + "API rate limit exceeded"**，落进"不重试"的那一支，因此
    `--rate-limit-first 1` 的第一次请求会真的打到产品的错误映射上，第二次才成功。
    将来若有人给 403 加上自动重试，这条用例会变成"绿得没有意义"（一次 403 被吞掉），
    必须同步修改这条断言，而不是让它继续绿着。
    """
    with _serve([*_base_args(), "--rate-limit-first", "1"]) as (_, base), httpx.Client(timeout=20.0) as client:
        # /healthz 不计入限流：否则编排器的就绪探测会把配额用光，服务永远"没起来"
        assert client.get(f"{base}/healthz").status_code == 200

        first = client.get(f"{base}/repos/{OWNER}/{NAME}")
        assert first.status_code == 403
        assert "rate limit" in first.text.lower()
        assert first.headers["x-ratelimit-remaining"] == "0"

        second = client.get(f"{base}/repos/{OWNER}/{NAME}")
        assert second.status_code == 200
        assert second.json()["full_name"] == f"{OWNER}/{NAME}"


# ------------------------------------------------- 对抗性开关（T-GH-4/5/6 的前置条件）
def test_evil_html_url_switch():
    """`--evil-html-url`：`/repos` 的 `html_url` 原样返回该值。

    产品侧必须把它换成配置 web base 拼装值（T-GH-4 / 存储型 XSS）；这条用例只保证
    "假端点确实会吐出脏值"——否则 T-GH-4 清洗的是空气。
    """
    with _serve([*_base_args(), "--evil-html-url", "javascript:alert(1)"]) as (_, base), httpx.Client(
        timeout=20.0
    ) as client:
        assert client.get(f"{base}/repos/{OWNER}/{NAME}").json()["html_url"] == "javascript:alert(1)"


def test_redirect_tarball_switch():
    """`--redirect-tarball`：同源 302 → `/codeload/{o}/{r}/tar.gz/{sha}`，跟随到底仍是 tar.gz。

    真 GitHub 的 tarball 就是 302 到 codeload，产品开了 `follow_redirects` 并逐跳校验
    host；"同域重定向必须正常跟随"是 T-GH-5 的另一半。
    """
    sha_v1 = _sha_v1()
    # 产品侧 `providers/http.py::new_client` 是 `follow_redirects=True`，这里照抄：
    # 少了这个，测的就不是"产品会跟随的同域 302"。
    with _serve([*_base_args(), "--redirect-tarball"]) as (_, base), httpx.Client(
        timeout=20.0, follow_redirects=True
    ) as client:
        response = client.get(f"{base}/repos/{OWNER}/{NAME}/tarball/{sha_v1}")
        assert response.status_code == 200
        assert len(response.history) == 1
        hop = response.history[0]
        assert hop.status_code == 302
        assert f"/codeload/{OWNER}/{NAME}/tar.gz/{sha_v1}" in hop.headers["location"]
        assert hop.url.host == httpx.URL(base).host  # 同源，产品不该拒
        assert len(_tarball_names(response.content)) == len(_snapshot_paths(SNAP_V1))


def test_redirect_to_external_switch():
    """`--redirect-to`：302 到任意外部 URL（跨域重定向，T-GH-5 要断言它被拒）。"""
    sha_v1 = _sha_v1()
    target = "http://169.254.169.254/latest/meta-data/"
    with _serve([*_base_args(), "--redirect-to", target]) as (_, base):
        with httpx.Client(timeout=20.0, follow_redirects=False) as client:
            response = client.get(f"{base}/repos/{OWNER}/{NAME}/tarball/{sha_v1}")
        assert response.status_code == 302
        assert response.headers["location"] == target


def test_oversize_tarball_switch():
    """`--oversize-tarball`：无视快照，吐 `2 × max_repo_mb` 字节，且 `Content-Length` 精确。

    用 `--max-repo-mb 1` 把它压到 2 MiB，测试才不会为了"体积超限"下载 120 MB。
    只读第一块：这条用例要证明的是**两道闸都够得着**（声明的长度 + 实际流出的字节），
    不是把 2 MiB 全吞下去。
    """
    sha_v1 = _sha_v1()
    with _serve([*_base_args(), "--oversize-tarball", "--max-repo-mb", "1"]) as (_, base):
        with httpx.Client(timeout=20.0) as client:
            with client.stream("GET", f"{base}/repos/{OWNER}/{NAME}/tarball/{sha_v1}") as response:
                assert response.status_code == 200
                assert int(response.headers["content-length"]) == 2 * 1024 * 1024
                first = next(response.iter_bytes())
                assert first  # 真的在流，而不是"声明很大、什么也不发"
                assert first[:2] == b"\x1f\x8b"  # 真的是 gzip（否则产品会报"不是 tar"而不是"太大"）


# ------------------------------------------------------------------------ 退出码
def test_invalid_params_exit_with_three():
    """spec §5.4：参数非法 → 退出码 3（与编排器用 2 表示的"环境不可用"分开）。

    只喂**非法**参数：合法参数会进 `serve_forever()`，测试会挂住。
    """
    fake = _load_fake()
    assert fake.main(["--fixture", str(FIXTURES / "not-a-fixture-dir")]) == 3
    assert fake.main(["--fixture", str(FIXTURES), "--sha", "not-a-sha"]) == 3
    assert fake.main(["--fixture", str(FIXTURES), "--second-commit", "abc"]) == 3
    assert fake.main(["--fixture", str(FIXTURES), "--snapshot", str(SNAPSHOTS / "nope")]) == 3
    # 未知开关也不该落到 argparse 默认的 2（那是"环境不可用"的码）
    assert fake.main(["--fixture-missing"]) == 3


@pytest.mark.parametrize("name", ["commit_v1.json", "commit_v2.json", "manifest.json", "repo.json"])
def test_github_fixtures_exist(name: str):
    """夹具是 `test_fake_github` 与 real-backend E2E 的共同输入，缺一个就整层失效。"""
    assert (FIXTURES / name).is_file(), f"缺少 {name}：先跑 python scripts/gen_fixtures.py"

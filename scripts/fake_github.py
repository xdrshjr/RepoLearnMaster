"""离线假 GitHub（spec §3.2.2 / §4.1 第 5 行）。

**为什么需要一个真服务**：M7 的 real-backend E2E 要把"导入 → 生成 → 发布"这条主链路
真的跑一遍。在测试里打桩内部函数等于测自己写的桩——它发现不了 httpx 的重定向策略、
流式读取、`Content-Length` 校验这些"只在真连接上才成立"的行为，也发现不了产品把
端点拼错（拼错了桩照样返回漂亮的数据）。

三条不可协商的约束：

1. **只用标准库**（`http.server` / `json` / `tarfile` / `gzip` / `io` / `argparse`）。
   假端点不该让 CI 多装一个包，也不该让"干净机器上跑不起来"成为 E2E 的借口。
2. **tarball 是现造的**：唯一事实来源是 `--snapshot` 目录。若改成"仓库里预先打好的
   压缩包"，"改了夹具忘了重新打包"会让 E2E 拿到上一版代码，而所有断言仍然绿。
3. **导入不启动任何东西**：`make_server()` 只构造对象，`main()` 才监听。测试因此可以
   在后台线程里起它（`apps/api/tests/test_fake_github.py`），导入模块不会占端口。

退出码（spec §5.4）：0 正常 / 3 参数非法。**不用 2**——`scripts/e2e-real.mjs` 用 2 表示
"环境不可用（端口占用、venv 缺失）"，两种失败混在一个码里，排障时只能靠猜。
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import io
import json
import re
import struct
import sys
import tarfile
import threading
import zlib
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import NoReturn
from urllib.parse import parse_qs, urlsplit

REPO_ROOT = Path(__file__).resolve().parents[1]

# spec §3.2.1：产品侧对 sha 的校验是 `re.fullmatch(r"[0-9a-f]{40,64}", sha)`。
# 这里故意同样只收小写：假端点若能返回大写或短 sha，产品会拒绝，而我们会以为是
# 产品的解析错了——假端点必须比真端点更严格，否则它就成了掩盖缺陷的那一层。
_SHA_RE = re.compile(r"[0-9a-f]{40,64}")

_DEFAULT_BRANCH_ALIASES = ("HEAD", "main", "master")


class ConfigError(Exception):
    """参数/夹具非法。`main()` 把它翻译成退出码 3。"""


@dataclass
class State:
    """一次运行的全部输入与可变状态（限流计数、tarball 缓存）。"""

    fixture: Path
    owner: str
    name: str
    sha: str
    snapshot: Path | None = None
    snapshot_v2: Path | None = None
    second_commit: str | None = None
    repo_json: dict = field(default_factory=dict)
    commit_v1: dict = field(default_factory=dict)
    commit_v2: dict | None = None
    rate_limit_first: int = 0
    evil_html_url: str | None = None
    redirect_to: str | None = None
    redirect_tarball: bool = False
    oversize_tarball: bool = False
    max_repo_mb: int = 60
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)
    _served: int = field(default=0, repr=False)
    _tarballs: dict[str, bytes] = field(default_factory=dict, repr=False)

    @property
    def full_name(self) -> str:
        return f"{self.owner}/{self.name}"

    @property
    def default_branch(self) -> str:
        return str(self.repo_json.get("default_branch") or "main")

    @property
    def v2_sha(self) -> str | None:
        """v2 的 sha：`--second-commit` 优先，否则取 `commit_v2.json` 里写死的常量。"""
        if self.second_commit:
            return self.second_commit
        return str((self.commit_v2 or {}).get("sha") or "") or None

    def consume_rate_limit(self) -> bool:
        """前 N 次 API 请求返回限流错误（供 `RATE_LIMITED` 分支断言）。

        **`/healthz` 不计入**：编排器的就绪判定是"stdout 那行 + `/healthz` 200"双条件，
        一开限流就把健康检查也打 403 的话，`--rate-limit-first 1` 会让服务永远"没起来"。
        """
        if self.rate_limit_first <= 0:
            return False
        with self._lock:
            self._served += 1
            return self._served <= self.rate_limit_first

    def snapshot_for(self, sha: str) -> Path | None:
        """sha → 快照目录。未知 sha 返回 None，让路由走 404（真 GitHub 也这样）。"""
        if sha == self.sha:
            return self.snapshot
        if self.v2_sha and sha == self.v2_sha:
            return self.snapshot_v2
        return None

    def commit_for(self, ref: str) -> dict | None:
        """ref → commit 响应体。

        规则（spec §3.2.2 + §3.2.3）：配置了 `--second-commit` 就等于"仓库已经往前走了"，
        此时 `main`/`HEAD`/v2 sha 都指向 v2；而显式请求 v1 的 sha 仍然拿到 v1——M10 的
        增量升级用例需要"旧版本还在，但 HEAD 变了"这个现场。
        """
        if self.commit_v2 is not None and self.v2_sha and ref in self._v2_refs():
            return dict(self.commit_v2, sha=self.v2_sha)
        if ref in (self.sha, self.default_branch, *_DEFAULT_BRANCH_ALIASES):
            return self.commit_v1
        return None

    def _v2_refs(self) -> set[str]:
        refs = {self.v2_sha or ""}
        if self.second_commit:
            # 只有显式给了 --second-commit，"分支指向 v2" 才成立；否则 /commits/main
            # 仍应返回 v1，让"首次导入"和"仓库更新后升级"是两条不同的现场。
            refs.update({self.default_branch, *_DEFAULT_BRANCH_ALIASES})
        return {ref for ref in refs if ref}


# --------------------------------------------------------------------------- 快照
def _snapshot_paths(root: Path) -> list[Path]:
    """快照目录下的全部文件，按仓库内相对路径排序（顺序影响 tree 与 tar 的字节）。"""
    paths = [p for p in root.rglob("*") if p.is_file()]
    return sorted(paths, key=lambda p: p.relative_to(root).as_posix())


def _read_snapshot(root: Path) -> dict[str, bytes]:
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in _snapshot_paths(root)}


def _line_count(data: bytes) -> int:
    return len(data.splitlines())


def _patch_text(data: bytes, sign: str, header: str) -> str:
    """一段确定性的"补丁"：只要前 3 行。

    真实 GitHub 才会给完整 unified diff；这里给的是**形状**（`@@ ... @@` + 前导符号），
    产品只把 `files` 当"变了几个文件"用，编造完整 patch 只会让夹具更难读。
    """
    lines = data.decode("utf-8", "replace").splitlines()[:3]
    body = "".join(f"{sign}{line}\n" for line in lines)
    return f"{header}\n{body}" if body else header


def changed_files(current: dict[str, bytes], previous: dict[str, bytes] | None) -> list[dict]:
    """把两份快照压成 GitHub 形状的 `files` 列表。

    规则与 `scripts/gen_fixtures.py::_commit_files` 逐条一致（两份实现刻意不互相
    导入：夹具生成器不该依赖一个测试服务器的模块）。若哪天两条路给出不同的 `files`，
    同一份 commit 在"夹具 JSON"和"运行时生成"上就会说不同的话，而 E2E 会以为自己
    在测另一边。
    """
    out: list[dict] = []
    if previous is None:
        for path in sorted(current):
            data = current[path]
            lines = _line_count(data)
            out.append(
                {
                    "filename": path,
                    "status": "added",
                    "additions": lines,
                    "deletions": 0,
                    "changes": lines,
                    "patch": _patch_text(data, "+", f"@@ -0,0 +1,{lines} @@"),
                }
            )
        return out
    for path in sorted(current):
        data = current[path]
        old = previous.get(path)
        if old is None:
            lines = _line_count(data)
            out.append(
                {
                    "filename": path,
                    "status": "added",
                    "additions": lines,
                    "deletions": 0,
                    "changes": lines,
                    "patch": _patch_text(data, "+", f"@@ -0,0 +1,{lines} @@"),
                }
            )
        elif old != data:
            new_lines, old_lines = _line_count(data), _line_count(old)
            out.append(
                {
                    "filename": path,
                    "status": "modified",
                    "additions": new_lines,
                    "deletions": old_lines,
                    "changes": new_lines + old_lines,
                    "patch": _patch_text(data, "+", f"@@ -1,{old_lines} +1,{new_lines} @@"),
                }
            )
    for path in sorted(set(previous) - set(current)):
        old_lines = _line_count(previous[path])
        out.append(
            {
                "filename": path,
                "status": "removed",
                "additions": 0,
                "deletions": old_lines,
                "changes": old_lines,
                "patch": _patch_text(previous[path], "-", f"@@ -1,{old_lines} +0,0 @@"),
            }
        )
    return sorted(out, key=lambda item: item["filename"])


# -------------------------------------------------------------------------- tarball
def _build_tarball(snapshot: Path, prefix: str) -> bytes:
    """现造 tar.gz：内容 = 快照目录，顶层目录 = `<owner>-<name>-<sha>`。

    顶层目录不是装饰：产品侧 `ingest/tarball.py::_strip_first_component` 靠它把路径
    归一到镜像根，造错了会得到"所有文件落到镜像外层"这种只在 E2E 才看得见的错。

    gzip 头里的 mtime 固定为 0（`tarfile.open(mode="w:gz")` 会写当前时间）：
    同一个 sha 两次请求拿到不同字节，就无法用"压缩包哈希"排查"是不是同一份快照"。
    """
    raw = io.BytesIO()
    with tarfile.open(fileobj=raw, mode="w", format=tarfile.PAX_FORMAT) as tar:
        for path in _snapshot_paths(snapshot):
            data = path.read_bytes()
            info = tarfile.TarInfo(f"{prefix}/{path.relative_to(snapshot).as_posix()}")
            info.size = len(data)
            info.mtime = 0
            info.mode = 0o644
            info.uid = info.gid = 0
            info.uname = info.gname = ""
            tar.addfile(info, io.BytesIO(data))
    out = io.BytesIO()
    with gzip.GzipFile(fileobj=out, mode="wb", mtime=0) as gz:
        gz.write(raw.getvalue())
    return out.getvalue()


def _oversize_gzip(total: int) -> tuple[int, Iterator[bytes]]:
    """造一个**合法** gzip 流（内容全零），字节数恰好等于 `total`。

    为什么较真：`--oversize-tarball` 是给"体积双检"（spec §3.2.2 / T-GH-6）用的。
    * 少报 `Content-Length` → 产品只会撞到"流式累计"那道闸，另一道永远测不到；
    * 流本身不合法 → 一旦产品先信了 `Content-Length`，看到的错误就变成"不是 tar"，
      断言随之失去意义。

    精确控长靠 deflate 的 stored block（每块 5 字节头 + 至多 65535 字节负载）：
    头 10 字节 + 各块 + 尾 8 字节 = total，解出来的内容全是零。
    """
    header = b"\x1f\x8b\x08\x00\x00\x00\x00\x00\x00\x03"  # magic/method/flags/mtime=0/xfl/os
    avail = total - len(header) - 8
    if avail < 6:
        # 退化输入（调用方给的总长太小）：不装 gzip 了，直接吐等长零字节。
        return total, iter([bytes(total)])
    blocks = max(1, -(-avail // 65540))  # 每块最多 5 + 65535 字节
    while blocks > 1 and avail - 5 * blocks < 0:
        blocks -= 1
    payload = avail - 5 * blocks
    sizes: list[int] = []
    left = payload
    for _ in range(blocks):
        size = min(65535, left)
        sizes.append(size)
        left -= size
    crc = 0
    zero = bytes(65535)
    left = payload
    while left > 0:
        take = min(left, len(zero))
        crc = zlib.crc32(zero[:take], crc)
        left -= take
    trailer = struct.pack("<II", crc, payload & 0xFFFFFFFF)

    def chunks() -> Iterator[bytes]:
        yield header
        for index, size in enumerate(sizes):
            # BFINAL（最后一块置 1，否则 gzip 会报 "ended before end-of-stream"）
            # + BTYPE=00（stored）+ LEN + NLEN（LEN 按位取反）
            final = 0x01 if index == len(sizes) - 1 else 0x00
            yield struct.pack("<BHH", final, size, 0xFFFF ^ size)
            if size:
                yield bytes(size)
        yield trailer

    return total, chunks()


# -------------------------------------------------------------------------- 路由
class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "FakeGitHub/1.0"

    # ---- 基础设施 -----------------------------------------------------------
    @property
    def state(self) -> State:
        return self.server.state  # type: ignore[attr-defined]

    def log_message(self, fmt: str, *args: object) -> None:
        """关掉 access log。

        编排器按 stdout 的就绪行 + `/healthz` 双条件判定启动完成，stderr 只留给真错误；
        每个请求一行日志会把 E2E 失败现场冲掉（几百行 access log 里找一条 traceback）。
        """

    def _origin(self) -> str:
        return f"http://127.0.0.1:{self.server.server_address[1]}"  # type: ignore[attr-defined]

    def _send(self, status: int, body: bytes, content_type: str, extra: dict[str, str] | None = None) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        for key, value in (extra or {}).items():
            self.send_header(key, value)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, status: int, payload: object, extra: dict[str, str] | None = None) -> None:
        body = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
        self._send(status, body, "application/json; charset=utf-8", extra)

    def _not_found(self) -> None:
        """统一 404 形状：产品的 `_map_github_error` 靠 404 + `message` 映射 `REPO_NOT_FOUND`。"""
        self._json(404, {"message": "Not Found"})

    def _redirect(self, location: str) -> None:
        self.send_response(302)
        self.send_header("Location", location)
        self.send_header("Content-Length", "0")
        self.end_headers()

    # ---- 入口 ---------------------------------------------------------------
    def do_GET(self) -> None:  # noqa: N802 —— BaseHTTPRequestHandler 规定的名字
        try:
            self._dispatch()
        except (BrokenPipeError, ConnectionResetError):
            # 产品在 Content-Length 检出超限后立刻挂断连接，这是预期行为而不是服务端错误：
            # 若任由异常抛出，ThreadingHTTPServer 会把 traceback 打到 stderr 冒充故障。
            self.close_connection = True

    def _dispatch(self) -> None:
        state = self.state
        parsed = urlsplit(self.path)
        parts = [part for part in parsed.path.split("/") if part]

        # 1) /healthz —— 编排器就绪判定用，**永不限流**（见 State.consume_rate_limit）
        if parts == ["healthz"]:
            self._json(200, {"ok": True, "sha": state.sha})
            return

        # 2) 限流开关：前 N 次任意 API 请求 403 + "rate limit"，形状照 GitHub
        if state.consume_rate_limit():
            self._json(
                403,
                {"message": "API rate limit exceeded"},
                extra={"X-RateLimit-Remaining": "0"},
            )
            return

        query = parse_qs(parsed.query)

        if len(parts) >= 3 and parts[0] == "repos":
            rest = parts[3:]
            if not rest:
                self._repo_meta()
                return
            if rest[0] == "commits" and len(rest) == 2:
                self._commit(rest[1])
                return
            if rest[0] == "tarball" and len(rest) == 2:
                self._tarball(rest[1], via_codeload=False)
                return
            if rest[:2] == ["git", "trees"] and len(rest) == 3:
                self._tree(rest[2])
                return
            if rest[0] == "contents" and len(rest) >= 2:
                self._contents("/".join(rest[1:]), query)
                return

        # 3) /codeload/{o}/{r}/tar.gz/{sha} —— `--redirect-tarball` 的同源落点。
        #    真 GitHub 的 /tarball 就是 302 到这里，产品必须跟得上且仍判为同域。
        if len(parts) == 5 and parts[0] == "codeload" and parts[3] == "tar.gz":
            self._tarball(parts[4], via_codeload=True)
            return

        self._not_found()

    # ---- 各路由 -------------------------------------------------------------
    def _repo_meta(self) -> None:
        state = self.state
        data = json.loads(json.dumps(state.repo_json))  # 深拷贝：注入字段不能污染夹具
        data["full_name"] = state.full_name
        data["name"] = state.name
        data["owner"] = dict(data.get("owner") or {}, login=state.owner)
        # html_url 默认指向本服务：E2E 把 REPOLEARN_GITHUB_WEB_BASE 也设成同一个
        # origin，于是"端点自报的 html_url"与"配置拼装值"一致，产品侧的白名单校验
        # 才不会误伤。`--evil-html-url` 专门打破这个前提（T-GH-4）。
        data["html_url"] = state.evil_html_url or f"{self._origin()}/{state.full_name}"
        self._json(200, data)

    def _commit(self, ref: str) -> None:
        state = self.state
        payload = state.commit_for(ref)
        if payload is None:
            self._not_found()
            return
        self._json(200, self._with_snapshot_files(payload, ref))

    def _with_snapshot_files(self, payload: dict, ref: str) -> dict:
        """给了快照就按目录清单重算 `files`，否则用夹具里预先算好的那份。

        为什么不在夹具里把 `files` 写死就够了：E2E 有时只传 `--snapshot`（没有 v2），
        此时"v2 的 commit 却报 v1 的文件清单"会让 `Commit.file_count` 与实际镜像对不上。
        """
        state = self.state
        if not state.snapshot:
            return payload
        current_snapshot = state.snapshot
        previous_snapshot: Path | None = None
        if state.v2_sha and payload.get("sha") == state.v2_sha:
            if state.snapshot_v2 is None:
                # 没有 v2 快照就保留夹具里那份清单：编一份"v2 的文件列表"比不给更糟。
                return payload
            current_snapshot = state.snapshot_v2
            previous_snapshot = state.snapshot
        current = _read_snapshot(current_snapshot)
        previous = _read_snapshot(previous_snapshot) if previous_snapshot else None
        return dict(payload, files=changed_files(current, previous))

    def _tree(self, sha: str) -> None:
        state = self.state
        snapshot = state.snapshot_for(sha)
        if snapshot is None:
            self._not_found()
            return
        tree = []
        for path, data in _read_snapshot(snapshot).items():
            tree.append(
                {
                    "path": path,
                    "type": "blob",
                    "size": len(data),
                    # 真 GitHub 给的是 git blob sha1（`blob <size>\0<content>` 的 sha1），
                    # 顺手算出来：产品侧把 sha 当不透明字符串用，但夹具越像真的越能暴露
                    # "顺手拿 sha 当内容哈希"这类误用。
                    "sha": hashlib.sha1(f"blob {len(data)}\0".encode() + data).hexdigest(),
                }
            )
        self._json(200, {"sha": sha, "tree": tree, "truncated": False})

    def _contents(self, rel_path: str, query: dict[str, list[str]]) -> None:
        state = self.state
        ref = (query.get("ref") or [""])[0]
        snapshot = state.snapshot_for(ref) if ref else state.snapshot
        if snapshot is None:
            self._not_found()
            return
        rel = rel_path.strip("/")
        if not rel or any(part in ("", ".", "..") for part in rel.split("/")):
            self._not_found()
            return
        target = snapshot / rel
        try:
            # 路径守卫：假端点也在进程里跑，读到 `--snapshot` 之外的文件同样算 bug。
            if not target.resolve().is_relative_to(snapshot.resolve()):
                self._not_found()
                return
            data = target.read_bytes()
        except OSError:
            self._not_found()
            return
        self._send(200, data, "text/plain; charset=utf-8")

    def _tarball(self, sha: str, *, via_codeload: bool) -> None:
        state = self.state
        if state.redirect_to:
            # 跨域重定向（T-GH-5）：产品必须逐跳校验 host，且在越界时抛 REPO_NOT_FOUND。
            self._redirect(state.redirect_to)
            return
        if state.redirect_tarball and not via_codeload:
            self._redirect(f"{self._origin()}/codeload/{state.owner}/{state.name}/tar.gz/{sha}")
            return
        if state.oversize_tarball:
            total, chunks = _oversize_gzip(state.max_repo_mb * 2 * 1024 * 1024)
            self.send_response(200)
            self.send_header("Content-Type", "application/x-gzip")
            self.send_header("Content-Length", str(total))
            self.end_headers()
            for chunk in chunks:
                self.wfile.write(chunk)
            return
        snapshot = state.snapshot_for(sha)
        if snapshot is None:
            self._not_found()
            return
        cached = state._tarballs.get(sha)
        if cached is None:
            cached = _build_tarball(snapshot, f"{state.owner}-{state.name}-{sha}")
            with state._lock:
                state._tarballs[sha] = cached
        # Content-Length 必须精确：产品的第一道体积闸就靠它（spec §3.2.2 / T-GH-6）。
        self._send(200, cached, "application/x-gzip")


class FakeGitHub(ThreadingHTTPServer):
    """把状态挂在 server 上：`make_server()` 返回它之后，端口才是确定的。"""

    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address: tuple[str, int], state: State) -> None:
        self.state = state
        super().__init__(address, _Handler)


# -------------------------------------------------------------------------- 组装
class _Parser(argparse.ArgumentParser):
    """参数非法一律走 `ConfigError`（→ 退出码 3），不留 argparse 默认的 2。"""

    def error(self, message: str) -> NoReturn:
        raise ConfigError(message)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = _Parser(prog="fake_github", description="离线假 GitHub（spec §3.2.2）")
    parser.add_argument("--port", type=int, default=9911, help="0 让系统分配（测试用）")
    parser.add_argument("--fixture", default="tests/fixtures/github", help="含 repo.json / commit_v1.json 的目录")
    parser.add_argument("--snapshot", default=None, help="v1 快照目录（tarball/tree/contents 的内容来源）")
    parser.add_argument("--snapshot-v2", dest="snapshot_v2", default=None, help="v2 快照目录（M10 增量升级用）")
    parser.add_argument("--second-commit", dest="second_commit", default=None, help="v2 的 commit sha")
    parser.add_argument("--owner", default="microsoft")
    parser.add_argument("--name", default="autogen")
    parser.add_argument("--sha", default=None, help="v1 的 commit sha，默认取 commit_v1.json")
    parser.add_argument("--rate-limit-first", dest="rate_limit_first", type=int, default=0, help="前 N 次请求 403")
    parser.add_argument("--evil-html-url", dest="evil_html_url", default=None, help="repos 元数据的 html_url 返回它")
    parser.add_argument("--redirect-to", dest="redirect_to", default=None, help="tarball 302 到这个 URL")
    parser.add_argument("--redirect-tarball", dest="redirect_tarball", action="store_true", help="同源 302 到 /codeload")
    parser.add_argument("--oversize-tarball", dest="oversize_tarball", action="store_true", help="吐 2×max_repo_mb 字节")
    parser.add_argument("--max-repo-mb", dest="max_repo_mb", type=int, default=60, help="oversize 用的上限（MB）")
    return parser.parse_args(argv)


def _resolve(raw: str | None) -> Path | None:
    """相对路径先按 cwd、再按仓库根解析。

    编排器从仓库根起进程，而 `pytest` 的工作目录可能是别的；这样两种起法都能用，
    同时"确实不存在"的路径仍会被 `_build_state` 判成参数非法。
    """
    if not raw:
        return None
    path = Path(raw)
    if path.is_absolute():
        return path
    for base in (Path.cwd(), REPO_ROOT):
        candidate = base / path
        if candidate.exists():
            return candidate
    return Path.cwd() / path


def _load_json(path: Path) -> dict:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ConfigError(f"夹具无法解析：{path}（{exc}）") from exc
    if not isinstance(payload, dict):
        raise ConfigError(f"夹具必须是 JSON 对象：{path}")
    return payload


def _build_state(ns: argparse.Namespace) -> State:
    """把命令行参数校验成运行状态。任何不成立都抛 `ConfigError`（退出码 3）。"""
    fixture = _resolve(ns.fixture)
    if fixture is None or not fixture.is_dir():
        raise ConfigError(f"--fixture 目录不存在：{ns.fixture}（先跑 python scripts/gen_fixtures.py）")
    for name in ("repo.json", "commit_v1.json"):
        if not (fixture / name).is_file():
            raise ConfigError(f"夹具缺少 {name}：{fixture}（先跑 python scripts/gen_fixtures.py）")

    repo_json = _load_json(fixture / "repo.json")
    commit_v1 = _load_json(fixture / "commit_v1.json")
    commit_v2 = _load_json(fixture / "commit_v2.json") if (fixture / "commit_v2.json").is_file() else None

    sha = ns.sha or str(commit_v1.get("sha") or "")
    if not _SHA_RE.fullmatch(sha):
        raise ConfigError(f"--sha 必须是 40-64 位小写十六进制：{sha!r}")
    if ns.second_commit is not None and not _SHA_RE.fullmatch(ns.second_commit):
        raise ConfigError(f"--second-commit 必须是 40-64 位小写十六进制：{ns.second_commit!r}")

    def snapshot(raw: str | None, flag: str) -> Path | None:
        if raw is None:
            return None
        path = _resolve(raw)
        if path is None or not path.is_dir():
            raise ConfigError(f"{flag} 目录不存在：{raw}（先跑 python scripts/gen_fixtures.py）")
        return path

    if not 0 <= ns.port <= 65535:
        raise ConfigError(f"--port 越界：{ns.port}")
    if ns.rate_limit_first < 0:
        raise ConfigError(f"--rate-limit-first 不能为负：{ns.rate_limit_first}")
    if ns.max_repo_mb <= 0:
        raise ConfigError(f"--max-repo-mb 必须为正：{ns.max_repo_mb}")

    return State(
        fixture=fixture,
        owner=ns.owner,
        name=ns.name,
        sha=sha,
        snapshot=snapshot(ns.snapshot, "--snapshot"),
        snapshot_v2=snapshot(ns.snapshot_v2, "--snapshot-v2"),
        second_commit=ns.second_commit,
        repo_json=repo_json,
        commit_v1=commit_v1,
        commit_v2=commit_v2,
        rate_limit_first=ns.rate_limit_first,
        evil_html_url=ns.evil_html_url,
        redirect_to=ns.redirect_to,
        redirect_tarball=ns.redirect_tarball,
        oversize_tarball=ns.oversize_tarball,
        max_repo_mb=ns.max_repo_mb,
    )


def make_server(ns: argparse.Namespace) -> FakeGitHub:
    """构造（但不启动）服务器。测试在线程里 `serve_forever()` 即可拿到端口。"""
    state = _build_state(ns)
    return FakeGitHub(("127.0.0.1", ns.port), state)


def main(argv: Sequence[str] | None = None) -> int:
    try:
        ns = parse_args(argv)
        server = make_server(ns)
    except ConfigError as exc:
        print(f"fake-github: {exc}", file=sys.stderr)
        return 3
    port = server.server_address[1]
    # 就绪信号：编排器同时看这一行和 /healthz（只看一行会在慢机器上假就绪）。
    print(f"fake-github listening on http://127.0.0.1:{port} (sha={server.state.sha})", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

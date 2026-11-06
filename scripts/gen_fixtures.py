"""生成测试夹具（spec §4.1 / T-TEST-1）。

要求：**离线可运行、产出确定（二次运行字节一致）**。

两条纪律：
1. 不触网。夹具一旦依赖网络，CI 就会随机红灯，最后被 skip。
2. 不用 `time.time()` / 随机数。任何"看起来无关紧要"的不确定性都会让
   "二次运行字节一致"这条断言失效，而它正是"夹具能当契约用"的前提。
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures"

GITHUB_REPO = {
    "full_name": "microsoft/autogen",
    "name": "autogen",
    "owner": {"login": "microsoft"},
    "description": "A programming framework for agentic AI",
    "stargazers_count": 32000,
    "language": "Python",
    "license": {"spdx_id": "MIT"},
    "default_branch": "main",
    "html_url": "https://github.com/microsoft/autogen",
    "size": 24000,
    "private": False,
    # `clone_url` / `archive_url` 本轮**不落库**（spec §3.2.1 安全红线 B），但仍然写进夹具：
    # 一个只含"允许字段"的夹具无法证明产品的白名单真的在丢弃东西——T-GH-4 需要"端点多给了
    # 几个字段，落库结果里一个都不该出现"这个现场。
    "clone_url": "https://github.com/microsoft/autogen.git",
    "archive_url": "https://github.com/microsoft/autogen/{archive_format}{/ref}",
}

GITHUB_COMMIT = {
    "sha": "0" * 40,
    "commit": {"author": {"date": "2026-01-01T00:00:00Z"}, "message": "initial fixture commit"},
    "html_url": "https://github.com/microsoft/autogen/commit/" + "0" * 40,
}

GOLDEN_CURRICULUM = {
    "title": "AutoGen 带读课程",
    "subtitle": "夹具生成的黄金样本",
    "summary_md": "用于契约校验与回归的确定性课程骨架。",
    "sections": [
        {
            "key": "overview",
            "title": "第一层 · 宏观架构",
            "minutes": 6,
            "lessons": [
                {"key": f"1.{i}", "title": f"结构 {i}", "goal": "看懂分层与入口", "minutes": 2,
                 "anchors": [{"file": "autogen/agentchat/conversable_agent.py", "line_start": 1, "line_end": 5}]}
                for i in range(1, 4)
            ],
        },
        {
            "key": "walkthrough",
            "title": "第二层 · 全局走读",
            "minutes": 9,
            "lessons": [
                {"key": f"2.{i}", "title": f"往返 {i}", "goal": "画出调用顺序", "minutes": 3,
                 "anchors": [{"file": "autogen/agentchat/groupchat.py", "line_start": 1, "line_end": 6}]}
                for i in range(1, 4)
            ],
        },
        {
            "key": "deep_dive",
            "title": "第三层 · 深入源码",
            "minutes": 12,
            "lessons": [
                {"key": f"3.{i}", "title": f"精讲 {i}", "goal": "解释关键分支", "minutes": 3,
                 "anchors": [{"file": "autogen/agentchat/conversable_agent.py", "line_start": 10, "line_end": 16}]}
                for i in range(1, 5)
            ],
        },
        {
            "key": "recap",
            "title": "课程总结",
            "minutes": 4,
            "lessons": [{"key": "4.1", "title": "复盘", "goal": "复述三个结论", "minutes": 4}],
        },
    ],
}

GOLDEN_TRACE = {
    "key": "trace_1.1",
    "title": "GroupChat → ConversableAgent → generate_reply",
    "steps": [
        {
            "index": 0,
            "title": "GroupChat.run 收到初始消息",
            "certainty": "source_fact",
            "evidence": [{"file": "autogen/agentchat/groupchat.py", "line_start": 10, "line_end": 12, "symbol": "run"}],
            "variables": [{"name": "initial_message", "value": "'hi'", "note": "示例值，非真实运行结果"}],
        },
        {
            "index": 1,
            "title": "逐 agent 调用 send",
            "certainty": "static_inference",
            "evidence": [{"file": "autogen/agentchat/conversable_agent.py", "line_start": 10, "line_end": 12}],
            "variables": [],
        },
    ],
}

SOURCE_SNIPPETS = {
    "autogen/agentchat/conversable_agent.py": (
        '"""ConversableAgent: 可收发消息、调用工具的 Agent 基类。"""\n'
        "\n"
        "class ConversableAgent:\n"
        "    def __init__(self, name, llm_config=None):\n"
        "        self.name = name\n"
        "        self.llm_config = llm_config or {}\n"
        "        self.chat_messages = {}\n"
        "\n"
        "    def send(self, message, recipient):\n"
        "        self.chat_messages.setdefault(recipient.name, []).append(message)\n"
        "        return recipient.receive(message, self)\n"
        "\n"
        "    def receive(self, message, sender):\n"
        "        return self.generate_reply(messages=self.chat_messages.get(sender.name, []))\n"
        "\n"
        "    def generate_reply(self, messages=None):\n"
        "        if not self.llm_config:\n"
        "            return None\n"
        "        return {'role': 'assistant', 'content': 'ok'}\n"
    ),
    "autogen/agentchat/groupchat.py": (
        '"""GroupChat: 多个 Agent 按顺序轮转的群聊编排。"""\n'
        "\n"
        "class GroupChat:\n"
        "    def __init__(self, agents, max_round=10):\n"
        "        self.agents = agents\n"
        "        self.max_round = max_round\n"
        "\n"
        "    def run(self, initial_message):\n"
        "        message = initial_message\n"
        "        for _ in range(self.max_round):\n"
        "            for agent in self.agents:\n"
        "                message = agent.send(message, self.agents[0])\n"
        "        return message\n"
    ),
}


# ---------------------------------------------------------------------------
# 假 GitHub 的双版本快照（spec §4.1 第 14 行 / T-UPG-2）
#
# tiny_v1 → tiny_v2 的演化被**写死**成 1 modified + 1 added + 1 removed：`analysis/diff.py`
# 的 T-UPG-2 断言的就是这三个数字。故意不"顺手多改一处"——多改一行，那条断言就从
# "证明 diff 正确"退化成"证明夹具被改过"。
#
# 两个 sha、两个日期都是常量而不是时间函数：夹具一旦依赖当前时间，"二次运行字节一致"
# 当场失效，而它正是"夹具能当契约用"的前提。
SHA_V1 = "1a2b3c4d5e6f7a8b9c0d1e2f3a4b5c6d7e8f9a0b"
SHA_V2 = "2b3c4d5e6f7a8b9c0d1e2f3a4b5c6d7e8f9a0b1c"
COMMIT_DATE_V1 = "2026-01-01T00:00:00Z"
COMMIT_DATE_V2 = "2026-03-01T00:00:00Z"
COMMIT_MESSAGE_V1 = "chore(tiny): initial import"
COMMIT_MESSAGE_V2 = "feat(tiny): add router, drop bus"

TINY_README = (
    "# tiny-agent\n"
    "\n"
    "一个**用来当夹具**的极小 Python 仓库：只演示「agent 把消息交给传输层」这一条链路。\n"
    "它不是产品代码，存在的理由是给 RepoLearn 的抓取 / 分析 / 升级三处提供一份可读、\n"
    "可逐字节比对的真代码。\n"
    "\n"
    "## 跑一下\n"
    "\n"
    "```bash\n"
    "python -m tiny.main\n"
    "```\n"
    "\n"
    "## 为什么只有四个文件\n"
    "\n"
    "夹具的价值在于「二次运行逐字节一致」：文件越少，「1 modified + 1 added + 1 removed」\n"
    "这条断言（M10 / T-UPG-2）就越不可能被无关改动污染。传输层具体是谁（总线还是路由器）\n"
    "由 `tiny/agent.py::default_bus()` 决定，调用方不需要知道。\n"
)

TINY_AGENT_V1 = (
    '"""TinyAgent：消息的发出方。\n'
    "\n"
    "传输层从 `default_bus()` 取，Agent 自己不认识 `MessageBus`——这条边界就是 v2 能把\n"
    "总线换成 `Router` 而调用方一行不改的原因。\n"
    '"""\n'
    "\n"
    "from tiny.bus import MessageBus\n"
    "\n"
    "\n"
    "def default_bus() -> MessageBus:\n"
    "    return MessageBus()\n"
    "\n"
    "\n"
    "class TinyAgent:\n"
    "    def __init__(self, name: str, bus: MessageBus | None = None) -> None:\n"
    "        self.name = name\n"
    "        self.bus = bus or default_bus()\n"
    "\n"
    "    def send(self, text: str) -> int:\n"
    "        return self.bus.publish(self.name, text)\n"
)

TINY_AGENT_V2 = (
    '"""TinyAgent：消息的发出方。\n'
    "\n"
    "v2 把传输层从 `MessageBus` 换成了 `Router`：构造签名与 `send()` 都没动，变的只是\n"
    "`default_bus()` 造出来的对象——「改动集中在两个函数里」正是我们希望 diff 呈现的样子。\n"
    '"""\n'
    "\n"
    "from tiny.router import Router\n"
    "\n"
    "\n"
    "def default_bus() -> Router:\n"
    "    return Router()\n"
    "\n"
    "\n"
    "class TinyAgent:\n"
    "    def __init__(self, name: str, bus: Router | None = None) -> None:\n"
    "        self.name = name\n"
    "        self.bus = bus or default_bus()\n"
    "\n"
    "    def send(self, text: str) -> int:\n"
    "        return self.bus.publish(self.name, text)\n"
    "\n"
    "    def received(self) -> list[tuple[str, str]]:\n"
    '        """v2 新增：别人说给我听的消息（v1 里只能自己去翻 bus.log）。"""\n'
    "        return [item for item in self.bus.log if item[0] != self.name]\n"
)

TINY_BUS = (
    '"""进程内消息总线：只保留「谁说了什么」的追加日志。\n'
    "\n"
    '刻意不用队列与线程：夹具里的代码要能被静态分析一眼读完，任何异步细节都会让\n'
    '"这份 diff 到底改了哪一行"变成需要调试的问题。\n'
    '"""\n'
    "\n"
    "\n"
    "class MessageBus:\n"
    "    def __init__(self) -> None:\n"
    "        self.log: list[tuple[str, str]] = []\n"
    "\n"
    "    def publish(self, sender: str, text: str) -> int:\n"
    '        """追加一条消息，返回投递后的消息总数（调用方用它做最朴素的重试判断）。"""\n'
    "        self.log.append((sender, text))\n"
    "        return len(self.log)\n"
)

TINY_ROUTER = (
    '"""Router：v2 新增的传输层，按发送者登记的处理函数做一次转发。\n'
    "\n"
    "它自己保留 `log`，因此不再需要 `tiny/bus.py`：一个只有四个文件的小仓库里，\n"
    '两份"追加日志"必然演化成两份不一致的历史。\n'
    '"""\n'
    "\n"
    "from collections.abc import Callable\n"
    "\n"
    "\n"
    "class Router:\n"
    "    def __init__(self) -> None:\n"
    "        self.log: list[tuple[str, str]] = []\n"
    "        self.routes: dict[str, Callable[[str], None]] = {}\n"
    "\n"
    "    def register(self, name: str, handler: Callable[[str], None]) -> None:\n"
    "        self.routes[name] = handler\n"
    "\n"
    "    def publish(self, sender: str, text: str) -> int:\n"
    "        self.log.append((sender, text))\n"
    "        handler = self.routes.get(sender)\n"
    "        if handler is not None:\n"
    "            handler(text)\n"
    "        return len(self.log)\n"
)

TINY_MAIN = (
    '"""最小可跑入口：两个 agent 共用一条总线，各说一句话。"""\n'
    "\n"
    "from tiny.agent import TinyAgent, default_bus\n"
    "\n"
    "\n"
    "def main() -> list[tuple[str, str]]:\n"
    "    bus = default_bus()\n"
    '    alice = TinyAgent("alice", bus)\n'
    '    bob = TinyAgent("bob", bus)\n'
    '    alice.send("hello")\n'
    '    bob.send("hi")\n'
    "    return bus.log\n"
    "\n"
    "\n"
    'if __name__ == "__main__":\n'
    "    print(main())\n"
)

TINY_V1 = {
    "README.md": TINY_README,
    "tiny/agent.py": TINY_AGENT_V1,
    "tiny/bus.py": TINY_BUS,
    "tiny/main.py": TINY_MAIN,
}

# v2 复用 TINY_README / TINY_MAIN 这两个**同一个对象**，而不是把内容抄一遍：
# "其余文件逐字节不变"于是成了代码结构上的事实，而不是靠人记住别手抖。
# `tiny/bus.py` 干脆不出现在这里——删除由"不存在"表达，这才是 removed。
TINY_V2 = {
    "README.md": TINY_README,
    "tiny/agent.py": TINY_AGENT_V2,
    "tiny/main.py": TINY_MAIN,
    "tiny/router.py": TINY_ROUTER,
}


def _dump(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    body = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    path.write_text(body, encoding="utf-8")


def _write_text(path: Path, text: str) -> None:
    """写文本夹具时显式钉住 `newline="\\n"`。

    `Path.write_text` 默认 `newline=None`，在 Windows 上会把 `\\n` 翻成 `\\r\\n`；而
    `manifest.json` 里记的是**字节**的 sha256——换行一旦随平台变化，
    `analysis/diff.py` 的按哈希比对照样会在另一半机器上得到"所有文件都变了"。
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)


def _snapshot_files(root: Path) -> list[Path]:
    return sorted((p for p in root.rglob("*") if p.is_file()), key=lambda p: p.relative_to(root).as_posix())


def _write_snapshot(name: str, files: dict[str, str]) -> Path:
    """落盘一份快照，并清掉上一轮遗留、这一轮不该存在的文件与空目录。

    为什么要清：v2 的"1 removed"是靠 `tiny/bus.py` **不存在**来表达的。若上一轮生成
    把它留在了 tiny_v2 里（比如手改过、或先在 v1 里生成过一次），测试会拿到一份
    "谁都没改过"的 diff，而断言仍然绿——夹具漂移里最难发现的一类。

    空目录一并删：有人对着夹具跑 `py_compile`/`import` 就会留下 `__pycache__`，
    它不进 git 却会出现在 tarball 与 tree 的快照清单里，让"文件数 = 快照文件数"这条
    最朴素的断言在一个干净的 CI 上通过、在本机上失败。
    """
    root = FIXTURES / "repos" / name
    for rel, text in files.items():
        _write_text(root / rel, text)
    keep = {(root / rel).resolve() for rel in files}
    for path in _snapshot_files(root):
        if path.resolve() not in keep:
            path.unlink()
    for path in sorted((p for p in root.rglob("*") if p.is_dir()), key=lambda p: len(p.parts), reverse=True):
        if not any(path.iterdir()):
            path.rmdir()
    return root


def _line_count(text: str) -> int:
    return len(text.splitlines())


def _patch_text(text: str, sign: str, header: str) -> str:
    """一段确定性的"补丁"：只取前 3 行。

    真 GitHub 才给完整 unified diff；这里给的是**形状**（`@@ ... @@` + 前导符号）。
    产品只把 `files` 当"变了几个文件"用，编造一份完整 patch 只会让夹具更难读。
    """
    lines = text.splitlines()[:3]
    body = "".join(f"{sign}{line}\n" for line in lines)
    return f"{header}\n{body}" if body else header


def _commit_files(files: dict[str, str], previous: dict[str, str] | None = None) -> list[dict]:
    """快照（对比上一版）→ GitHub 形状的 `files` 列表。

    规则与 `scripts/fake_github.py::changed_files` 逐条一致（两份实现刻意不互相导入：
    夹具生成器不该依赖一个测试服务器的模块）。若两条路给出不同结果，同一份 commit 在
    "夹具 JSON"和"运行时现造"上就会说不同的话，而 E2E 会以为自己在测另一边。
    """
    out: list[dict] = []
    for path in sorted(files):
        text = files[path]
        old = None if previous is None else previous.get(path)
        if old == text:
            continue  # 内容没变就不该出现在 commit.files 里（真 GitHub 也这样）
        if old is None:
            lines = _line_count(text)
            out.append(
                {
                    "filename": path,
                    "status": "added",
                    "additions": lines,
                    "deletions": 0,
                    "changes": lines,
                    "patch": _patch_text(text, "+", f"@@ -0,0 +1,{lines} @@"),
                }
            )
        else:
            new_lines, old_lines = _line_count(text), _line_count(old)
            out.append(
                {
                    "filename": path,
                    "status": "modified",
                    "additions": new_lines,
                    "deletions": old_lines,
                    "changes": new_lines + old_lines,
                    "patch": _patch_text(text, "+", f"@@ -1,{old_lines} +1,{new_lines} @@"),
                }
            )
    if previous is not None:
        for path in sorted(set(previous) - set(files)):
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


def _commit_payload(
    sha: str,
    date: str,
    message: str,
    files: dict[str, str],
    previous: dict[str, str] | None = None,
) -> dict:
    """`GET /repos/{o}/{r}/commits/{ref}` 的响应夹具（`CommitMeta` 只读其中四个字段）。"""
    return {
        "sha": sha,
        "commit": {"author": {"date": date}, "message": message},
        "html_url": f"https://github.com/microsoft/autogen/commit/{sha}",
        "files": _commit_files(files, previous),
    }


def _snapshot_manifest(name: str, files: dict[str, str]) -> dict:
    """快照的按哈希清单，给 `analysis/diff.py` 风格的 path + sha256 比对用。

    哈希取自**落盘字节**而不是内存里的字符串：清单的用途正是"断言磁盘上这份文件没被
    改过"，读内存就等于自己给自己发合格证。
    """
    root = FIXTURES / "repos" / name
    rows = []
    for rel in sorted(files):
        data = (root / rel).read_bytes()
        rows.append({"path": rel, "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)})
    return {"root": root.relative_to(ROOT).as_posix(), "files": rows}


def _github_manifest() -> dict:
    return {
        "commits": {"v1": SHA_V1, "v2": SHA_V2},
        "snapshots": {
            "tiny_v1": _snapshot_manifest("tiny_v1", TINY_V1),
            "tiny_v2": _snapshot_manifest("tiny_v2", TINY_V2),
        },
    }


def _snapshot_digests() -> dict[Path, str]:
    """`tests/fixtures/repos/` 下全部文件的字节哈希（`--check` 用它抓夹具漂移）。"""
    root = FIXTURES / "repos"
    if not root.exists():
        return {}
    return {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in _snapshot_files(root)}


def main() -> int:
    parser = argparse.ArgumentParser(description="生成确定性测试夹具")
    parser.add_argument("--check", action="store_true", help="只校验现有夹具是否最新")
    args = parser.parse_args()

    before = {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in FIXTURES.rglob("*.json")} if FIXTURES.exists() else {}
    before_snapshots = _snapshot_digests()

    _dump(FIXTURES / "github" / "repo.json", GITHUB_REPO)
    _dump(FIXTURES / "github" / "commit.json", GITHUB_COMMIT)
    _dump(FIXTURES / "golden" / "curriculum.json", GOLDEN_CURRICULUM)
    _dump(FIXTURES / "golden" / "trace.json", GOLDEN_TRACE)
    _dump(FIXTURES / "sources" / "index.json", {k: v for k, v in sorted(SOURCE_SNIPPETS.items())})
    for rel, content in SOURCE_SNIPPETS.items():
        target = FIXTURES / "sources" / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")

    # --- 追加产物：双版本快照 + 假 GitHub 的 commit/manifest 夹具 -------------
    # 全部追加在末尾，且不改动上面任何一行：既有产物的字节是已入库的契约，
    # "顺手重排一下"会让每个夹具在 git 里都变成整文件重写。
    _write_snapshot("tiny_v1", TINY_V1)
    _write_snapshot("tiny_v2", TINY_V2)
    _dump(
        FIXTURES / "github" / "commit_v1.json",
        _commit_payload(SHA_V1, COMMIT_DATE_V1, COMMIT_MESSAGE_V1, TINY_V1),
    )
    _dump(
        FIXTURES / "github" / "commit_v2.json",
        _commit_payload(SHA_V2, COMMIT_DATE_V2, COMMIT_MESSAGE_V2, TINY_V2, TINY_V1),
    )
    _dump(FIXTURES / "github" / "manifest.json", _github_manifest())

    after = {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in FIXTURES.rglob("*.json")}
    if args.check:
        drift = [str(p.relative_to(ROOT)) for p in after if before.get(p) not in (None, after[p])]
        after_snapshots = _snapshot_digests()
        drift += [
            str(p.relative_to(ROOT))
            for p in after_snapshots
            if before_snapshots.get(p) not in (None, after_snapshots[p])
        ]
        drift += [str(p.relative_to(ROOT)) for p in before_snapshots if p not in after_snapshots]
        if drift:
            print("fixtures drifted: " + ", ".join(drift))
            return 1
        print("fixtures up to date")
        return 0
    print(f"wrote {len(after)} json fixtures under {FIXTURES.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

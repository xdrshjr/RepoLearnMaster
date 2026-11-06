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


def _dump(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    body = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    path.write_text(body, encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="生成确定性测试夹具")
    parser.add_argument("--check", action="store_true", help="只校验现有夹具是否最新")
    args = parser.parse_args()

    before = {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in FIXTURES.rglob("*.json")} if FIXTURES.exists() else {}

    _dump(FIXTURES / "github" / "repo.json", GITHUB_REPO)
    _dump(FIXTURES / "github" / "commit.json", GITHUB_COMMIT)
    _dump(FIXTURES / "golden" / "curriculum.json", GOLDEN_CURRICULUM)
    _dump(FIXTURES / "golden" / "trace.json", GOLDEN_TRACE)
    _dump(FIXTURES / "sources" / "index.json", {k: v for k, v in sorted(SOURCE_SNIPPETS.items())})
    for rel, content in SOURCE_SNIPPETS.items():
        target = FIXTURES / "sources" / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")

    after = {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in FIXTURES.rglob("*.json")}
    if args.check:
        drift = [str(p.relative_to(ROOT)) for p in after if before.get(p) not in (None, after[p])]
        if drift:
            print("fixtures drifted: " + ", ".join(drift))
            return 1
        print("fixtures up to date")
        return 0
    print(f"wrote {len(after)} json fixtures under {FIXTURES.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

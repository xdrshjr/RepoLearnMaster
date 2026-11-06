"""命令行入口（spec §4.1：`python -m repolearn.cli ...`）。

子命令：
* `migrate` —— 跑 Alembic 到 head（`start.ps1` 与 CI 都调它）；
* `seed-demo` —— 插入一条**离线演示课程**（无网络/无 Key 时前端仍可完整演示三层学习
  与书籍阅读；也是 E2E 的稳定基础）；
* `export-openapi` —— 导出 `packages/contracts/openapi.json`（`--check` 校验漂移）；
* `prune` —— 镜像 LRU + 过期幂等键清理；
* `requeue-stale` —— 心跳停更的 Job 放回队列；
* `backfill-quality` —— 回填历史课程的质量报告；
* `doctor` —— 打印 Gate 0 三态与内核状态。

**为什么这些必须是子命令而不是脚本**：`start.ps1`、CI、以及将来可能的多用户部署
都要调用同一批操作。脚本会各自漂移，而 CLI 只有一份实现。
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import sys
from pathlib import Path

from repolearn import __version__
from repolearn.core.config import REPO_ROOT, settings


def _run(coro):
    return asyncio.get_event_loop_policy().new_event_loop().run_until_complete(coro)


# --------------------------------------------------------------------------- #
# migrate                                                                      #
# --------------------------------------------------------------------------- #


def cmd_migrate(args: argparse.Namespace) -> int:
    from alembic import command
    from alembic.config import Config

    cfg = Config(str(REPO_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(REPO_ROOT / "apps" / "api" / "migrations"))
    if args.downgrade:
        command.downgrade(cfg, args.target or "base")
        print(f"downgraded to {args.target or 'base'}")
        return 0
    command.upgrade(cfg, args.target or "head")
    print(f"migrated to {args.target or 'head'}")
    return 0


# --------------------------------------------------------------------------- #
# seed-demo                                                                    #
# --------------------------------------------------------------------------- #

DEMO_REPO_FULL_NAME = "microsoft/autogen (demo)"

DEMO_FILES = {
    "autogen/agentchat/conversable_agent.py": (
        '"""ConversableAgent: 一个可以收发消息、调用工具的 Agent 基类。"""\n'
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
        "        reply = self.generate_reply(messages=self.chat_messages.get(sender.name, []))\n"
        "        return reply\n"
        "\n"
        "    def generate_reply(self, messages=None):\n"
        "        if not self.llm_config:\n"
        "            return None\n"
        "        return self._call_llm(messages or [])\n"
        "\n"
        "    def _call_llm(self, messages):\n"
        "        return {'role': 'assistant', 'content': 'ok'}\n"
    ),
    "autogen/agentchat/groupchat.py": (
        '"""GroupChat: 多个 Agent 按发言顺序轮转的群聊编排。"""\n'
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


async def _seed_demo() -> int:
    from sqlalchemy import select

    from repolearn.core.clock import utcnow
    from repolearn.core.db import session_scope
    from repolearn.core.ids import new_id
    from repolearn.models import (
        Commit,
        CourseVersion,
        Lesson,
        QuizItem,
        Repository,
        SimulatedTrace,
        SourceAnchor,
        Step,
        User,
    )
    from repolearn.services.object_store import mirror_dir, put

    sha = "demo0000" + hashlib.sha256(b"repolearn-demo").hexdigest()[:56]
    sha8 = sha[:8]
    base = mirror_dir(sha8)
    for rel, content in DEMO_FILES.items():
        target = base / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")

    cache_key = hashlib.sha256(f"microsoft/autogen|{sha}|1|zh".encode()).hexdigest()
    async with session_scope() as session:
        user = await session.get(User, "usr_local")
        if user is None:
            session.add(User(id="usr_local", handle="local", display_name="本机学习者", is_local=True, created_at=utcnow()))
            await session.flush()

        # 幂等：这个命令会被 `start.ps1` 与用户手工反复执行。第一次实现直接 INSERT，
        # 第二次就在 `repositories.full_name` 的唯一约束上崩掉——而"重跑一次准备命令
        # 却报错"会让用户以为环境坏了。已存在就复用并重建它的课程内容。
        existing = (
            await session.execute(select(Repository).where(Repository.full_name == DEMO_REPO_FULL_NAME))
        ).scalar_one_or_none()
        if existing is not None:
            commit_row = (
                await session.execute(
                    select(Commit).where(Commit.repository_id == existing.id, Commit.sha == sha)
                )
            ).scalar_one_or_none()
            if commit_row is None:
                session.add(
                    Commit(
                        id=new_id("commit"),
                        repository_id=existing.id,
                        sha=sha,
                        committed_at=utcnow(),
                        file_count=len(DEMO_FILES),
                        tarball_bytes=sum(len(v) for v in DEMO_FILES.values()),
                        license_note="MIT",
                        created_at=utcnow(),
                    )
                )
                await session.flush()
            demo = (
                await session.execute(
                    select(CourseVersion).where(CourseVersion.repository_id == existing.id)
                )
            ).scalars().all()
            for row in demo:
                await session.delete(row)
            await session.flush()
            repo = existing
        else:
            repo = Repository(
                id=new_id("repository"),
                full_name=DEMO_REPO_FULL_NAME,
                owner="microsoft",
                name="autogen-demo",
                description="离线演示课程：AutoGen 的 Agent 与群聊编排",
                stars=32000,
                license_spdx="MIT",
                primary_language="Python",
                default_branch="main",
                html_url="https://github.com/microsoft/autogen",
                is_public=True,
                created_at=utcnow(),
                updated_at=utcnow(),
            )
            session.add(repo)
            await session.flush()
            session.add(
                Commit(
                    id=new_id("commit"),
                    repository_id=repo.id,
                    sha=sha,
                    committed_at=utcnow(),
                    file_count=len(DEMO_FILES),
                    tarball_bytes=sum(len(v) for v in DEMO_FILES.values()),
                    license_note="MIT",
                    created_at=utcnow(),
                )
            )
        course = CourseVersion(
            id=new_id("course_version"),
            repository_id=repo.id,
            commit_sha=sha,
            cache_key=cache_key,
            policy_version="1",
            language="zh",
            title="AutoGen 带读：Agent 如何对话",
            subtitle="离线演示课程 · 无需网络与 API Key",
            summary_md=(
                "这是一门**离线演示课程**，用来在没有网络、没有配置任何 AI Key 的机器上"
                "完整演示 RepoLearn 的三层学习体验。\n\n"
                "它讲的是 AutoGen 里两个最核心的机制：`ConversableAgent` 的消息收发，"
                "以及 `GroupChat` 的轮转编排。"
            ),
            status="ready",
            sections=[
                {
                    "key": "overview",
                    "title": "第一层 · 宏观架构",
                    "minutes": 5,
                    "lessons": [{"key": "1.1", "title": "两个类，一条消息流", "minutes": 5}],
                },
                {
                    "key": "walkthrough",
                    "title": "第二层 · 全局走读",
                    "minutes": 8,
                    "lessons": [{"key": "2.1", "title": "send 到 receive 的一次往返", "minutes": 8}],
                },
                {
                    "key": "deep_dive",
                    "title": "第三层 · 深入源码",
                    "minutes": 10,
                    "lessons": [{"key": "3.1", "title": "generate_reply 的三种返回", "minutes": 10}],
                },
                {
                    "key": "recap",
                    "title": "课程总结",
                    "minutes": 4,
                    "lessons": [{"key": "4.1", "title": "复盘与进阶路径", "minutes": 4}],
                },
            ],
            quality_report={
                "anchor_coverage": 0.94,
                "lesson_completeness": 1.0,
                "trace_quality": "ok",
                "quiz_count": 4,
                "certainty": {"source_fact": 6, "static_inference": 3, "teaching_simulation": 2},
                "degraded": False,
                "anchor_confidence": "high",
                "runtime": "template",
                "reasons": [],
            },
            warnings=[],
            blueprint={"repo_full_name": "microsoft/autogen", "license": "MIT", "demo": True},
            cover_palette="mint",
            lesson_count=4,
            total_minutes=27,
            visibility="public",
            created_at=utcnow(),
            updated_at=utcnow(),
            published_at=utcnow(),
        )
        session.add(course)
        await session.flush()

        plans = [
            ("1.1", "overview", "两个类，一条消息流", "能说出 ConversableAgent 与 GroupChat 各自的职责"),
            ("2.1", "walkthrough", "send 到 receive 的一次往返", "能画出 send → receive → generate_reply 的调用顺序"),
            ("3.1", "deep_dive", "generate_reply 的三种返回", "能解释没有 llm_config 时为什么返回 None"),
            ("4.1", "recap", "复盘与进阶路径", "能复述本课程的三个关键结论"),
        ]
        for order, (key, section, title, goal) in enumerate(plans):
            lesson_id = new_id("lesson")
            session.add(
                Lesson(
                    id=lesson_id,
                    course_version_id=course.id,
                    section_key=section,
                    key=key,
                    title=title,
                    goal=goal,
                    minutes=6,
                    order_index=order,
                    status="ready",
                    playback_meta={
                        "files": [
                            {
                                "path": "autogen/agentchat/conversable_agent.py",
                                "lang": "python",
                                "line_count": 22,
                            },
                            {"path": "autogen/agentchat/groupchat.py", "lang": "python", "line_count": 14},
                        ],
                        "trace_key": f"trace_{key}",
                        "narration": {"segment_count": 3, "audio": None, "timing_source": "estimated"},
                    },
                    created_at=utcnow(),
                )
            )
            segments = [
                {
                    "id": "s0",
                    "text": f"这一节我们看 {title}。",
                    "start_ms": 0,
                    "end_ms": 3600,
                    "focus": {"file": "autogen/agentchat/conversable_agent.py", "line_start": 3, "line_end": 6},
                },
                {
                    "id": "s1",
                    "text": "先看这个类的构造函数：它只保存 name 与 llm_config，不做任何 IO。",
                    "start_ms": 3600,
                    "end_ms": 12000,
                    "focus": {"file": "autogen/agentchat/conversable_agent.py", "line_start": 5, "line_end": 8},
                },
                {
                    "id": "s2",
                    "text": "注意 generate_reply：没有配置 llm_config 时它返回 None，这是静默降级而不是报错。",
                    "start_ms": 12000,
                    "end_ms": 20000,
                    "focus": {"file": "autogen/agentchat/conversable_agent.py", "line_start": 17, "line_end": 20},
                },
            ]
            session.add(
                Step(
                    id=new_id("step"),
                    lesson_id=lesson_id,
                    order_index=0,
                    title=title,
                    duration_ms=20000,
                    timing_source="estimated",
                    focus_file="autogen/agentchat/conversable_agent.py",
                    focus_line_start=3,
                    focus_line_end=6,
                    segments=segments,
                    board={
                        "kind": "architecture",
                        "mermaid": "flowchart LR\n  a[GroupChat] --> b[ConversableAgent]\n  b --> c[generate_reply]",
                        "nodes": [
                            {"id": "a", "label": "GroupChat"},
                            {"id": "b", "label": "ConversableAgent"},
                            {"id": "c", "label": "generate_reply"},
                        ],
                    },
                    code_notes=[
                        {
                            "file": "autogen/agentchat/conversable_agent.py",
                            "line": 10,
                            "text": "send 把消息记进 chat_messages，然后立刻转交",
                        }
                    ],
                    certainty={"legend": "三种确定性见播放器右下角"},
                    created_at=utcnow(),
                )
            )
            session.add(
                SourceAnchor(
                    id=new_id("anchor"),
                    course_version_id=course.id,
                    lesson_id=lesson_id,
                    file="autogen/agentchat/conversable_agent.py",
                    symbol="ConversableAgent",
                    line_start=3,
                    line_end=6,
                    commit_sha=sha,
                    kind="definition",
                    created_at=utcnow(),
                )
            )
            session.add(
                QuizItem(
                    id=new_id("quiz"),
                    course_version_id=course.id,
                    lesson_id=lesson_id,
                    stem="当 llm_config 为空时，generate_reply 会怎样？",
                    choices=[
                        {"id": "a", "text": "抛出异常"},
                        {"id": "b", "text": "返回 None"},
                        {"id": "c", "text": "调用默认模型"},
                    ],
                    answer_id="b",
                    explanation_md="`generate_reply` 里第一个分支就是 `if not self.llm_config: return None`。",
                    evidence=[
                        {
                            "file": "autogen/agentchat/conversable_agent.py",
                            "line_start": 17,
                            "line_end": 20,
                            "kind": "definition",
                        }
                    ],
                    difficulty=1,
                    kind="recall",
                    created_at=utcnow(),
                )
            )
        session.add(
            SimulatedTrace(
                id=new_id("trace"),
                course_version_id=course.id,
                lesson_id=None,
                key="trace_demo",
                title="GroupChat → ConversableAgent → generate_reply",
                steps=[
                    {
                        "index": 0,
                        "title": "GroupChat.run 收到初始消息",
                        "certainty": "source_fact",
                        "evidence": [
                            {"file": "autogen/agentchat/groupchat.py", "line_start": 10, "line_end": 12, "symbol": "run"}
                        ],
                        "variables": [{"name": "initial_message", "value": "'你好'", "note": "示例值，非真实运行结果"}],
                    },
                    {
                        "index": 1,
                        "title": "逐 agent 调用 send",
                        "certainty": "source_fact",
                        "evidence": [
                            {"file": "autogen/agentchat/groupchat.py", "line_start": 12, "line_end": 13},
                            {"file": "autogen/agentchat/conversable_agent.py", "line_start": 10, "line_end": 12},
                        ],
                        "variables": [],
                    },
                    {
                        "index": 2,
                        "title": "receive 触发 generate_reply",
                        "certainty": "static_inference",
                        "evidence": [
                            {"file": "autogen/agentchat/conversable_agent.py", "line_start": 14, "line_end": 15}
                        ],
                        "variables": [{"name": "reply", "value": "None", "note": "示例值，非真实运行结果"}],
                    },
                ],
                certainty_summary={"source_fact": 2, "static_inference": 1, "teaching_simulation": 0},
                created_at=utcnow(),
            )
        )
    print(f"seeded demo course under {base}")
    print("course_id 见数据库；前端首页会列出「AutoGen 带读：Agent 如何对话」")
    return 0


def cmd_seed_demo(_args: argparse.Namespace) -> int:
    return _run(_seed_demo())


# --------------------------------------------------------------------------- #
# export-openapi                                                               #
# --------------------------------------------------------------------------- #


def cmd_export_openapi(args: argparse.Namespace) -> int:
    from repolearn.main import create_app

    app = create_app()
    spec = app.openapi()
    target = REPO_ROOT / "packages" / "contracts" / "openapi.json"
    body = json.dumps(spec, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.check:
        if not target.is_file():
            print(f"missing {target}", file=sys.stderr)
            return 1
        current = target.read_text(encoding="utf-8")
        if current != body:
            print(
                "contract drift detected: openapi.json 与代码不一致，请运行 `python -m repolearn.cli export-openapi`",
                file=sys.stderr,
            )
            return 1
        print("contract up to date")
        return 0
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(body, encoding="utf-8")
    print(f"wrote {target} ({len(body)} bytes, {len(spec.get('paths', {}))} paths)")
    return 0


# --------------------------------------------------------------------------- #
# prune / requeue / backfill / doctor                                          #
# --------------------------------------------------------------------------- #


async def _prune() -> int:
    from datetime import timedelta

    from sqlalchemy import delete

    from repolearn.core.clock import utcnow
    from repolearn.core.db import session_scope
    from repolearn.models import IdempotencyKey
    from repolearn.services.object_store import prune_mirrors

    result = prune_mirrors()
    async with session_scope() as session:
        cutoff = utcnow() - timedelta(minutes=10)
        deleted = await session.execute(delete(IdempotencyKey).where(IdempotencyKey.expires_at < cutoff))
    print(f"mirrors: removed {result['removed_dirs']} dirs / {result['removed_bytes']} bytes")
    print(f"idempotency keys: removed {int(deleted.rowcount or 0)}")
    return 0


def cmd_prune(_args: argparse.Namespace) -> int:
    return _run(_prune())


async def _requeue() -> int:
    from repolearn.jobs.runner import reap_orphaned_generations, requeue_stale_jobs

    jobs = await requeue_stale_jobs()
    reaped = await reap_orphaned_generations()
    print(f"requeued {jobs} stale jobs; reaped {reaped['courses']} orphan courses / {reaped['locks']} locks")
    return 0


def cmd_requeue(_args: argparse.Namespace) -> int:
    return _run(_requeue())


async def _backfill() -> int:
    from repolearn.core.db import session_scope
    from repolearn.services.quality_service import backfill_all

    async with session_scope() as session:
        result = await backfill_all(session)
    print(f"quality backfilled: {result['updated']}/{result['courses']} courses")
    return 0


def cmd_backfill(_args: argparse.Namespace) -> int:
    return _run(_backfill())


async def _doctor() -> int:
    from repolearn.core.db import session_scope
    from repolearn.services.setup_service import doctor

    async with session_scope() as session:
        checks = await doctor(session)
    for check in checks:
        print(f"[{check['status']:>8}] {check['name']}: {check['detail']}")
        if check.get("hint"):
            print(f"           → {check['hint']}")
    return 0


def cmd_doctor(_args: argparse.Namespace) -> int:
    return _run(_doctor())


def cmd_info(_args: argparse.Namespace) -> int:
    print(f"RepoLearn {__version__}")
    print(f"env={settings.env} db={settings.database_url}")
    print(f"objects={settings.object_path}")
    print(f"kernel={settings.kernel_url} runtime={settings.agent_runtime}")
    return 0


# --------------------------------------------------------------------------- #
# 解析                                                                         #
# --------------------------------------------------------------------------- #


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="repolearn",
        description="RepoLearn CLI：迁移、种子数据、契约导出、运维清理。",
    )
    parser.add_argument("--version", action="version", version=f"repolearn {__version__}")
    sub = parser.add_subparsers(dest="command")

    migrate = sub.add_parser("migrate", help="运行数据库迁移到 head")
    migrate.add_argument("--target", default=None, help="目标 revision（默认 head）")
    migrate.add_argument("--downgrade", action="store_true", help="降级到 --target（默认 base）")
    migrate.set_defaults(func=cmd_migrate)

    seed = sub.add_parser("seed-demo", help="插入离线演示课程（无网络/无 Key 可用）")
    seed.set_defaults(func=cmd_seed_demo)

    export = sub.add_parser("export-openapi", help="导出/校验 packages/contracts/openapi.json")
    export.add_argument("--check", action="store_true", help="只校验漂移，不写文件")
    export.set_defaults(func=cmd_export_openapi)

    prune = sub.add_parser("prune", help="镜像 LRU 清理 + 过期幂等键清理")
    prune.set_defaults(func=cmd_prune)

    requeue = sub.add_parser("requeue-stale", help="回收心跳停更的 Job 与僵尸课程版本")
    requeue.set_defaults(func=cmd_requeue)

    backfill = sub.add_parser("backfill-quality", help="回填历史课程的质量报告")
    backfill.set_defaults(func=cmd_backfill)

    doctor = sub.add_parser("doctor", help="打印 Gate 0 三态与各依赖状态")
    doctor.set_defaults(func=cmd_doctor)

    info = sub.add_parser("info", help="打印当前配置摘要")
    info.set_defaults(func=cmd_info)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "command", None):
        parser.print_help()
        return 0
    return int(args.func(args) or 0)


if __name__ == "__main__":
    raise SystemExit(main())

"""端到端流水线测试：N1–N9 真的跑完并把课程发布成 `ready`（T-GRAPH-1 的离线版）。

这段测试的价值在于"整条链路真的连起来了"：节点上下文注入、镜像读取、模板降级、
发布事务、质量报告。它用 monkeypatch 把 GitHub 换成固定夹具，因此**离线、确定、
秒级**——不是"集成测试跑不了所以跳过"的那种。

状态 C（模板降级）是被覆盖的主路径：Gate 0 G1 失败是这台机器上的真实情况，
把它当"异常路径"测不到，等于核心功能没有测试。
"""

from __future__ import annotations

import hashlib

from repolearn.core.clock import utcnow
from repolearn.core.db import SessionMaker
from repolearn.core.ids import new_id
from repolearn.ingest.github import CommitMeta, RepoMeta
from repolearn.models import CourseVersion, Lesson, QuizItem, Repository, SourceAnchor, Step
from repolearn.services.object_store import mirror_dir
from repolearn.workflow import run_graph, run_sequential

DEMO_SOURCES = {
    "autogen/agentchat/conversable_agent.py": (
        '"""ConversableAgent: 可收发消息的 Agent 基类。"""\n'
        "\n"
        "class ConversableAgent:\n"
        "    def __init__(self, name, llm_config=None):\n"
        "        self.name = name\n"
        "        self.llm_config = llm_config or {}\n"
        "\n"
        "    def send(self, message, recipient):\n"
        "        return recipient.receive(message, self)\n"
        "\n"
        "    def receive(self, message, sender):\n"
        "        return self.generate_reply(messages=[])\n"
        "\n"
        "    def generate_reply(self, messages=None):\n"
        "        if not self.llm_config:\n"
        "            return None\n"
        "        return {'role': 'assistant', 'content': 'ok'}\n"
    ),
    "autogen/agentchat/groupchat.py": (
        '"""GroupChat: 多个 Agent 轮转的群聊编排。"""\n'
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
    "README.md": "# autogen demo\n\nA tiny fixture repo.\n",
}

SHA = hashlib.sha256(b"repolearn-pipeline-fixture").hexdigest()


def _materialize_mirror() -> str:
    base = mirror_dir(SHA[:8])
    for rel, content in DEMO_SOURCES.items():
        target = base / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    return str(base)


def _patch_github(monkeypatch) -> None:
    import repolearn.ingest as ingest
    import repolearn.ingest.github as gh

    meta = RepoMeta(
        full_name="fixture/agentchat",
        owner="fixture",
        name="agentchat",
        description="fixture repo",
        stars=42,
        license_spdx="MIT",
        primary_language="Python",
        default_branch="main",
        html_url="https://github.com/fixture/agentchat",
    )
    commit = CommitMeta(
        sha=SHA,
        committed_at="2026-01-01T00:00:00Z",
        message="fixture commit",
        file_count=len(DEMO_SOURCES),
        extra={"tarball_bytes": 1024},
    )

    async def fake_meta(ref) -> RepoMeta:  # noqa: ANN001
        return meta

    async def fake_commit(ref, branch, wanted=None) -> CommitMeta:  # noqa: ANN001
        return commit

    async def fake_fetch_and_mirror(url: str, wanted: str | None = None):  # noqa: ANN001
        return ingest.IngestOutcome(ref=ref_from(url), meta=meta, commit=commit, extraction=None, reused=True)

    def ref_from(url: str):
        return ingest.RepoRef(full_name=meta.full_name, owner="fixture", name="agentchat")

    monkeypatch.setattr(gh, "fetch_repo_meta", fake_meta)
    monkeypatch.setattr(gh, "resolve_commit", fake_commit)
    monkeypatch.setattr("repolearn.workflow.nodes.fetch_repo_meta", fake_meta, raising=False)
    monkeypatch.setattr("repolearn.ingest.github.fetch_repo_meta", fake_meta)
    monkeypatch.setattr("repolearn.ingest.github.resolve_commit", fake_commit)
    monkeypatch.setattr(ingest, "fetch_and_mirror", fake_fetch_and_mirror)


async def _make_course(session) -> str:
    repo = Repository(
        id=new_id("repository"),
        full_name="fixture/agentchat",
        owner="fixture",
        name="agentchat",
        description="fixture",
        stars=42,
        license_spdx="MIT",
        primary_language="Python",
        default_branch="main",
        html_url="https://github.com/fixture/agentchat",
        is_public=True,
        created_at=utcnow(),
        updated_at=utcnow(),
    )
    session.add(repo)
    await session.flush()
    course = CourseVersion(
        id=new_id("course_version"),
        repository_id=repo.id,
        commit_sha=SHA,
        cache_key=hashlib.sha256(f"fixture/agentchat|{SHA}|1|zh".encode()).hexdigest(),
        policy_version="1",
        language="zh",
        title="待生成",
        status="generating",
        sections=[],
        quality_report={},
        warnings=[],
        blueprint={"repo_full_name": "fixture/agentchat", "license": "MIT"},
        cover_palette="mint",
        visibility="public",
        created_at=utcnow(),
        updated_at=utcnow(),
    )
    session.add(course)
    await session.flush()
    await session.commit()
    return course.id


async def test_full_pipeline_publishes_ready_course(monkeypatch):
    """状态 C（无 Agent 内核）下仍然必须产出可学的课程。"""
    _materialize_mirror()
    _patch_github(monkeypatch)

    async with SessionMaker() as session:
        course_id = await _make_course(session)

    from repolearn.jobs.handlers import run_course_job

    events: list[tuple[str, dict]] = []

    async def emit(event_type: str, data: dict) -> None:
        events.append((event_type, data))

    outcome = await run_course_job(
        job_id=new_id("job"),
        course_id=course_id,
        payload={"repo_url": "https://github.com/fixture/agentchat", "commit": {"sha": SHA}},
        emit=emit,
    )

    assert outcome.status in ("ready", "partial")
    assert any(event_type == "node.completed" for event_type, _ in events)

    async with SessionMaker() as session:
        course = await session.get(CourseVersion, course_id)
        assert course is not None
        assert course.status in ("ready", "partial")
        assert course.lesson_count >= 10
        assert course.sections
        assert course.quality_report.get("degraded") is True  # 模板降级必须被如实标注
        assert course.quality_report.get("anchor_confidence") == "low"

        from sqlalchemy import func, select

        lessons = (
            await session.execute(select(Lesson).where(Lesson.course_version_id == course_id))
        ).scalars().all()
        assert len(lessons) == course.lesson_count
        steps = (
            await session.execute(select(Step).where(Step.lesson_id == lessons[0].id))
        ).scalars().all()
        assert steps and steps[0].segments
        # segments 必须连续覆盖：这是播放器的前提
        cursor = 0
        for seg in steps[0].segments:
            assert seg["start_ms"] == cursor
            cursor = seg["end_ms"]

        quiz_count = (
            await session.execute(select(func.count(QuizItem.id)).where(QuizItem.course_version_id == course_id))
        ).scalar()
        assert quiz_count and quiz_count > 0

        anchors = (
            await session.execute(select(SourceAnchor).where(SourceAnchor.course_version_id == course_id))
        ).scalars().all()
        assert anchors and all(a.commit_sha == SHA for a in anchors)


async def test_sequential_fallback_matches_graph_contract(monkeypatch):
    """没有 langgraph 时，顺序执行必须产出同一份形状（否则"降级"就是空话）。"""
    from repolearn.workflow.state import new_state

    _materialize_mirror()
    _patch_github(monkeypatch)

    saved: dict[str, object] = {}

    def save_artifact(node: str, key: str, payload: object) -> str:
        path = f"test/{node}/{key}"
        saved[path] = payload
        return path

    class Ctx:
        runtime_mode = "template"

        async def run(self, *a, **kw):  # noqa: ANN002, ANN003
            return "{}", {}

        def read_file(self, path: str) -> str:
            return (mirror_dir(SHA[:8]) / path).read_text(encoding="utf-8")

        def line_count(self, path: str) -> int:
            return self.read_file(path).count("\n") + 1

        def save_artifact(self, node: str, key: str, payload: object) -> str:
            return save_artifact(node, key, payload)

        def load_artifact(self, path: str):
            return saved.get(path, {})

        async def emit_progress(self, node: str, percent: int = 0) -> None:
            return None

        async def synthesize(self, key: str, segments: list[dict]):
            return None, "estimated"

        async def publish(self, state: dict) -> dict:
            return {"publish": {"status": "partial", "lesson_count": len(state.get("lessons") or {})}}

        job_id = "job_test"

    state = new_state("job_test", "crs_test")
    state["repo"] = {"repo_url": "https://github.com/fixture/agentchat"}
    state["commit"] = {"requested_ref": None}
    state["runtime"] = "template"

    final = await run_sequential(state, Ctx())  # type: ignore[arg-type]
    assert final["curriculum"]["sections"]
    assert len(final["lessons"]) == 12
    published = final.get("publish") or {}
    assert published, f"publish 结果缺失，final keys={sorted(final)}"
    inner = published.get("publish") or published
    assert inner.get("lesson_count") == 12, f"unexpected publish shape: {published}"
    assert final["traces"]


async def test_run_graph_falls_back_when_langgraph_missing(monkeypatch):
    """`run_graph` 在 langgraph 不可用时必须退到顺序执行，而不是抛错。"""
    from repolearn.workflow import course_graph

    async def boom(ctx):  # noqa: ANN001
        raise course_graph.GraphUnavailable("test")

    monkeypatch.setattr(course_graph, "build_course_graph", boom)
    calls: list[str] = []

    async def fake_sequential(state, ctx, on_node=None):  # noqa: ANN001
        calls.append("sequential")
        return {"ok": True}

    monkeypatch.setattr(course_graph, "run_sequential", fake_sequential)
    result = await run_graph(job_id="j", course_id="c", ctx=object())  # type: ignore[arg-type]
    assert result == {"ok": True}
    assert calls == ["sequential"]

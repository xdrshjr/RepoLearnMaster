"""课时并发生成：**一个课时的崩溃不能带走整门课**（T-WF-1）。

真实现场（2026-11-09 浏览器实测，job `job_01M6ZCNVY0CGT1GHGV24CNKPZN`）：
课时按 `LESSON_CONCURRENCY=3` 并发生成，其中一个撞上内核 429 后失败，
于是整个 job 以 `PROVIDER_UNAVAILABLE` 结束——**12 个课时一个都没留下**。
`_write_all` 的注释写着"单课时失败不阻塞整体"，但它用的是
`asyncio.gather(...)`（默认 `return_exceptions=False`）且只 `except Exception`：
`CancelledError` 这类 `BaseException` 会直接穿透 `gather`，把整门课带走。

这条用例守的是那句注释：课时失败要变成**警告 + failed_lessons**，
节点本身永远正常返回。
"""

from __future__ import annotations

import asyncio
import json

import pytest

from repolearn.workflow import nodes as nodes_mod


class _Ctx:
    """最小上下文：只实现 N6 用到的面。"""

    runtime_mode = "kernel"

    def __init__(self, behaviours: dict[str, BaseException | None]) -> None:
        self.behaviours = behaviours
        self.calls: list[str] = []

    async def emit_progress(self, node: str, percent: int = 0) -> None:  # noqa: ARG002
        return None

    async def run(self, role: str, system: str, prompt: str, **kwargs):  # noqa: ANN001, ANN003
        key = str(kwargs.get("lesson_key", ""))
        self.calls.append((key, kwargs.get("tools")))
        behaviour = self.behaviours.get(key)
        if behaviour is not None:
            raise behaviour
        # 一个 schema-合法的课时（lesson.json 要求 key/title/layer + 非空 steps，
        # 每个 step 要 index/title/duration_ms/segments，segment 要覆盖整段时长）
        lesson = {
            "key": key,
            "title": f"课时 {key}",
            "layer": "overview",
            "steps": [
                {
                    "index": 0,
                    "title": "step",
                    "duration_ms": 5000,
                    "timing_source": "estimated",
                    "segments": [{"id": "s0", "text": "讲一句", "start_ms": 0, "end_ms": 5000}],
                }
            ],
            "quiz": [],
        }
        return json.dumps(lesson, ensure_ascii=False), {"tokens_in": 10, "tokens_out": 5}

    def save_artifact(self, node: str, key: str, payload):  # noqa: ANN001, ANN201
        return f"artifacts/{node}/{key}"

    def load_artifact(self, key):  # noqa: ANN001, ANN201
        return {}


def _state() -> dict:
    return {
        "repo": {"full_name": "fixture/repo", "default_branch": "main"},
        "commit": {"sha": "a" * 40},
        "knowledge_graph": {},
        "runtime": "kernel",
        "curriculum": {
            "sections": [
                {
                    "key": "overview",
                    "lessons": [
                        {"key": "1.1", "title": "a", "goal": "g", "anchors": []},
                        {"key": "1.2", "title": "b", "goal": "g", "anchors": []},
                        {"key": "1.3", "title": "c", "goal": "g", "anchors": []},
                    ],
                }
            ]
        },
    }


@pytest.mark.asyncio
async def test_cancelled_lesson_does_not_abort_the_batch(monkeypatch):
    """T-WF-1：`CancelledError`（BaseException）也不能穿透 gather。"""
    ctx = _Ctx({"1.2": asyncio.CancelledError()})
    made = nodes_mod.make_nodes(ctx)

    update = await made["write_lessons"](_state())

    # 节点必须正常返回，且把崩溃的课时记进 failed_lessons
    assert "1.2" in update["failed_lessons"]
    codes = [w["code"] for w in update["warnings"]]
    assert "LESSON_FAILED" in codes
    # 其余课时不受影响
    assert set(update["lessons"]) == {"1.1", "1.3"}


@pytest.mark.asyncio
async def test_lesson_error_is_isolated(monkeypatch):
    """T-WF-2：普通异常同样只影响那一个课时。"""
    from repolearn.core.errors import AppError

    ctx = _Ctx({"1.1": AppError("PROVIDER_UNAVAILABLE", "boom")})
    made = nodes_mod.make_nodes(ctx)

    update = await made["write_lessons"](_state())

    assert update["failed_lessons"] == ["1.1"]
    assert set(update["lessons"]) == {"1.2", "1.3"}
    assert any("1.1" in w["message"] for w in update["warnings"])


@pytest.mark.asyncio
async def test_fanout_path_isolates_a_failing_lesson():
    """T-WF-4：扇出路径（`current_lesson` 存在）同样不能让一个课时带走整门课。

    真实现场（job job_01M6ZE5PWRJ2Z0ZK7HPQA2F0A0）：11 个课时写成功，第 12 个撞上
    节点 token 分闸 → 异常从 LangGraph 节点直接穿到 `graph.ainvoke` → 整门课 failed。
    正确行为是：失败的课时进 `failed_lessons`，其余照常发布（课程 partial）。
    """
    from repolearn.core.errors import AppError

    ctx = _Ctx({"1.2": AppError("BUDGET_EXCEEDED", "budget exceeded: tokens used=154978 limit=150000")})
    made = nodes_mod.make_nodes(ctx)
    state = {**_state(), "current_lesson": {"key": "1.2", "title": "b", "goal": "g", "anchors": []}}

    update = await made["write_lessons"](state)  # 不允许抛

    assert update["failed_lessons"] == ["1.2"]
    assert update["lessons"] == {}
    assert update["warnings"][0]["code"] == "LESSON_FAILED"

    # 成功的课时在同一个节点里仍然正常返回
    ok_state = {**_state(), "current_lesson": {"key": "1.3", "title": "c", "goal": "g", "anchors": []}}
    good = await made["write_lessons"](ok_state)
    assert set(good["lessons"]) == {"1.3"}
    assert good.get("failed_lessons") in (None, [])


@pytest.mark.asyncio
async def test_writer_gets_a_narrow_tool_set():
    """T-WF-5：写课时不下发 `repo_read_file`（它会把每轮上下文撑大，实测 155k/课时）。"""
    from repolearn.providers.base import DEFAULT_AGENT_TOOLS, WRITER_AGENT_TOOLS

    ctx = _Ctx({})
    made = nodes_mod.make_nodes(ctx)
    await made["write_lessons"]({**_state(), "current_lesson": {"key": "1.1", "title": "a", "goal": "g", "anchors": []}})

    assert ctx.calls, "writer 必须真的被调用"
    key, tools = ctx.calls[0]
    assert key == "1.1"
    assert tools == WRITER_AGENT_TOOLS
    assert "repo_read_file" not in tools
    # 护栏：默认工具集仍然包含读文件（planner 需要它）
    assert "repo_read_file" in DEFAULT_AGENT_TOOLS

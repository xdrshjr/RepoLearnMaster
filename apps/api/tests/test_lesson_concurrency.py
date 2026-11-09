"""课时并发必须真的被限流（T-WF-3）。

真实现场（2026-11-09 浏览器实测，连续三次）：课程跑到"写课时"就整个失败——

    job : failed · PROVIDER_UNAVAILABLE
    body: {"error":{"code":"KERNEL_BUSY","message":"too many concurrent runs"}}
    结果: 12 个课时一个都没留下

根因在**图与节点的接缝**上：`course_graph.fan_out_lessons` 用 LangGraph 的 `Send`
按课时扇出，于是有 12 个**并发**的 `write_lessons` 节点调用，每个调用只写一个课时
（`state["current_lesson"]` 存在），因此永远不会进入 `_write_all` —— 而
`LESSON_CONCURRENCY = 3` 那把信号量恰好只存在于 `_write_all` 里面。
实际后果是 12 路同时打内核，而内核对并发有硬上限（8），于是稳定 429。

这条用例直接模拟"12 个并发节点调用"，断言真正进入模型的行数 ≤ 3。
"""

from __future__ import annotations

import asyncio
import json

import pytest

from repolearn.workflow import nodes as nodes_mod


class _Ctx:
    """记录**同时**在跑的 run 数量。"""

    runtime_mode = "kernel"

    def __init__(self) -> None:
        self.active = 0
        self.max_active = 0
        self.finished: list[str] = []

    async def emit_progress(self, node: str, percent: int = 0) -> None:  # noqa: ARG002
        return None

    async def run(self, role: str, system: str, prompt: str, **kwargs):  # noqa: ANN001, ANN003
        key = str(kwargs.get("lesson_key", ""))
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        try:
            # 模拟一次真实的模型往返（有 IO，会被真正并发调度）
            await asyncio.sleep(0.05)
        finally:
            self.active -= 1
            self.finished.append(key)
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


def _base_state() -> dict:
    return {
        "repo": {"full_name": "fixture/repo", "default_branch": "main"},
        "commit": {"sha": "a" * 40},
        "knowledge_graph": {},
        "runtime": "kernel",
    }


@pytest.mark.asyncio
async def test_send_fanout_is_throttled_to_lesson_concurrency():
    """T-WF-3：12 个并发节点调用最多只有 3 路真的在跑模型。"""
    ctx = _Ctx()
    made = nodes_mod.make_nodes(ctx)
    lessons = [{"key": f"1.{i}", "title": f"t{i}", "goal": "g", "anchors": []} for i in range(1, 13)]

    # LangGraph 的 Send 扇出等价于"同时调用 node 12 次"
    await asyncio.gather(
        *(made["write_lessons"]({**_base_state(), "current_lesson": lesson}) for lesson in lessons)
    )

    assert ctx.max_active <= nodes_mod.LESSON_CONCURRENCY, (
        f"同时跑了 {ctx.max_active} 路模型调用，上限应是 {nodes_mod.LESSON_CONCURRENCY}——"
        "超过内核的 8 路并发上限就会稳定拿到 429 KERNEL_BUSY"
    )
    assert set(ctx.finished) == {lesson["key"] for lesson in lessons}, "12 个课时都要真的写出来"


@pytest.mark.asyncio
async def test_sequential_path_shares_the_same_gate():
    """顺序路径（_write_all）仍然受限，且不会因为共用一把闸而互相饿死。"""
    ctx = _Ctx()
    made = nodes_mod.make_nodes(ctx)
    lessons = [{"key": f"2.{i}", "title": f"t{i}", "goal": "g", "anchors": []} for i in range(1, 6)]
    state = {
        **_base_state(),
        "curriculum": {"sections": [{"key": "walkthrough", "lessons": lessons}]},
    }

    update = await made["write_lessons"](state)

    assert ctx.max_active <= nodes_mod.LESSON_CONCURRENCY
    assert set(update["lessons"]) == {lesson["key"] for lesson in lessons}
    assert update["failed_lessons"] == []

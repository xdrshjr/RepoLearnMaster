"""轨迹阶段预算耗尽 → 静态轨迹兜底，**不能**让整门课作废（T-BUD-16）。

真实现场（2026-11-09 浏览器实测，job `job_01M6ZFHM3PJJ1NSDNMR1AT61MN`）：

    write_lessons : 12 个课时全部写成功（每课时 ~150k tokens）
    simulate_trace: budget exceeded: tokens used=4297 limit=1000     ← 预算被课时吃光
    job           : failed_budget → **已经写好的 12 个课时一个都没发布**

轨迹是"可降级项"：模型推演拿不到时，静态调用链（`template_trace`）本身就能讲。
所以预算耗尽必须和"结构契约不通过"走同一个出口——降级 + 一条警告，课程照常发布。
"""

from __future__ import annotations

import pytest

from repolearn.core.errors import AppError
from repolearn.workflow import nodes as nodes_mod


class _Ctx:
    runtime_mode = "kernel"

    def __init__(self, *, fail_with: str | None = None) -> None:
        self.fail_with = fail_with
        self.calls = 0

    async def emit_progress(self, node: str, percent: int = 0) -> None:  # noqa: ARG002
        return None

    async def run(self, role: str, system: str, prompt: str, **kwargs):  # noqa: ANN001, ANN003
        self.calls += 1
        if self.fail_with:
            raise AppError(self.fail_with, "budget exceeded: tokens used=4297 limit=1000")
        return "{}", {"tokens_in": 10, "tokens_out": 5}

    def save_artifact(self, node: str, key: str, payload):  # noqa: ANN001, ANN201
        return f"artifacts/{node}/{key}"

    def load_artifact(self, key):  # noqa: ANN001, ANN201
        return {}


def _state() -> dict:
    return {
        "repo": {"full_name": "fixture/repo"},
        "commit": {"sha": "a" * 40},
        "knowledge_graph": {"chains": [], "artifact": None},
        "runtime": "kernel",
        "lessons": {"1.1": {"artifact": "artifacts/write_lessons/1.1.json", "anchors": []}},
    }


@pytest.mark.asyncio
async def test_trace_budget_exhaustion_degrades_instead_of_failing(monkeypatch):
    """T-BUD-16：轨迹阶段预算耗尽 → 静态轨迹 + 警告，节点正常返回。"""
    monkeypatch.setattr(nodes_mod, "_chains_from_artifact", lambda kg, ctx: [])
    ctx = _Ctx(fail_with="BUDGET_EXCEEDED")
    made = nodes_mod.make_nodes(ctx)

    update = await made["simulate_trace"](_state())

    assert set(update["traces"]) == {"1.1"}, "课时必须有轨迹（哪怕是静态的）"
    codes = [w["code"] for w in update["warnings"]]
    assert "TRACE_FALLBACK" in codes


@pytest.mark.asyncio
async def test_other_trace_errors_still_propagate(monkeypatch):
    """只有预算耗尽可降级：别的错误照旧抛出（别把真故障也吞掉）。"""
    monkeypatch.setattr(nodes_mod, "_chains_from_artifact", lambda kg, ctx: [])
    ctx = _Ctx(fail_with="PROVIDER_UNAVAILABLE")
    made = nodes_mod.make_nodes(ctx)

    with pytest.raises(AppError) as exc:
        await made["simulate_trace"](_state())
    assert exc.value.code == "PROVIDER_UNAVAILABLE"

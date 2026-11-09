"""预算耗尽时**不能扔掉已经交付的产出**（2026-11-09 真机复现）。

现场（`var/logs/api.log` + 本地直连内核复现，job `job_01M6ZB2G6W94Y90D1RWDHGKX94`）:

    planner 第 10 轮 : tool.start emit_course_json → tool.end ok:true   ← 骨架已交付
    第 11 轮        : budget.exceeded {"kind":"turns","used":11,"limit":10}
    run.failed      : {"code":"BUDGET_EXCEEDED"}                        ← 不带 result（旧行为）
    课程终态        : runtime=template，quality_report.degraded=true     ← 整门课降级

用户看到的是"生成失败/简化版"，而完整的课程骨架其实已经在 EmitSlot 里。
两层都要修，这条用例守的是 **Python 这一层**：
`_Ctx.run` 在 `status=budget_exceeded` 但 `result` 里有可用产出时，必须当作交付成功
（金额照记、闸门照生效），而不是抛 `BUDGET_EXCEEDED` 让 N5 去建模板骨架。
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from repolearn.core.errors import AppError
from repolearn.jobs import handlers as handlers_mod
from repolearn.providers import agent_runtime
from repolearn.providers.agent_runtime import AgentRunResult
from repolearn.providers.base import LlmConfig
from repolearn.providers.budget_guard import JobBudget


@dataclass
class _Candidate:
    config: LlmConfig
    capabilities: dict
    model_id: str = "deepseek-flash"


class _Resolver:
    def resolve(self, role: str) -> list[_Candidate]:  # noqa: ARG002
        cfg = LlmConfig(provider="custom", protocol="openai_compatible", api_key="k", model_id="deepseek-flash")
        return [_Candidate(config=cfg, capabilities={"price_in": 0, "price_out": 0})]


class _Selector:
    def __init__(self, result: AgentRunResult) -> None:
        self.result = result

    async def run(self, req):  # noqa: ANN001, ANN201
        return [], self.result


def _ctx(monkeypatch: pytest.MonkeyPatch, result: AgentRunResult) -> handlers_mod._Ctx:
    # `_Ctx.run` 内部是 `from repolearn.providers.agent_runtime import get_selector`
    # （函数内导入，避免循环依赖），所以必须打在**定义处**，打在 handlers 模块上无效。
    monkeypatch.setattr(agent_runtime, "get_selector", lambda: _Selector(result))

    async def _noop(self, *args, **kwargs):  # noqa: ANN001, ANN003
        return None

    monkeypatch.setattr(handlers_mod._Ctx, "_record_cost", _noop)
    return handlers_mod._Ctx(
        job_id="job_test",
        course_id="crs_test",
        resolver=_Resolver(),
        budget=JobBudget(),
        tts=None,
        runtime_mode="kernel",
        emit=_noop,
    )


_CURRICULUM = {"title": "sherlock-project/sherlock 带读课程", "sections": [{"key": "overview", "lessons": []}]}


@pytest.mark.asyncio
async def test_budget_exceeded_with_delivered_curriculum_counts_as_delivery(monkeypatch):
    """T-BUD-10：撞顶时已交付的骨架必须被采用（而不是抛异常去建模板课）。"""
    ctx = _ctx(
        monkeypatch,
        AgentRunResult(
            status="budget_exceeded",
            result={"curriculum": _CURRICULUM, "lessons": {}, "traces": {}, "quizzes": {}, "failures": []},
            usage={"tokensIn": 208000, "tokensOut": 27},
            error={"code": "BUDGET_EXCEEDED", "message": "budget exceeded: turns used=11 limit=10"},
            runtime="kernel",
        ),
    )

    text, usage = await ctx.run("planner", "sys", "prompt", node="plan_curriculum", schema="course")

    assert "sherlock-project/sherlock 带读课程" in text
    assert usage["tokens_in"] == 208000
    # 金额/预算照记：闸门不能被"交付成功"顺手关掉
    assert ctx.budget.used_tokens == 208027


@pytest.mark.asyncio
async def test_budget_exceeded_without_any_delivery_still_falls_back(monkeypatch):
    """T-BUD-11：什么都没交付时仍然抛 BUDGET_EXCEEDED（N5 才会走模板兜底）。"""
    ctx = _ctx(
        monkeypatch,
        AgentRunResult(
            status="budget_exceeded",
            result={"curriculum": None, "lessons": {}, "traces": {}, "quizzes": {}, "failures": []},
            usage={"tokensIn": 90000, "tokensOut": 5},
            error={"code": "BUDGET_EXCEEDED", "message": "budget exceeded: turns used=7 limit=6"},
            runtime="kernel",
        ),
    )

    with pytest.raises(AppError) as exc:
        await ctx.run("planner", "sys", "prompt", node="plan_curriculum", schema="course")
    assert exc.value.code == "BUDGET_EXCEEDED"


@pytest.mark.asyncio
async def test_delivered_lesson_is_used_when_the_writer_runs_out_of_budget(monkeypatch):
    """T-BUD-12：writer 同理——课时已经 emit 成功就不能因为随后的触顶而丢掉。"""
    lesson = {"key": "1.1", "title": "sherlock.py 走读", "steps": [], "quiz": []}
    ctx = _ctx(
        monkeypatch,
        AgentRunResult(
            status="budget_exceeded",
            result={"curriculum": None, "lessons": {"1.1": lesson}, "traces": {}, "quizzes": {}, "failures": []},
            usage={"tokensIn": 5000, "tokensOut": 100},
            error={"code": "BUDGET_EXCEEDED", "message": "budget exceeded: turns used=9 limit=8"},
            runtime="kernel",
        ),
    )

    text, _ = await ctx.run("writer", "sys", "prompt", node="write_lessons", lesson_key="1.1")

    assert '"key": "1.1"' in text

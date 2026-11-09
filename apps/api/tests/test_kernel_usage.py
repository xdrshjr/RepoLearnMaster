"""内核 → Python 的 **usage 传播**（真实故障回归）。

现场（var/logs/api.log，job_01M6Z6GDK7JGRMH1THMNP18CD0）：

    kernel 侧 : budget exceeded: tokens used=213725 limit=200000
    cost_ledger: tokens_in=0 tokens_out=0 usd=0

同一件事，两边记的是两个数。根因：内核的 `budget.exceeded` / `run.failed`
两个事件都不带 usage，Python 侧只认 `usage` 字段，于是记 0。

记 0 的后果不是"报表难看"：
* job 级总闸靠 `charge()` 累积 → 永远不触发（只有内核的节点分闸在拦）；
* 成本面板、`/v1/metrics`、`cli doctor` 的成本项全是 0；
* 用户看到"预算耗尽"却完全不知道花了多少，而真实花了 213,725。
"""

from __future__ import annotations

from repolearn.providers.agent_runtime import AgentEvent, apply_run_event, new_run_accumulator


def _ev(event_type: str, **data) -> AgentEvent:  # noqa: ANN003
    return AgentEvent(type=event_type, seq=1, data=data)


def test_budget_exceeded_carries_real_usage():
    """T-BUD-3：预算耗尽时 usage 必须留下（不是 0）。"""
    acc = new_run_accumulator()
    result = apply_run_event(
        acc,
        _ev(
            "budget.exceeded",
            kind="tokens",
            used=213725,
            limit=200000,
            usage={"turns": 6, "tokensIn": 210000, "tokensOut": 3725, "usd": 0.12},
        ),
    )
    assert result.status == "budget_exceeded"
    assert result.usage["tokensIn"] == 210000
    assert result.usage["tokensOut"] == 3725
    # 错误里要同时有"哪一档超了"与具体数字：前端文案与报表都用得上
    assert result.error["kind"] == "tokens"
    assert result.error["used"] == 213725
    assert result.error["limit"] == 200000


def test_later_event_without_usage_does_not_erase_it():
    """T-BUD-4：后到的事件没有 usage 时，不能把已有真实用量清零。

    这是现场那个 bug 的**直接形态**：`budget.exceeded` 带着用量，紧接着的
    `run.failed` 不带，整体覆盖就等于把 213,725 抹成 0。
    """
    acc = new_run_accumulator()
    apply_run_event(
        acc,
        _ev("budget.exceeded", kind="tokens", used=100, limit=50, usage={"tokensIn": 90, "tokensOut": 10}),
    )
    result = apply_run_event(acc, _ev("run.failed", code="BUDGET_EXCEEDED", message="over", retryable=False))
    assert result.status == "budget_exceeded"
    assert result.usage.get("tokensIn") == 90
    assert result.usage.get("tokensOut") == 10


def test_completed_run_still_reports_usage():
    """T-BUD-5：正常完成路径的 usage 不能被改坏（它是账本的主要来源）。"""
    acc = new_run_accumulator()
    result = apply_run_event(
        acc,
        _ev("run.completed", result={"text": "ok"}, usage={"tokensIn": 1200, "tokensOut": 300}),
    )
    assert result.status == "completed"
    assert result.result == {"text": "ok"}
    assert result.usage == {"tokensIn": 1200, "tokensOut": 300}


def test_cancelled_run_is_not_mistaken_for_budget():
    """T-BUD-6：取消与预算超限是两个终态，不能混（前端文案与重试按钮都不同）。"""
    acc = new_run_accumulator()
    result = apply_run_event(acc, _ev("run.failed", code="CANCELLED", message="run cancelled"))
    assert result.status == "cancelled"
    assert result.error["code"] == "CANCELLED"


def test_stream_events_do_not_change_terminal_state():
    """T-BUD-7：文本增量/工具事件只进事件流，不该把终态改成"failed"。"""
    acc = new_run_accumulator()
    result = apply_run_event(acc, _ev("agent.text.delta", delta="hi"))
    assert result.status == "failed"  # 还是初始值，等真正的终态事件
    assert result.usage == {}


def test_budget_exceeded_keeps_delivered_curriculum():
    """T-BUD-8：预算触顶时**已交付**的产物必须留下（2026-11-09 真机复现）。

    现场：planner 第 10 轮 `emit_course_json` 已经 accepted（`slot.curriculum` 有值），
    第 11 轮想再说点什么时 `turns used=11 limit=10` 撞顶。内核发出 `run.failed`，
    Python 侧只认 `result` 字段——旧版本里该字段根本没有，于是 `result.result` 是空
    字典，`nodes.plan_curriculum` 走模板兜底，整门课静默降级成"简化版"。

    这条用例守的是"交付物与终态是两条线"：终态可以是 budget_exceeded，
    但已经交付的课程骨架必须跟着 `run.failed` 一起回来。
    """
    acc = new_run_accumulator()
    curriculum = {"title": "sherlock 带读", "sections": [{"key": "overview", "lessons": []}]}
    apply_run_event(acc, _ev("budget.exceeded", kind="turns", used=11, limit=10, usage={"tokensIn": 208000}))
    result = apply_run_event(
        acc,
        _ev(
            "run.failed",
            code="BUDGET_EXCEEDED",
            message="budget exceeded: turns used=11 limit=10",
            retryable=False,
            usage={"tokensIn": 208000, "tokensOut": 27},
            result={"curriculum": curriculum, "lessons": {}, "traces": {}, "quizzes": {}, "failures": []},
        ),
    )
    assert result.status == "budget_exceeded"
    assert result.result["curriculum"] == curriculum
    # usage 依然不能被失败事件抹掉（T-BUD-4 的规则同时成立）
    assert result.usage["tokensIn"] == 208000


def test_failed_event_without_result_does_not_erase_a_delivered_one():
    """T-BUD-9：后到的 `run.failed` 不带 result 时，不能把已有交付物抹成空。"""
    acc = new_run_accumulator()
    apply_run_event(acc, _ev("run.completed", result={"curriculum": {"title": "t"}}))
    result = apply_run_event(acc, _ev("run.failed", code="KERNEL_RUN_FAILED", message="boom"))
    assert result.result["curriculum"] == {"title": "t"}
    assert result.status == "failed"

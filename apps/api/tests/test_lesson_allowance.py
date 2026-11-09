"""课时级额度不能被"固定的 600k 预留"压到 1 000 的下限（T-BUD-14/15）。

真实现场（2026-11-09 03:29 UTC 之后，`REPOLEARN_JOB_MAX_TOKENS=180000`——这正是
v1 的默认值，也是很多开发机的现状）：

    planner: ok（46,982 tokens，课程骨架已交付）
    writer : budget exceeded: tokens used=7907 limit=1000     ← 第一个课时就死
    课程   : failed_budget，12 个课时一个都没生成

根因不是"预算太小"（那是用户的选择），而是 `node_allowance(per_lesson=True)`
硬减一个**绝对值** `RESERVED_TOKENS = 600_000`：

    remaining(132,366) - 600,000 < 0  → max(1_000, …) → 1_000

一个课时 1 000 token 连读一个文件都不够。于是"预算紧"变成了"完全不可用"，
而用户看到的是"预算耗尽"，看不出问题出在预留算法上。

预留必须是**上限**而不是绝对值：小预算按比例让出，大预算才用得上 600k。
"""

from __future__ import annotations

from repolearn.providers.budget_guard import (
    NODE_BUDGETS,
    RESERVED_TOKENS,
    RESERVED_TOKENS_RATIO,
    JobBudget,
)


def test_small_job_budget_still_gives_each_lesson_a_usable_allowance():
    """T-BUD-14：总闸 180k、规划已花掉 ~47k 时，课时额度必须是"能用"的量级。"""
    budget = JobBudget(max_tokens=180_000, used_tokens=47_634)

    allowance = budget.node_allowance("write_lessons", per_lesson=True)

    assert allowance > 1_000, "旧的绝对值预留会把它压成 1_000，一个课时都活不下来"
    expected = min(NODE_BUDGETS["write_lessons"], 180_000 - 47_634 - int(180_000 * RESERVED_TOKENS_RATIO))
    assert allowance == expected


def test_reserve_never_exceeds_the_job_cap_share():
    """T-BUD-15：预留是上限，不是绝对值——任何总闸下都留得下余量给课时。"""
    for max_tokens in (60_000, 180_000, 500_000, 2_000_000, 8_000_000):
        budget = JobBudget(max_tokens=max_tokens)
        reserve = budget.per_lesson_reserve()
        assert reserve <= RESERVED_TOKENS
        assert reserve <= int(max_tokens * RESERVED_TOKENS_RATIO)
        # 至少一半额度（或节点分闸，取小）要留给"后面还有课时"
        usable = min(NODE_BUDGETS["write_lessons"], int(max_tokens * 0.5))
        assert budget.node_allowance("write_lessons", per_lesson=True) >= usable


def test_big_budget_still_uses_the_absolute_reserve():
    """大预算下行为与修改前一致（600k 的绝对预留），别把放大器拆了。"""
    budget = JobBudget(max_tokens=2_000_000)
    assert budget.per_lesson_reserve() == RESERVED_TOKENS
    assert budget.node_allowance("write_lessons", per_lesson=True) == NODE_BUDGETS["write_lessons"]


def test_exhausted_budget_still_floors_at_one_thousand():
    """额度真的用完时，下限仍是 1 000（不是负数、不是 0）。"""
    budget = JobBudget(max_tokens=180_000, used_tokens=179_000)
    assert budget.node_allowance("write_lessons", per_lesson=True) == 1_000

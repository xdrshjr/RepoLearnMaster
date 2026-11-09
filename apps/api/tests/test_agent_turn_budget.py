"""prompt 里要求的工具预算 与 下发给内核的轮数预算 必须一致（T-BUD-13）。

真实故障（2026-11-09 直连内核复现，sherlock@c588d7c8）：

    planner  maxTurns=6   → turns used=7 limit=6      （读文件读到没轮数交付）
    planner  maxTurns=10  → turns used=11 limit=10    （第 10 轮才 emit）
    课程终态 runtime=template / quality_report.degraded=true

上一次修这个问题的写法是"把轮数从 16 收到 6"——理由（token 放大器）是对的，
但它没有回答"模型要读几个文件才肯交付"，于是每一次真实生成都撞在闸门上，产品
静默交付"简化版"。所以现在有两个互相约束的数：

* `prompts.PLANNER_MAX_FILE_READS`：告诉模型"读完这么多就交付"；
* `budget_guard.NODE_MAX_TURNS["plan_curriculum"]`：真正下发的轮数。

这两个数**必须一起改**，否则要么模型被 prompt 骗（让它读 5 个但只给 4 轮），
要么闸门形同虚设。这条用例把"一起改"变成红灯。
"""

from __future__ import annotations

import re

from repolearn.providers.budget_guard import NODE_MAX_TURNS, JobBudget
from repolearn.workflow.prompts import (
    PLANNER_MAX_FILE_READS,
    WRITER_MAX_FILE_READS,
    planner_system,
    writer_system,
)

#: 交付一次（emit_course_json）+ 至少一次 schema 修正尝试 的固定开销。
DELIVERY_OVERHEAD_TURNS = 2


def test_planner_turn_budget_covers_what_the_prompt_asks_for():
    """轮数必须装得下"读 N 个文件 + 交付 + 修正"。"""
    turns = JobBudget().node_max_turns("plan_curriculum")
    needed = PLANNER_MAX_FILE_READS + DELIVERY_OVERHEAD_TURNS
    assert turns >= needed, (
        f"planner 只给 {turns} 轮，但 prompt 允许读 {PLANNER_MAX_FILE_READS} 个文件"
        f"再交付（至少需要 {needed} 轮）。二者必须一起改：只改 prompt 会让模型"
        f"读到没轮数交付，整门课降级成模板。"
    )


def test_writer_turn_budget_covers_what_the_prompt_asks_for():
    """同一个不变量对 writer 也成立（实测它需要 9 轮，而旧预算是 8）。"""
    turns = JobBudget().node_max_turns("write_lessons")
    needed = WRITER_MAX_FILE_READS + DELIVERY_OVERHEAD_TURNS
    assert turns >= needed, f"writer 只给 {turns} 轮，prompt 允许读 {WRITER_MAX_FILE_READS} 个文件"
    # 实测撞过两次墙：8 轮（turns used=9 limit=8）与 10 轮（turns used=11 limit=10）。
    assert turns > 10, "10 轮也是实测撞墙的值"


def test_prompt_states_the_same_read_budget():
    """prompt 里写出来的数字必须来自常量，不能各写一份。"""
    system = planner_system()
    assert f"最多先读 {PLANNER_MAX_FILE_READS} 个文件" in system
    # 硬编码的数字漂移是这类 bug 的常见来源：任何出现过的"最多先读 N 个文件"
    # 都必须等于常量本身。
    for found in re.findall(r"最多先读 (\d+) 个文件", system):
        assert int(found) == PLANNER_MAX_FILE_READS
    assert f"最多读 {WRITER_MAX_FILE_READS} 个文件" in writer_system()


def test_planner_budget_is_not_reduced_back_to_six():
    """6 轮是**实测撞墙**的值：任何人把它改回去都应该看到这条用例变红。"""
    assert NODE_MAX_TURNS["plan_curriculum"] > 6

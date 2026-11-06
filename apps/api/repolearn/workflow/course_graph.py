"""课程生成图（spec §3.4）。

**执行模型的三条硬约束**都在这里可验证：

1. `AsyncSqliteSaver` —— 同步的 `SqliteSaver` 与 `graph.ainvoke()` 组合会在写
   checkpoint 时抛"不能在事件循环里调用同步 IO"。因此 checkpointer 从
   `langgraph.checkpoint.sqlite.aio` 取，且在 `async with ... from_conn_string()`
   上下文内构建图。
2. **checkpoint 库与业务库物理隔离** —— `var/data/langgraph.sqlite` vs
   `var/data/repolearn.db`。同一文件里的写锁争用会让 LangGraph 每个 superstep
   的 checkpoint 提交与业务写入互相推到 `busy_timeout`。
3. **并行分支显式 reducer** —— 见 `state.py` 的 reducer 表；这里用 `Send` 扇出，
   汇聚到 N9。

状态里只放引用：N6/N7 的完整产物写 `artifacts/<job>/<node>/<key>.json`，
state 里留 `{"key":..., "artifact":...}`（≤256KB 预算，测试断言）。
"""

from __future__ import annotations

import inspect
import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from repolearn.core.config import settings
from repolearn.core.logging import get_logger
from repolearn.workflow.state import NODE_PROGRESS, CourseGenState, new_state, prune_tree

log = get_logger("course_graph")


class GraphUnavailable(RuntimeError):
    """langgraph 不可用或 checkpointer 打开失败。调用方退到顺序执行。"""


@dataclass
class NodeContext:
    """节点能拿到的一切外部依赖。**显式注入**而不是全局单例：

    节点要能单测（喂假 provider、假镜像），全局单例会逼测试去 monkeypatch 五处。
    """

    run: Callable[..., Any]  # async (role, system, prompt, **kw) -> (text, usage)
    read_file: Callable[[str], str]
    line_count: Callable[[str], int]
    save_artifact: Callable[[str, str, Any], str]
    emit_progress: Callable[[str, int], Any]
    job_id: str


# --------------------------------------------------------------------------- #
# 图构建                                                                       #
# --------------------------------------------------------------------------- #


def checkpointer_path() -> Path:
    p = Path(settings.checkpoint_db)
    return p if p.is_absolute() else settings.repo_root / p


async def build_course_graph(ctx: NodeContext):
    """返回编译后的图。上层必须用 `async with` 或显式 close 释放连接。"""
    try:
        from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
        from langgraph.graph import END, StateGraph
    except Exception as exc:  # noqa: BLE001 - 缺包就是"不可用"，不是崩溃
        raise GraphUnavailable(f"langgraph 不可用：{exc}") from exc

    from repolearn.workflow.nodes import make_nodes

    path = checkpointer_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    saver_cm = AsyncSqliteSaver.from_conn_string(str(path))
    saver = await saver_cm.__aenter__()

    nodes = make_nodes(ctx)

    builder = StateGraph(CourseGenState)
    for name, fn in nodes.items():
        builder.add_node(name, fn)

    builder.set_entry_point("normalize_repo")
    builder.add_edge("normalize_repo", "resolve_commit")
    builder.add_edge("resolve_commit", "fetch_repo")
    builder.add_edge("fetch_repo", "analyze_repo")
    builder.add_edge("analyze_repo", "plan_curriculum")

    # N6 按课时扇出（Send），N7/N8 在各自节点内按课时并发，
    # 汇聚到 N9。recursion_limit=80 是安全上界：超限说明图里出现了意外循环。
    def fan_out_lessons(state: CourseGenState):
        from langgraph.types import Send

        lessons = [
            lesson
            for section in (state.get("curriculum", {}).get("sections") or [])
            for lesson in (section.get("lessons") or [])
        ]
        if not lessons:
            return "simulate_trace"
        return [Send("write_lessons", {**state, "current_lesson": lesson}) for lesson in lessons]

    builder.add_conditional_edges("plan_curriculum", fan_out_lessons, ["write_lessons", "simulate_trace"])
    builder.add_edge("write_lessons", "simulate_trace")
    builder.add_edge("simulate_trace", "synthesize_audio")
    builder.add_edge("synthesize_audio", "publish_course")
    builder.add_edge("publish_course", END)

    compiled = builder.compile(checkpointer=saver)
    # 把上下文管理器挂在图对象上，便于调用方统一关闭
    compiled._saver_cm = saver_cm
    return compiled


async def close_graph(graph) -> None:
    cm = getattr(graph, "_saver_cm", None)
    if cm is not None:
        try:
            await cm.__aexit__(None, None, None)
        except Exception:  # noqa: BLE001
            pass


async def run_graph(
    *,
    job_id: str,
    course_id: str,
    ctx: NodeContext,
    on_node: Callable[[str, dict], Any] | None = None,
    initial_state: dict | None = None,
) -> dict:
    """跑完整图；任何失败都由调用方（runner）转成 Job 终态。

    没有 langgraph 时**不让整个生成失败**：退到顺序执行同一批节点函数——
    这是一条被测试覆盖的路径（T-DEG 系列），不是遗留代码。
    """
    state = dict(initial_state) if initial_state else new_state(job_id, course_id)
    config = {
        "configurable": {"thread_id": job_id},
        "recursion_limit": 80,
    }
    try:
        graph = await build_course_graph(ctx)
    except GraphUnavailable as exc:
        log.warning("graph_unavailable_sequential", error=str(exc))
        return await run_sequential(state, ctx, on_node)

    try:
        async def _tick(node_name: str, payload: dict) -> None:
            if on_node is not None:
                result = on_node(node_name, payload)
                if inspect.isawaitable(result):
                    await result

        final = await graph.ainvoke(state, config)  # type: ignore[arg-type]
        return dict(final)
    finally:
        await close_graph(graph)


async def run_sequential(
    state: CourseGenState,
    ctx: NodeContext,
    on_node: Callable[[str, dict], Any] | None = None,
) -> dict:
    """无 langgraph 时的顺序执行：语义与图一致，只是没有 checkpoint。"""
    from repolearn.workflow.nodes import make_nodes

    nodes = make_nodes(ctx)
    order = (
        "normalize_repo",
        "resolve_commit",
        "fetch_repo",
        "analyze_repo",
        "plan_curriculum",
        "write_lessons",
        "simulate_trace",
        "synthesize_audio",
        "publish_course",
    )
    current: dict = dict(state)
    for name in order:
        fn = nodes[name]
        update = fn(current)  # type: ignore[operator]
        if inspect.isawaitable(update):
            update = await update
        if isinstance(update, dict):
            from repolearn.workflow.state import merge_budget, merge_dict, merge_list

            merged = dict(current)
            for key, value in update.items():
                if key in ("lessons", "traces", "quizzes", "narration"):
                    merged[key] = merge_dict(merged.get(key), value)
                elif key == "budget":
                    merged[key] = merge_budget(merged.get(key), value)
                elif key == "failed_lessons":
                    merged[key] = merge_list(merged.get(key), value)
                elif key == "warnings":
                    merged[key] = list(merged.get(key) or []) + list(value or [])
                else:
                    merged[key] = value
            current = merged
        if on_node is not None:
            result = on_node(name, current)
            if inspect.isawaitable(result):
                await result
    return current


def artifact_payload(ctx: NodeContext, node: str, key: str, payload: Any) -> str:
    """把大体量产物外置，返回可进 state 的引用。"""
    return ctx.save_artifact(node, key, payload)


def describe_state(state: dict) -> dict:
    """给事件/日志用的状态摘要（**不含 lesson 全文**）。"""
    return {
        "lessons": len(state.get("lessons") or {}),
        "traces": len(state.get("traces") or {}),
        "quizzes": sum(len(v or []) for v in (state.get("quizzes") or {}).values()),
        "warnings": len(state.get("warnings") or []),
        "failed_lessons": state.get("failed_lessons") or [],
        "runtime": state.get("runtime"),
        "node_progress": NODE_PROGRESS,
    }


__all__ = [
    "GraphUnavailable",
    "NodeContext",
    "artifact_payload",
    "build_course_graph",
    "checkpointer_path",
    "close_graph",
    "describe_state",
    "json",
    "prune_tree",
    "run_graph",
    "run_sequential",
]

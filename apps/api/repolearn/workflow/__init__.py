"""课程生成工作流层（spec §3.4）。

对外只暴露 `run_course_job()`：把 LangGraph 图、节点上下文、发布事务串成一条
可被 Job Runner 直接调用的流水线。runner 不应该知道"有 9 个节点"这件事。
"""

from __future__ import annotations

from repolearn.workflow.course_graph import (
    GraphUnavailable,
    NodeContext,
    build_course_graph,
    close_graph,
    describe_state,
    run_graph,
    run_sequential,
)
from repolearn.workflow.state import (
    MAX_CHECKPOINT_BYTES,
    NODE_LABELS,
    NODE_PROGRESS,
    NODES,
    CourseGenState,
    merge_budget,
    merge_dict,
    merge_list,
    new_state,
    prune_tree,
    state_size_bytes,
)

__all__ = [
    "MAX_CHECKPOINT_BYTES",
    "NODES",
    "NODE_LABELS",
    "NODE_PROGRESS",
    "CourseGenState",
    "GraphUnavailable",
    "NodeContext",
    "build_course_graph",
    "close_graph",
    "describe_state",
    "merge_budget",
    "merge_dict",
    "merge_list",
    "new_state",
    "prune_tree",
    "run_graph",
    "run_sequential",
    "state_size_bytes",
]

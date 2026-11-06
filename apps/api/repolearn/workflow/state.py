"""课程生成工作流的状态定义（spec §3.4）。

三条硬约束在这里落地：

1. **显式 reducer 表**。N6/N7/N8 用 `Send` 扇出，多个分支在同一个 superstep 返回
   对同名键的部分更新；没有 reducer，LangGraph 抛 `InvalidUpdateError`
   （"expected one value, got N"）。因此每个会被多分支写的键都在 `REDUCERS` 里。
2. **state 只放引用与小摘要**（单次 checkpoint ≤ 256 KB）。完整 lesson / trace /
   narration 在节点出口就写进 `artifacts/<job>/<node>/<key>.json`，state 里只留
   `{"key": ..., "artifact": ...}`。
3. **不在 state 里存密钥或明文**。API Key 只经 `providers` 的配置对象在内存里流转。
"""

from __future__ import annotations

import operator
from typing import Annotated, Any, TypedDict

MAX_CHECKPOINT_BYTES = 256 * 1024
MAX_STATE_TREE_ENTRIES = 200


def merge_dict(left: dict | None, right: dict | None) -> dict:
    """浅合并。每个课时分支返回 `{lesson_key: value}`，键互不重叠，浅合并即正确。"""
    return {**(left or {}), **(right or {})}


def merge_list(left: list | None, right: list | None) -> list:
    """`operator.add` 的去重版：多分支各自追加失败项，顺序无关。"""
    out: list = list(left or [])
    for item in right or []:
        if item not in out:
            out.append(item)
    return out


def merge_budget(left: dict | None, right: dict | None) -> dict:
    """逐字段取 `max(used)`、保留 `deadline_ms`。

    为什么不是简单求和：并行分支各自累加用量时，同一次调用可能被两个分支各记一遍。
    取 max 会低估——所以两条分支的用量分别在**各自出口**记进 cost_ledger，
    state 里的 budget 只用于"是否已经超限"的粗判（真实闸门在 JobBudget 里）。
    """
    a, b = left or {}, right or {}
    out = dict(a)
    for key in ("used_tokens", "used_usd", "max_tokens", "max_usd"):
        if key in a or key in b:
            out[key] = max(float(a.get(key, 0) or 0), float(b.get(key, 0) or 0))
    if "deadline_ms" in a or "deadline_ms" in b:
        out["deadline_ms"] = a.get("deadline_ms") or b.get("deadline_ms")
    return out


def _merge_ref(left: dict | None, right: dict | None) -> dict:
    return merge_dict(left, right)


class CourseGenState(TypedDict, total=False):
    """9 个节点共享的状态。全部字段可 JSON 序列化。"""

    job_id: str
    course_id: str
    repo: dict[str, Any]
    commit: dict[str, Any]
    mirror_dir: str
    #: 核心文件 + 目录骨架，上限 200 条；完整列表在 artifacts/<job>/n3/tree.json
    tree: list[dict[str, Any]]
    #: 只放 {node_count, edge_count, entrypoints[], chain_ids[]}
    knowledge_graph: dict[str, Any]
    curriculum: dict[str, Any]
    #: key → {artifact, anchors[], quiz_artifact, warnings[]}
    lessons: Annotated[dict[str, Any], _merge_ref]
    traces: Annotated[dict[str, Any], _merge_ref]
    quizzes: Annotated[dict[str, Any], _merge_ref]
    narration: Annotated[dict[str, Any], _merge_ref]
    budget: Annotated[dict[str, Any], merge_budget]
    warnings: Annotated[list[dict], operator.add]
    failed_lessons: Annotated[list[str], merge_list]
    #: v2 追加：让 N9 知道"这次是哪条链路被讲了"
    chain_ids: list[str]
    #: v2 追加：运行时通道（kernel|exec|template），进 quality_report 便于归因
    runtime: str
    #: Send 扇出的分支输入。**必须声明在这里**：LangGraph 会拒绝更新 schema 之外的键
    #: （`InvalidUpdateError`），而 N6 的每个扇出分支都要携带"本课时是哪一课"。
    current_lesson: dict[str, Any]
    #: N9 的发布结果（status / lesson_count / quality_report）。**必须声明**：
    #: LangGraph 只把 schema 里的键写回 state，未声明的键会被静默丢弃——
    #: 那会让每一次成功生成都被上报成 `partial`，质量报告永远是空的。
    publish: Annotated[dict[str, Any], _merge_ref]


INITIAL_KEYS = (
    "job_id",
    "course_id",
    "repo",
    "commit",
    "mirror_dir",
    "tree",
    "knowledge_graph",
    "curriculum",
    "lessons",
    "traces",
    "quizzes",
    "narration",
    "budget",
    "warnings",
    "failed_lessons",
    "chain_ids",
    "runtime",
)

NODES = (
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

NODE_LABELS = {
    "normalize_repo": "解析仓库",
    "resolve_commit": "确定版本",
    "fetch_repo": "拉取镜像",
    "analyze_repo": "静态分析",
    "plan_curriculum": "规划课程",
    "write_lessons": "撰写课时",
    "simulate_trace": "生成执行轨迹",
    "synthesize_audio": "合成配音",
    "publish_course": "发布课程",
}

NODE_PROGRESS = {
    "normalize_repo": 8,
    "resolve_commit": 16,
    "fetch_repo": 28,
    "analyze_repo": 40,
    "plan_curriculum": 52,
    "write_lessons": 76,
    "simulate_trace": 86,
    "synthesize_audio": 93,
    "publish_course": 100,
}


def new_state(job_id: str, course_id: str) -> CourseGenState:
    return CourseGenState(
        job_id=job_id,
        course_id=course_id,
        repo={},
        commit={},
        mirror_dir="",
        tree=[],
        knowledge_graph={},
        curriculum={},
        lessons={},
        traces={},
        quizzes={},
        narration={},
        budget={},
        warnings=[],
        failed_lessons=[],
        chain_ids=[],
        runtime="template",
    )


def state_size_bytes(state: dict) -> int:
    import json

    try:
        return len(json.dumps(state, ensure_ascii=False, default=str).encode("utf-8"))
    except (TypeError, ValueError):
        return -1


def prune_tree(tree: list[dict], limit: int = MAX_STATE_TREE_ENTRIES) -> list[dict]:
    """把 tree 裁到"核心文件 + 目录骨架"，完整列表落 artifact（spec §3.4）。"""
    core = [t for t in tree if t.get("is_core")]
    others = [t for t in tree if not t.get("is_core")]
    dirs: list[dict] = []
    seen: set[str] = set()
    for item in tree:
        path = str(item.get("path", ""))
        parts = path.split("/")
        for i in range(1, len(parts)):
            d = "/".join(parts[:i])
            if d not in seen:
                seen.add(d)
                dirs.append({"path": d, "size": 0, "lang": "dir", "is_core": False})
    return (core + dirs + others)[:limit]

"""工作流单元测试：reducer、状态体积、模板降级、轨迹守卫（T-GRAPH-4 / T-DEG-1 / T-TRACE-1）。"""

from __future__ import annotations

import json

from repolearn.analysis import analyze
from repolearn.analysis.knowledge_graph import KnowledgeGraph, Module
from repolearn.workflow.simulation_guard import (
    SIMULATION_NOTE,
    guard_trace,
    summarize,
    template_trace,
)
from repolearn.workflow.state import (
    MAX_CHECKPOINT_BYTES,
    merge_budget,
    merge_dict,
    merge_list,
    new_state,
    prune_tree,
    state_size_bytes,
)
from repolearn.workflow.template import (
    build_template_curriculum,
    build_template_lesson,
    file_header_comment,
    seconds_for,
)

FILES = [
    {"path": "pkg/mod.py", "size": 120, "lang": "python", "is_core": True},
    {"path": "pkg/util.py", "size": 80, "lang": "python", "is_core": True},
    {"path": "README.md", "size": 40, "lang": "markdown", "is_core": True},
]
SOURCES = {
    "pkg/mod.py": '"""主模块：定义入口。"""\n\nclass Engine:\n    def run(self):\n        return helper()\n\n\ndef helper():\n    return 1\n',
    "pkg/util.py": "def util():\n    return 2\n",
    "README.md": "# demo\n",
}


def _read(path: str) -> str:
    return SOURCES.get(path, "")


# ---- reducer --------------------------------------------------------------


def test_merge_dict_is_shallow_and_order_independent():
    assert merge_dict({"a": 1}, {"b": 2}) == {"a": 1, "b": 2}
    assert merge_dict(None, {"a": 1}) == {"a": 1}
    assert merge_dict({"a": 1}, None) == {"a": 1}


def test_merge_list_dedups():
    assert merge_list(["1.1"], ["1.1", "2.1"]) == ["1.1", "2.1"]


def test_merge_budget_takes_max_used():
    merged = merge_budget({"used_tokens": 100, "deadline_ms": 5000}, {"used_tokens": 250})
    assert merged["used_tokens"] == 250
    assert merged["deadline_ms"] == 5000


def test_state_starts_empty_and_small():
    state = new_state("job_1", "crs_1")
    assert state["lessons"] == {}
    assert state_size_bytes(state) < MAX_CHECKPOINT_BYTES


def test_prune_tree_keeps_core_and_dirs():
    tree = [{"path": f"d{i}/f{i}.py", "is_core": True} for i in range(5)] + [
        {"path": f"bin{i}.dat", "is_core": False} for i in range(5)
    ]
    pruned = prune_tree(tree, limit=20)
    assert any(item["path"] == "d0" for item in pruned)
    assert len(pruned) <= 20


def test_state_with_many_lessons_stays_under_budget():
    """T-GRAPH-4 的口径：state 里只放引用，因此 12 个课时也不会撑大。"""
    state = new_state("job_1", "crs_1")
    for i in range(12):
        state["lessons"][f"3.{i}"] = {
            "artifact": f"job_1/write_lessons/{i}.json",
            "anchors": [{"file": "pkg/mod.py", "line_start": 1, "line_end": 5}],
            "quiz_artifact": f"job_1/write_lessons/{i}.json",
            "warnings": [],
        }
        state["traces"][f"3.{i}"] = {"artifact": f"job_1/simulate_trace/{i}.json"}
    size = state_size_bytes(state)
    assert size < MAX_CHECKPOINT_BYTES, f"state 体积 {size} 超过 256KB"


# ---- 轨迹守卫 -------------------------------------------------------------


def test_guard_downgrades_unverifiable_source_fact():
    trace = {
        "key": "t1",
        "title": "链路",
        "steps": [
            {
                "index": 0,
                "title": "调用 helper",
                "certainty": "source_fact",
                "evidence": [{"file": "pkg/mod.py", "line_start": 900, "line_end": 901}],
            }
        ],
    }
    result = guard_trace(trace, lambda p: 9 if p == "pkg/mod.py" else 0, lesson_key="3.1")
    assert result.steps[0]["certainty"] != "source_fact"
    assert result.downgraded == 1
    assert any(w["code"] == "CERTAINTY_DOWNGRADED" for w in result.warnings)


def test_guard_keeps_verifiable_source_fact():
    trace = {
        "key": "t1",
        "title": "链路",
        "steps": [
            {
                "index": 0,
                "title": "调用 helper",
                "certainty": "source_fact",
                "evidence": [{"file": "pkg/mod.py", "line_start": 2, "line_end": 3}],
            }
        ],
    }
    result = guard_trace(trace, lambda p: 9, lesson_key="3.1")
    assert result.steps[0]["certainty"] == "source_fact"
    assert result.downgraded == 0


def test_guard_annotates_simulation_variables():
    trace = {
        "key": "t1",
        "title": "链路",
        "steps": [
            {
                "index": 0,
                "title": "推演",
                "certainty": "teaching_simulation",
                "variables": [{"name": "msg", "value": "hi"}],
            }
        ],
    }
    result = guard_trace(trace, lambda p: 9)
    assert result.steps[0]["variables"][0]["note"] == SIMULATION_NOTE


def test_summarize_marks_weak_below_40_percent():
    steps = [{"certainty": "source_fact"}] + [{"certainty": "teaching_simulation"}] * 3
    summary = summarize(steps)
    assert summary["quality"] == "weak"
    assert summary["source_fact_ratio"] == 0.25


def test_template_trace_never_claims_source_fact():
    """状态 C 的硬规则：模板轨迹只输出 static_inference，不编造 source_fact。"""
    chain = {"title": "a → b", "steps": [{"symbol": "a", "file": "pkg/mod.py", "line": 4}]}
    trace = template_trace(chain, "1.1")
    assert trace["steps"]
    assert all(step["certainty"] == "static_inference" for step in trace["steps"])


# ---- 模板降级 -------------------------------------------------------------


def _kg() -> KnowledgeGraph:
    result = analyze(FILES, _read)
    return result.knowledge_graph


def test_template_curriculum_is_deterministic():
    kg = _kg()
    a = build_template_curriculum({"full_name": "o/r"}, kg, _read)
    b = build_template_curriculum({"full_name": "o/r"}, kg, _read)
    assert json.dumps(a, sort_keys=True, ensure_ascii=False) == json.dumps(b, sort_keys=True, ensure_ascii=False)
    assert len(a["sections"]) == 4
    total = sum(len(s["lessons"]) for s in a["sections"])
    assert total == 12


def test_template_lesson_has_contiguous_segments():
    kg = _kg()
    plan = {"key": "1.1", "title": "走读", "layer": "overview", "minutes": 5, "anchors": [{"file": "pkg/mod.py", "line_start": 3, "line_end": 6}]}
    lesson = build_template_lesson(lesson_plan=plan, kg=kg, read=_read)
    segments = lesson["steps"][0]["segments"]
    cursor = 0
    for seg in segments:
        assert seg["start_ms"] == cursor
        cursor = seg["end_ms"]
    assert lesson["steps"][0]["duration_ms"] == cursor
    assert lesson["steps"][0]["timing_source"] == "estimated"
    assert lesson["quiz"]


def test_template_lesson_survives_unreadable_file():
    """模板路径不允许因读失败而中断。"""
    kg = _kg()
    plan = {"key": "1.1", "title": "x", "layer": "overview", "anchors": [{"file": "nope.py", "line_start": 1, "line_end": 1}]}
    lesson = build_template_lesson(lesson_plan=plan, kg=kg, read=lambda p: (_ for _ in ()).throw(OSError("boom")))
    assert lesson["steps"][0]["segments"]


def test_file_header_comment_extracts_docstring():
    assert "主模块" in file_header_comment(SOURCES["pkg/mod.py"])


def test_seconds_for_uses_chinese_reading_speed():
    assert seconds_for("一" * 42) == 10


def test_rehydrated_empty_kg_does_not_crash():
    kg = KnowledgeGraph(modules=[Module(key="pkg", path="pkg")])
    plan = {"key": "1.1", "title": "x", "layer": "overview"}
    lesson = build_template_lesson(lesson_plan=plan, kg=kg, read=lambda p: "")
    assert lesson["steps"]

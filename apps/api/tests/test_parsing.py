"""结构化产出解析与语义校验（spec §6.3 / §3.4 N5/N6）。"""

from __future__ import annotations

from repolearn.workflow.parsing import (
    check_anchors,
    check_curriculum,
    check_quiz,
    check_segments,
    extract_json,
    load_schema,
    parse_and_validate,
    validate,
)

GOOD_CURRICULUM = {
    "title": "AutoGen 入门",
    "sections": [
        {"key": "overview", "title": "宏观", "lessons": [{"key": f"1.{i}", "title": "a", "goal": "g"} for i in range(3)]},
        {"key": "walkthrough", "title": "走读", "lessons": [{"key": f"2.{i}", "title": "b", "goal": "g"} for i in range(3)]},
        {"key": "deep_dive", "title": "深入", "lessons": [{"key": f"3.{i}", "title": "c", "goal": "g"} for i in range(4)]},
        {"key": "recap", "title": "总结", "lessons": [{"key": "4.1", "title": "d", "goal": "g"}]},
    ],
}


def test_extract_json_from_fence():
    text = '好的，这是结果：\n```json\n{"a": 1}\n```\n希望有帮助'
    assert extract_json(text) == '{"a": 1}'


def test_extract_json_tolerates_trailing_comma():
    assert extract_json('{"a": 1,}') is not None


def test_extract_json_returns_none_for_prose():
    assert extract_json("这里没有任何 JSON") is None


def test_schema_files_exist():
    for name in ("course", "lesson", "trace", "book"):
        assert load_schema(name) is not None, name


def test_validate_reports_paths():
    errors = validate("course", {"title": ""})
    assert any("sections" in e for e in errors)


def test_parse_and_validate_ok():
    result = parse_and_validate('```json\n{"title":"x","sections":[{"key":"overview","title":"t","lessons":[{"key":"1","title":"t","goal":"g"}]}]}\n```', "course")
    assert result.ok is True


def test_check_curriculum_requires_four_sections():
    payload = {"sections": [{"key": "overview", "lessons": [{"key": f"1.{i}", "goal": "g"} for i in range(10)]}]}
    errors = check_curriculum(payload)
    assert any("缺少章节" in e for e in errors)


def test_check_curriculum_enforces_lesson_count():
    too_few = {"sections": [{"key": k, "lessons": [{"key": f"{k}.1", "goal": "g"}]} for k in ("overview", "walkthrough", "deep_dive", "recap")]}
    assert any("少于 10" in e for e in check_curriculum(too_few))
    assert check_curriculum(GOOD_CURRICULUM) == []


def test_check_curriculum_requires_goal():
    payload = {"sections": [
        {"key": "overview", "lessons": [{"key": f"1.{i}", "goal": "g"} for i in range(3)]},
        {"key": "walkthrough", "lessons": [{"key": f"2.{i}", "goal": "g"} for i in range(3)]},
        {"key": "deep_dive", "lessons": [{"key": f"3.{i}", "goal": "g"} for i in range(3)]},
        {"key": "recap", "lessons": [{"key": "4.1", "goal": ""}]},
    ]}
    assert any("缺少 goal" in e for e in check_curriculum(payload))


def test_check_segments_detects_gap():
    steps = [{"index": 0, "duration_ms": 10000, "segments": [
        {"id": "s0", "start_ms": 0, "end_ms": 3000},
        {"id": "s1", "start_ms": 5000, "end_ms": 10000},
    ]}]
    errors = check_segments(steps)
    assert any("空洞" in e for e in errors)


def test_check_segments_accepts_contiguous():
    steps = [{"index": 0, "duration_ms": 10000, "segments": [
        {"id": "s0", "start_ms": 0, "end_ms": 4000},
        {"id": "s1", "start_ms": 4000, "end_ms": 10000},
    ]}]
    assert check_segments(steps) == []


def test_check_segments_requires_start_at_zero():
    steps = [{"index": 0, "duration_ms": 5000, "segments": [{"id": "s0", "start_ms": 1000, "end_ms": 5000}]}]
    assert any("首段未从 0 开始" in e for e in check_segments(steps))


def test_check_segments_flags_duration_mismatch():
    steps = [{"index": 0, "duration_ms": 20000, "segments": [{"id": "s0", "start_ms": 0, "end_ms": 5000}]}]
    assert any("不匹配" in e for e in check_segments(steps))


def test_check_quiz_requires_answer_in_choices():
    quiz = [{"id": "q1", "choices": [{"id": "a"}], "answer_id": "z", "evidence": [{"file": "x"}]}]
    errors = check_quiz(quiz)
    assert any("answer_id" in e for e in errors)


def test_check_quiz_requires_evidence():
    quiz = [{"id": "q1", "choices": [{"id": "a"}], "answer_id": "a", "evidence": []}]
    assert any("evidence" in e for e in check_quiz(quiz))


def test_check_anchors_validates_existence_and_bounds():
    lines = {"pkg/mod.py": 5}
    assert check_anchors([{"file": "pkg/mod.py", "line_start": 1, "line_end": 3}], lines) == []
    assert check_anchors([{"file": "missing.py", "line_start": 1, "line_end": 2}], lines)
    assert check_anchors([{"file": "pkg/mod.py", "line_start": 4, "line_end": 99}], lines)
    assert check_anchors([{"file": "pkg/mod.py", "line_start": 5, "line_end": 2}], lines)

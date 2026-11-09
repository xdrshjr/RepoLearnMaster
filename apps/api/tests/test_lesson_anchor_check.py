"""课时级锚点校验把"整门课回滚"变成"这一课时自己修"（T-ANCHOR-3）。

真实现场（2026-11-09，job `job_01M6ZHWQQZTDQ27N5JB5HNBWD8`）：
12 个课时全部写完（160 万 tokens），发布前 `check_anchors` 发现 5 个越界锚点，
`publish` 抛 `ANCHOR_STALE` → **整门课回滚**，用户只看到"生成失败"。

越界锚点在课时级是**可修复错误**：`produce_validated` 会把校验错误回灌给模型，
模型改一行就能过。这条用例守两件事：
1. `check_lesson_anchors` 必须扫到 focus 与 code_notes 两处；
2. 它给出的错误必须能让人/模型看懂（含文件与行号）。
"""

from __future__ import annotations

from repolearn.workflow.parsing import check_lesson_anchors, lesson_anchors

FILE_LINES = {"pkg/a.py": 100, "pkg/b.py": 20}


def _lesson(**overrides) -> dict:
    lesson = {
        "key": "1.1",
        "title": "t",
        "layer": "overview",
        "steps": [
            {
                "index": 0,
                "title": "step",
                "duration_ms": 5000,
                "segments": [
                    {
                        "id": "s0",
                        "text": "讲一句",
                        "start_ms": 0,
                        "end_ms": 5000,
                        "focus": {"file": "pkg/a.py", "line_start": 10, "line_end": 20},
                    }
                ],
                "code_notes": [{"file": "pkg/b.py", "line": 5, "text": "note"}],
            }
        ],
        "quiz": [],
    }
    lesson.update(overrides)
    return lesson


def test_valid_lesson_passes():
    assert check_lesson_anchors(_lesson(), FILE_LINES) == []


def test_focus_beyond_file_end_is_reported():
    lesson = _lesson()
    lesson["steps"][0]["segments"][0]["focus"] = {"file": "pkg/a.py", "line_start": 90, "line_end": 101}
    errors = check_lesson_anchors(lesson, FILE_LINES)
    assert errors, "越界的 focus 必须被拦下"
    assert any("pkg/a.py" in err for err in errors)


def test_code_note_beyond_file_end_is_reported():
    lesson = _lesson()
    lesson["steps"][0]["code_notes"] = [{"file": "pkg/b.py", "line": 21, "text": "note"}]
    errors = check_lesson_anchors(lesson, FILE_LINES)
    assert errors
    assert any("pkg/b.py" in err for err in errors)


def test_unknown_file_is_reported():
    lesson = _lesson()
    lesson["steps"][0]["segments"][0]["focus"] = {"file": "pkg/ghost.py", "line_start": 1, "line_end": 2}
    errors = check_lesson_anchors(lesson, FILE_LINES)
    assert errors and any("ghost.py" in err for err in errors)


def test_lesson_anchors_scans_both_sources():
    anchors = lesson_anchors(_lesson())
    files = {anchor["file"] for anchor in anchors}
    assert files == {"pkg/a.py", "pkg/b.py"}

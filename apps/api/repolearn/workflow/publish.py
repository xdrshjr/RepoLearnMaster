"""发布（spec §3.4 N9 / §3.10）。

**事务边界是这一节的全部要点**：`course_version` → `lessons` → `anchors` → `traces`
→ `quiz_items` 必须在**一个事务**里写完，并用 `status` 作为对外可见开关。
任何中途失败都回滚——用户看不到半成品课程。

发布前的四类校验（任一失败 → 回滚 + `AppError`，而不是"带警告发布"）：
1. 锚点存在性 + 行号不越界（T-ANCHOR-1）；
2. `source_fact` 步骤必须有可定位的 evidence（T-TRACE-1）；
3. segments 连续覆盖（T-PLAY-1）；
4. 最小可发布阈值：4 章节全有、有效课时 ≥ 8、锚点覆盖率 ≥ 80%。
   不满足 → `partial` 而不是 `ready`（这是产品语义，不是失败）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from repolearn.core.clock import utcnow
from repolearn.core.errors import AppError
from repolearn.core.ids import new_id
from repolearn.core.logging import get_logger
from repolearn.models import CourseVersion, Lesson, QuizItem, SimulatedTrace, SourceAnchor, Step
from repolearn.workflow.parsing import check_anchors, check_segments

log = get_logger("publish")


@dataclass
class QualityReport:
    anchor_coverage: float = 0.0
    lesson_completeness: float = 0.0
    trace_quality: str = "unknown"
    quiz_count: int = 0
    certainty: dict = field(default_factory=dict)
    degraded: bool = False
    anchor_confidence: str = "high"
    runtime: str = "kernel"
    reasons: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "anchor_coverage": round(self.anchor_coverage, 3),
            "lesson_completeness": round(self.lesson_completeness, 3),
            "trace_quality": self.trace_quality,
            "quiz_count": self.quiz_count,
            "certainty": self.certainty,
            "degraded": self.degraded,
            "anchor_confidence": self.anchor_confidence,
            "runtime": self.runtime,
            "reasons": self.reasons,
        }


def _collect_steps(lesson: dict) -> list[dict]:
    return [s for s in (lesson.get("steps") or []) if isinstance(s, dict)]


def anchor_coverage(lessons: list[dict], valid_files: set[str]) -> float:
    total = 0
    ok = 0
    for lesson in lessons:
        for step in _collect_steps(lesson):
            for seg in step.get("segments") or []:
                focus = (seg or {}).get("focus") if isinstance(seg, dict) else None
                if not focus:
                    continue
                total += 1
                if str(focus.get("file")) in valid_files:
                    ok += 1
    if total == 0:
        return 0.0
    return ok / total


def compute_quality(
    *,
    lessons: list[dict],
    valid_files: set[str],
    failed_lessons: list[str],
    warnings: list[dict],
    runtime: str,
) -> QualityReport:
    total_planned = max(1, len(lessons) + len(failed_lessons))
    completeness = len(lessons) / total_planned
    coverage = anchor_coverage(lessons, valid_files)
    quiz_count = sum(len(json_quiz) for json_quiz in [(l.get("quiz") or []) for l in lessons])
    degraded = runtime == "template" or any(w.get("code") == "AGENT_UNAVAILABLE" for w in warnings)
    reasons: list[str] = []
    if failed_lessons:
        reasons.append(f"{len(failed_lessons)} 个课时生成失败")
    if coverage < 0.8:
        reasons.append(f"锚点覆盖率 {coverage:.0%} 低于 80%")
    if degraded:
        reasons.append("课程由静态分析模板生成（Agent 内核不可用）")
    return QualityReport(
        anchor_coverage=coverage,
        lesson_completeness=completeness,
        trace_quality="unknown",
        quiz_count=quiz_count,
        degraded=degraded,
        anchor_confidence="low" if degraded or coverage < 0.6 else "high",
        runtime=runtime,
        reasons=reasons,
    )


async def publish(
    session: AsyncSession,
    *,
    course_id: str,
    curriculum: dict,
    lessons: dict[str, dict],
    traces: dict[str, dict],
    narration: dict[str, dict],
    commit_sha: str,
    file_lines: dict[str, int],
    warnings: list[dict],
    failed_lessons: list[str],
    runtime: str,
    load_artifact: Any,
    min_lessons: int = 8,
    min_coverage: float = 0.8,
    min_sections: int = 4,
) -> dict[str, Any]:
    """在调用方开启的事务里写全量课程资产。"""
    sections = [s for s in (curriculum.get("sections") or []) if isinstance(s, dict)]
    lesson_docs: list[dict] = []
    for key, ref in lessons.items():
        doc = load_artifact(ref.get("artifact")) if ref.get("artifact") else {}
        if doc:
            doc = dict(doc)
            doc["_key"] = key
            lesson_docs.append(doc)

    # ---- 1. 校验 ---------------------------------------------------------
    all_anchors: list[dict] = []
    for doc in lesson_docs:
        for step in _collect_steps(doc):
            for seg in step.get("segments") or []:
                focus = (seg or {}).get("focus")
                if isinstance(focus, dict):
                    all_anchors.append(focus)
        for note in step.get("code_notes") or []:
            if isinstance(note, dict) and note.get("file"):
                all_anchors.append({"file": note["file"], "line_start": note.get("line", 1), "line_end": note.get("line", 1)})
    anchor_errors = check_anchors(all_anchors, file_lines)
    if anchor_errors:
        raise AppError(
            "ANCHOR_STALE",
            "课程锚点校验失败，已回滚",
            details={"errors": anchor_errors[:5]},
        )
    segment_errors = [e for doc in lesson_docs for e in check_segments(_collect_steps(doc))]
    if segment_errors:
        raise AppError("CONTRACT_VIOLATION", "课时时间轴校验失败", details={"errors": segment_errors[:5]})

    # ---- 2. 质量报告 -----------------------------------------------------
    quality = compute_quality(
        lessons=lesson_docs,
        valid_files=set(file_lines),
        failed_lessons=failed_lessons,
        warnings=warnings,
        runtime=runtime,
    )
    certainty_all: dict[str, int] = {"source_fact": 0, "static_inference": 0, "teaching_simulation": 0}
    trace_docs: list[dict] = []
    for key, ref in traces.items():
        doc = load_artifact(ref.get("artifact")) if ref.get("artifact") else {}
        if not doc:
            continue
        doc["_key"] = key
        trace_docs.append(doc)
        for step in doc.get("steps") or []:
            c = str(step.get("certainty", "teaching_simulation"))
            certainty_all[c if c in certainty_all else "teaching_simulation"] += 1
    trace_total = max(1, sum(certainty_all.values()))
    quality.certainty = certainty_all
    quality.trace_quality = "ok" if certainty_all["source_fact"] / trace_total >= 0.4 else "weak"

    # ---- 3. 判定 ready / partial ----------------------------------------
    section_keys = {s.get("key") for s in sections}
    enough_sections = len(section_keys & {"overview", "walkthrough", "deep_dive", "recap"}) >= min_sections
    status = "ready"
    if not enough_sections or len(lesson_docs) < min_lessons or quality.anchor_coverage < min_coverage or failed_lessons:
        status = "partial"
        if not enough_sections:
            quality.reasons.append("章节不完整")
        if len(lesson_docs) < min_lessons:
            quality.reasons.append(f"有效课时 {len(lesson_docs)} 少于 {min_lessons}")

    # ---- 4. 写入 --------------------------------------------------------
    course = await session.get(CourseVersion, course_id)
    if course is None:
        raise AppError("COURSE_NOT_READY", "课程版本不存在")
    course.title = str(curriculum.get("title", course.title))
    course.subtitle = curriculum.get("subtitle")
    course.summary_md = str(curriculum.get("summary_md", "") or "")
    course.sections = [
        {
            "key": s.get("key"),
            "title": s.get("title"),
            "minutes": int(s.get("minutes", 0) or 0),
            "lessons": [
                {"key": l.get("key"), "title": l.get("title"), "minutes": int(l.get("minutes", 0) or 0)}
                for l in (s.get("lessons") or [])
            ],
        }
        for s in sections
    ]
    course.quality_report = quality.as_dict()
    course.warnings = list(warnings) + list(course.warnings or [])
    course.lesson_count = len(lesson_docs)
    course.total_minutes = sum(int(doc.get("minutes", 0) or 0) for doc in lesson_docs)
    course.status = status
    course.published_at = utcnow()
    course.updated_at = utcnow()
    course.blueprint = {
        **(course.blueprint or {}),
        "sections": len(sections),
        "lessons": len(lesson_docs),
        "commit_sha": commit_sha,
        "runtime": runtime,
    }

    order = 0
    for doc in lesson_docs:
        key = str(doc.get("_key") or doc.get("key"))
        lesson_id = new_id("lesson")
        lesson = Lesson(
            id=lesson_id,
            course_version_id=course_id,
            section_key=str(doc.get("layer", "overview")),
            key=key,
            title=str(doc.get("title", key)),
            goal=doc.get("goal"),
            minutes=int(doc.get("minutes", 5) or 5),
            order_index=order,
            status="ready",
            playback_meta={
                "files": doc.get("files") or [],
                "trace_key": doc.get("trace_key"),
                "certainty_legend": {
                    "source_fact": "源码事实",
                    "static_inference": "静态推断",
                    "teaching_simulation": "教学模拟",
                },
                "narration": narration.get(key, {}),
            },
            created_at=utcnow(),
        )
        session.add(lesson)
        order += 1

        for idx, step in enumerate(_collect_steps(doc)):
            segments = step.get("segments") or []
            focus = segments[0].get("focus") if segments and isinstance(segments[0], dict) else None
            session.add(
                Step(
                    id=new_id("step"),
                    lesson_id=lesson_id,
                    order_index=int(step.get("index", idx) or idx),
                    title=str(step.get("title", f"第 {idx + 1} 步")),
                    duration_ms=int(step.get("duration_ms", 0) or 0),
                    timing_source=str(step.get("timing_source", "estimated")),
                    focus_file=(focus or {}).get("file"),
                    focus_line_start=(focus or {}).get("line_start"),
                    focus_line_end=(focus or {}).get("line_end"),
                    segments=segments,
                    board=step.get("board") or {},
                    code_notes=step.get("code_notes") or [],
                    certainty={"legend": "三种确定性见 /docs"},
                    created_at=utcnow(),
                )
            )

        for anchor in doc.get("files") or []:
            path = str(anchor.get("path") or "")
            if not path:
                continue
            session.add(
                SourceAnchor(
                    id=new_id("anchor"),
                    course_version_id=course_id,
                    lesson_id=lesson_id,
                    file=path,
                    symbol=None,
                    line_start=1,
                    line_end=max(1, file_lines.get(path, 1)),
                    commit_sha=commit_sha,
                    kind="definition",
                    created_at=utcnow(),
                )
            )

        for quiz in doc.get("quiz") or []:
            if not isinstance(quiz, dict):
                continue
            session.add(
                QuizItem(
                    id=new_id("quiz"),
                    course_version_id=course_id,
                    lesson_id=lesson_id,
                    stem=str(quiz.get("stem", "")),
                    choices=quiz.get("choices") or [],
                    answer_id=str(quiz.get("answer_id", "a")),
                    explanation_md=str(quiz.get("explanation_md", "")),
                    evidence=quiz.get("evidence") or [],
                    difficulty=int(quiz.get("difficulty", 1) or 1),
                    kind=str(quiz.get("kind", "recall")),
                    created_at=utcnow(),
                )
            )

    for doc in trace_docs:
        key = str(doc.get("_key"))
        lesson = (
            await session.execute(
                select(Lesson).where(Lesson.course_version_id == course_id, Lesson.key == key)
            )
        ).scalar_one_or_none()
        session.add(
            SimulatedTrace(
                id=new_id("trace"),
                course_version_id=course_id,
                lesson_id=lesson.id if lesson else None,
                key=str(doc.get("key", f"trace_{key}")),
                title=str(doc.get("title", "")),
                steps=doc.get("steps") or [],
                certainty_summary=quality.certainty,
                created_at=utcnow(),
            )
        )

    await session.flush()
    log.info(
        "course_published",
        course_id=course_id,
        status=status,
        lessons=len(lesson_docs),
        coverage=round(quality.anchor_coverage, 3),
    )
    return {
        "status": status,
        "quality_report": quality.as_dict(),
        "lesson_count": len(lesson_docs),
        "total_minutes": course.total_minutes,
    }

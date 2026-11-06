"""质量服务（spec §3.13 质量报告 / `scripts/backfill_quality.py`）。

`quality_report` 是信任来源而不是装饰：P02 与 P08 用它展示"内容可信度"。
因此这里的计算必须与 `workflow/publish.py` 使用**同一口径**——两处各算一套
会让同一个课程在准备页和完课页显示不同的数字，而那是用户最先发现的一类 bug。
"""

from __future__ import annotations

from sqlalchemy import select

from repolearn.core.clock import utcnow
from repolearn.core.logging import get_logger
from repolearn.models import CourseVersion, Lesson, QuizItem, SimulatedTrace, SourceAnchor, Step
from repolearn.workflow.publish import anchor_coverage, compute_quality

log = get_logger("quality_service")


async def recompute(session, course_id: str, *, runtime: str | None = None) -> dict:
    course = await session.get(CourseVersion, course_id)
    if course is None:
        return {}
    lessons = (
        await session.execute(select(Lesson).where(Lesson.course_version_id == course_id))
    ).scalars().all()
    anchors = (
        await session.execute(select(SourceAnchor).where(SourceAnchor.course_version_id == course_id))
    ).scalars().all()
    lesson_docs: list[dict] = []
    for lesson in lessons:
        steps = (
            await session.execute(select(Step).where(Step.lesson_id == lesson.id).order_by(Step.order_index))
        ).scalars().all()
        quiz = (
            await session.execute(select(QuizItem).where(QuizItem.lesson_id == lesson.id))
        ).scalars().all()
        lesson_docs.append(
            {
                "key": lesson.key,
                "minutes": lesson.minutes,
                "steps": [
                    {
                        "index": s.order_index,
                        "segments": s.segments or [],
                        "code_notes": s.code_notes or [],
                    }
                    for s in steps
                ],
                "quiz": [{"evidence": q.evidence or []} for q in quiz],
            }
        )
    valid_files = {a.file for a in anchors}
    report = compute_quality(
        lessons=lesson_docs,
        valid_files=valid_files,
        failed_lessons=[str(w.get("lesson_key", "")) for w in (course.warnings or []) if w.get("code") == "LESSON_FAILED"],
        warnings=list(course.warnings or []),
        runtime=runtime or str((course.quality_report or {}).get("runtime", "kernel")),
    )
    traces = (
        await session.execute(select(SimulatedTrace).where(SimulatedTrace.course_version_id == course_id))
    ).scalars().all()
    certainty = {"source_fact": 0, "static_inference": 0, "teaching_simulation": 0}
    for trace in traces:
        for step in trace.steps or []:
            key = str(step.get("certainty", "teaching_simulation"))
            certainty[key if key in certainty else "teaching_simulation"] += 1
    total = max(1, sum(certainty.values()))
    report.certainty = certainty
    report.trace_quality = "ok" if certainty["source_fact"] / total >= 0.4 else "weak"
    report.quiz_count = sum(len(doc["quiz"]) for doc in lesson_docs)
    if not valid_files:
        report.anchor_coverage = anchor_coverage(lesson_docs, valid_files)
    course.quality_report = report.as_dict()
    course.updated_at = utcnow()
    await session.flush()
    log.info("quality_recomputed", course_id=course_id, coverage=round(report.anchor_coverage, 3))
    return course.quality_report


async def backfill_all(session) -> dict[str, int]:
    courses = (
        await session.execute(select(CourseVersion).where(CourseVersion.deleted_at.is_(None)))
    ).scalars().all()
    updated = 0
    for course in courses:
        report = await recompute(session, course.id)
        if report:
            updated += 1
    return {"courses": len(courses), "updated": updated}

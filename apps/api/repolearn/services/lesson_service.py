"""课时与播放（spec §5.2 / §5.3）。

`PlaybackBundle` 由 `lessons.playback_meta` + `steps` 按 `order_index` 拼装。
**拼装是只读的，永远不回写**——这条约束（P1-3）解决的是"同一批数据两处写"导致
播放到第 3 步又跳回第 1 步那类 bug。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select

from repolearn.core.errors import AppError
from repolearn.core.logging import get_logger
from repolearn.models import Lesson, QuizItem, SimulatedTrace, Step
from repolearn.schemas.lesson import LessonBrief, LessonDetail, LessonListResponse, LessonSection
from repolearn.schemas.playback import (
    AudioRef,
    Board,
    CodeNote,
    FileRef,
    FocusRef,
    LessonBriefOut,
    PlaybackBundle,
    QuizChoice,
    QuizItemOut,
    Segment,
    StepBundle,
    TraceOut,
    TraceStepOut,
)
from repolearn.services.course_service import get_course

log = get_logger("lesson_service")

CERTAINTY_LEGEND = {
    "source_fact": "源码事实",
    "static_inference": "静态推断",
    "teaching_simulation": "教学模拟",
}


async def list_lessons(session, course_id: str) -> LessonListResponse:
    course, _repo = await get_course(session, course_id)
    lessons = (
        await session.execute(
            select(Lesson).where(Lesson.course_version_id == course_id).order_by(Lesson.order_index)
        )
    ).scalars().all()
    step_counts = await _step_counts(session, [l.id for l in lessons])
    sections: list[LessonSection] = []
    index: dict[str, LessonSection] = {}
    for section in course.sections or []:
        if not isinstance(section, dict):
            continue
        key = str(section.get("key", ""))
        item = LessonSection(key=key, title=str(section.get("title", key)), minutes=int(section.get("minutes", 0) or 0))
        index[key] = item
        sections.append(item)
    for lesson in lessons:
        target = index.get(lesson.section_key)
        if target is None:
            target = LessonSection(key=lesson.section_key, title=lesson.section_key, minutes=0)
            index[lesson.section_key] = target
            sections.append(target)
        target.lessons.append(
            LessonBrief(
                key=lesson.key,
                title=lesson.title,
                status=lesson.status,
                minutes=lesson.minutes,
                step_count=step_counts.get(lesson.id, 0),
            )
        )
    return LessonListResponse(sections=sections)


async def _step_counts(session, lesson_ids: list[str]) -> dict[str, int]:
    if not lesson_ids:
        return {}
    rows = (
        await session.execute(select(Step.lesson_id, Step.id).where(Step.lesson_id.in_(lesson_ids)))
    ).all()
    counts: dict[str, int] = {}
    for lesson_id, _ in rows:
        counts[lesson_id] = counts.get(lesson_id, 0) + 1
    return counts


async def get_lesson(session, course_id: str, key: str) -> tuple[Lesson, list[Step], list[QuizItem]]:
    course, _repo = await get_course(session, course_id, require_ready=True)
    lesson = (
        await session.execute(
            select(Lesson).where(Lesson.course_version_id == course_id, Lesson.key == key)
        )
    ).scalar_one_or_none()
    if lesson is None:
        raise AppError("COURSE_NOT_READY", f"课时 {key} 不存在", status=404)
    steps = (
        await session.execute(select(Step).where(Step.lesson_id == lesson.id).order_by(Step.order_index))
    ).scalars().all()
    quiz = (
        await session.execute(select(QuizItem).where(QuizItem.lesson_id == lesson.id).order_by(QuizItem.created_at))
    ).scalars().all()
    return lesson, list(steps), list(quiz)


async def lesson_detail(session, course_id: str, key: str) -> LessonDetail:
    lesson, steps, quiz = await get_lesson(session, course_id, key)
    meta = dict(lesson.playback_meta or {})
    return LessonDetail(
        key=lesson.key,
        title=lesson.title,
        layer=lesson.section_key,
        minutes=lesson.minutes,
        goal=lesson.goal,
        anchors=list(meta.get("anchors") or []),
        steps=[
            {
                "index": s.order_index,
                "title": s.title,
                "duration_ms": s.duration_ms,
                "segments": s.segments or [],
                "board": s.board or {},
                "code_notes": s.code_notes or [],
            }
            for s in steps
        ],
        quiz=[
            {
                "id": q.id,
                "stem": q.stem,
                "choices": q.choices or [],
                "answer_id": q.answer_id,
                "explanation_md": q.explanation_md,
                "evidence": q.evidence or [],
            }
            for q in quiz
        ],
        files=list(meta.get("files") or []),
        trace_key=meta.get("trace_key"),
    )


async def playback(session, course_id: str, key: str) -> PlaybackBundle:
    """拼装 `PlaybackBundle`（spec §5.3）。一次拉全，避免播放中请求。"""
    course, _repo = await get_course(session, course_id, require_ready=True)
    lesson, steps, quiz = await get_lesson(session, course_id, key)
    meta = dict(lesson.playback_meta or {})
    narration = dict(meta.get("narration") or {})

    quiz_out = [
        QuizItemOut(
            id=q.id,
            stem=q.stem,
            choices=[QuizChoice(id=str(c.get("id", "")), text=str(c.get("text", ""))) for c in (q.choices or []) if isinstance(c, dict)],
            answer_id=q.answer_id,
            explanation_md=q.explanation_md,
            evidence=list(q.evidence or []),
        )
        for q in quiz
    ]

    step_bundles: list[StepBundle] = []
    for step in steps:
        segments = [
            Segment(
                id=str(seg.get("id", f"s{i}")),
                text=str(seg.get("text", "")),
                start_ms=int(seg.get("start_ms", 0) or 0),
                end_ms=int(seg.get("end_ms", 0) or 0),
                focus=(
                    FocusRef(
                        file=str((seg.get("focus") or {}).get("file", "")),
                        line_start=int((seg.get("focus") or {}).get("line_start", 1) or 1),
                        line_end=int((seg.get("focus") or {}).get("line_end", 1) or 1),
                    )
                    if isinstance(seg.get("focus"), dict) and (seg.get("focus") or {}).get("file")
                    else None
                ),
                board_actions=list(seg.get("board_actions") or []),
                subtitle_style=str(seg.get("subtitle_style", "normal")),
            )
            for i, seg in enumerate(seg for seg in (step.segments or []) if isinstance(seg, dict))
        ]
        audio = None
        # 优先按 step 取音轨（N8 现在每步合成一条）；旧课程数据是课时级
        # `narration.audio`，作为兼容分支保留——否则已发布的课程会突然全部失声。
        step_narration = (narration.get("steps") or {}).get(str(step.order_index))
        audio_payload = (step_narration or {}).get("audio") if isinstance(step_narration, dict) else None
        if not isinstance(audio_payload, dict):
            audio_payload = narration.get("audio")
        if isinstance(audio_payload, dict) and audio_payload.get("url"):
            audio = AudioRef(
                url=str(audio_payload["url"]),
                duration_ms=int(audio_payload.get("duration_ms", 0) or 0),
                voice=str(audio_payload.get("voice", "")),
            )
        board = None
        if isinstance(step.board, dict) and step.board.get("mermaid"):
            board = Board(
                kind=str(step.board.get("kind", "architecture")),
                mermaid=str(step.board.get("mermaid", "")),
                nodes=list(step.board.get("nodes") or []),
            )
        step_bundles.append(
            StepBundle(
                index=step.order_index,
                title=step.title,
                duration_ms=step.duration_ms,
                timing_source=str(
                    (step_narration or {}).get("timing_source")
                    or narration.get("timing_source", step.timing_source)
                ),
                audio=audio,
                segments=segments,
                board=board,
                code_notes=[
                    CodeNote(file=str(n.get("file", "")), line=int(n.get("line", 1) or 1), text=str(n.get("text", "")))
                    for n in (step.code_notes or [])
                    if isinstance(n, dict) and n.get("file")
                ],
                quiz=quiz_out,
                certainty_legend=CERTAINTY_LEGEND,
            )
        )

    trace = await _trace_for(session, course_id, lesson)
    files = [
        FileRef(
            path=str(f.get("path", "")),
            content_ref=f"/api/courses/{course_id}/files?path={f.get('path', '')}",
            lang=str(f.get("lang", "text")),
            line_count=int(f.get("line_count", 0) or 0),
        )
        for f in (meta.get("files") or [])
        if isinstance(f, dict)
    ]
    return PlaybackBundle(
        course_id=course_id,
        commit_sha=course.commit_sha,
        lesson=LessonBriefOut(
            key=lesson.key, title=lesson.title, layer=lesson.section_key, minutes=lesson.minutes
        ),
        steps=step_bundles,
        files=files,
        trace=trace,
    )


async def _trace_for(session, course_id: str, lesson: Lesson) -> TraceOut | None:
    row = (
        await session.execute(
            select(SimulatedTrace)
            .where(SimulatedTrace.course_version_id == course_id)
            .where((SimulatedTrace.lesson_id == lesson.id) | (SimulatedTrace.lesson_id.is_(None)))
            .order_by(SimulatedTrace.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if row is None:
        return None
    return TraceOut(
        id=row.id,
        steps=[
            TraceStepOut(
                index=int(s.get("index", i) or i),
                title=str(s.get("title", "")),
                certainty=str(s.get("certainty", "teaching_simulation")),
                evidence=list(s.get("evidence") or []),
                variables=list(s.get("variables") or []),
                note=s.get("note"),
            )
            for i, s in enumerate(row.steps or [])
            if isinstance(s, dict)
        ],
        certainty_summary=dict(row.certainty_summary or {}),
    )


def validate_playback(bundle: dict[str, Any]) -> list[str]:
    """发布前/读取前的 segments 连续性校验（T-PLAY-1）。

    放在读路径上也调用一次，是因为历史数据可能来自旧版本；宁可让一个课时
    报 422，也不要让播放器在用户面前跳帧。
    """
    errors: list[str] = []
    for step in bundle.get("steps") or []:
        segments = sorted(step.get("segments") or [], key=lambda s: s.get("start_ms", 0))
        if not segments:
            continue
        cursor = 0
        for seg in segments:
            if seg.get("start_ms", 0) > cursor:
                errors.append(f"step {step.get('index')} 在 {cursor}–{seg.get('start_ms')} 之间有空洞")
            cursor = max(cursor, int(seg.get("end_ms", 0) or 0))
    return errors

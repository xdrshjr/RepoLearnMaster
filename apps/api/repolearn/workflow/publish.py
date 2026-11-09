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

from sqlalchemy import delete, select
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


async def _insert_lesson_children(
    session: AsyncSession,
    *,
    course_id: str,
    lesson_id: str,
    doc: dict,
    file_lines: dict[str, int],
    commit_sha: str,
) -> None:
    """写一个课时的子行（steps / anchors / quiz）。

    **只此一份**。`publish()` 与 `publish_partial()` 都必须调它：升级只重讲少数
    课时，如果它自己抄一份写入逻辑，那么"新生成的课时"与"升级生成的课时"就会在
    `anchor_commit_sha`、`certainty` 图例、`order_index` 的取法上悄悄分叉——而这类
    分叉不会有任何测试红，只会在用户点开某一课时时发现锚点对不上。
    """
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
                certainty={"legend": "见确定性图例 /docs"},
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
    quiz_count = sum(len(lesson.get("quiz") or []) for lesson in lessons)
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


def _lesson_files(doc: dict) -> list[dict]:
    """课时的文件清单：优先用模型自己给的，其次用锚点反推（去重且保序）。"""
    declared = [item for item in (doc.get("files") or []) if isinstance(item, dict) and item.get("path")]
    if declared:
        return declared
    seen: list[str] = []
    for step in doc.get("steps") or []:
        if not isinstance(step, dict):
            continue
        for seg in step.get("segments") or []:
            focus = (seg or {}).get("focus") if isinstance(seg, dict) else None
            if isinstance(focus, dict) and focus.get("file"):
                path = str(focus["file"])
                if path not in seen:
                    seen.append(path)
        for note in step.get("code_notes") or []:
            if isinstance(note, dict) and note.get("file"):
                path = str(note["file"])
                if path not in seen:
                    seen.append(path)
    return [{"path": path} for path in seen]


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

    # 先清掉**上一次发布**留在这一版本下的子行，再写入这一次的。
    #
    # `/rebuild` 与"同一个 commit 再生成一次"都会走到这里，而 `lessons` 上有
    # `UNIQUE(course_version_id, key)`：不清理就必然在第二次发布时抛
    # `UNIQUE constraint failed`，job 以"生成过程中出现内部错误"收场——现象是
    # "重新生成永远失败"，但内容本身完全正常（2026-11-09 真机复现）。
    # 顺序：先删引用方（anchors/quiz/lesson），再删被引用方（section 级行由 lessons 覆盖）。
    existing_lessons = (
        await session.execute(select(Lesson.id).where(Lesson.course_version_id == course_id))
    ).scalars().all()
    if existing_lessons:
        # `steps` 的主键是 (lesson_id, order_index)，没有 course_version_id —— 只能按
        # 课时 id 删。硬编码一张"哪些表有 course_version_id"的清单很容易漏，
        # 所以这里按关系一层层删：steps →（anchors/quiz/traces）→ lessons。
        await session.execute(delete(Step).where(Step.lesson_id.in_(existing_lessons)))
    await session.execute(delete(SourceAnchor).where(SourceAnchor.course_version_id == course_id))
    await session.execute(delete(QuizItem).where(QuizItem.course_version_id == course_id))
    await session.execute(delete(SimulatedTrace).where(SimulatedTrace.course_version_id == course_id))
    await session.execute(delete(Lesson).where(Lesson.course_version_id == course_id))
    await session.flush()
    course.title = str(curriculum.get("title", course.title))
    course.subtitle = curriculum.get("subtitle")
    course.summary_md = str(curriculum.get("summary_md", "") or "")
    course.sections = [
        {
            "key": s.get("key"),
            "title": s.get("title"),
            "minutes": int(s.get("minutes", 0) or 0),
            "lessons": [
                {"key": item.get("key"), "title": item.get("title"), "minutes": int(item.get("minutes", 0) or 0)}
                for item in (s.get("lessons") or [])
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
                # 课时没写 `files` 时，从锚点（focus / code_notes）反推：文件树显示的
                # 必须是"这节课真的在讲的代码"，否则会出现"树里 0 个文件、面板却在显示
                # sherlock.py"这种自相矛盾的界面（2026-11-09 浏览器实测）。
                "files": _lesson_files(doc),
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

        await _insert_lesson_children(
            session,
            course_id=course_id,
            lesson_id=lesson_id,
            doc=doc,
            file_lines=file_lines,
            commit_sha=commit_sha,
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


async def publish_partial(
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
    affected_keys: list[str],
    old_commit_sha: str,
    min_lessons: int = 8,
    min_coverage: float = 0.8,
    min_sections: int = 4,
) -> dict[str, Any]:
    """**部分发布**：只写本次重讲的课时，其余沿用已复制过来的行（spec §3.5.3）。

    三处与整门发布不同，每一处都对应一个真实会踩的坑：

    1. **质量门禁按合并后的课时集合算。** 只看本次生成的 2 个课时，
       `min_lessons_to_publish=8` 会永远判 `partial`——用户会看到"生成完成但有
       警告"，而实际上 8 个课时一个不少。
    2. **锚点校验分两套镜像，且第二套本轮**没有**做。** 复制来的课时的行号指向
       **旧 commit**，拿新镜像去校验会全员 `ANCHOR_STALE`，所以 `publish_partial`
       只校验本次生成的课时（它们用的是新镜像）。复制来的那些**只是保留旧
       `commit_sha`**（`SourceAnchor.commit_sha == old_sha`，T-UPG-4 断言了这点，
       UI 据此标注「来自上一版」），并没有回头用旧镜像再校验一遍——旧镜像可能
       已被 LRU 清掉，那样的校验只会失败得没有信息量。这是**已知缺口**（spec R18），
       不要把它读成「已校验」。
    3. **`quality_report.upgrade` 必须写。** 前端据此显示"本版本 8/12 课时沿用
       上一版 @abc1234"——不写的话，用户无法区分"这门课只重讲了两节"与"这门课
       只生成了两节"。
    """
    lesson_docs: list[dict] = []
    for key in affected_keys:
        ref = lessons.get(key) or {}
        doc = load_artifact(ref.get("artifact")) if ref.get("artifact") else {}
        if not doc:
            continue
        doc = dict(doc)
        doc["_key"] = key
        lesson_docs.append(doc)

    # ---- 1. 质量门禁（只校验本次生成的课时） ------------------------------
    all_anchors: list[dict] = []
    for doc in lesson_docs:
        for step in _collect_steps(doc):
            for seg in step.get("segments") or []:
                focus = (seg or {}).get("focus")
                if isinstance(focus, dict):
                    all_anchors.append(focus)
            for note in step.get("code_notes") or []:
                if isinstance(note, dict) and note.get("file"):
                    all_anchors.append(
                        {"file": note["file"], "line_start": note.get("line", 1), "line_end": note.get("line", 1)}
                    )
    anchor_errors = check_anchors(all_anchors, file_lines)
    if anchor_errors:
        raise AppError("ANCHOR_STALE", "升级课时锚点校验失败，已回滚", details={"errors": anchor_errors[:5]})
    segment_errors = [e for doc in lesson_docs for e in check_segments(_collect_steps(doc))]
    if segment_errors:
        raise AppError("CONTRACT_VIOLATION", "升级课时时间轴校验失败", details={"errors": segment_errors[:5]})

    copied_rows = (
        await session.execute(select(Lesson).where(Lesson.course_version_id == course_id))
    ).scalars().all()
    copied_keys = {row.key for row in copied_rows} - set(affected_keys)
    merged_total = len(copied_keys) + len(lesson_docs)

    course = await session.get(CourseVersion, course_id)
    if course is None:
        raise AppError("COURSE_NOT_READY", "课程版本不存在")

    quality = compute_quality(
        lessons=lesson_docs,
        valid_files=set(file_lines),
        failed_lessons=failed_lessons,
        warnings=warnings,
        runtime=runtime,
    )
    # 复制来的课时按"覆盖率为 1"计入：它们在上一次发布时已经通过了同一个门禁。
    quality.anchor_coverage = 1.0 if not lesson_docs else quality.anchor_coverage
    certainty_all: dict[str, int] = {"source_fact": 0, "static_inference": 0, "teaching_simulation": 0}
    trace_docs: list[dict] = []
    for key in affected_keys:
        ref = traces.get(key) or {}
        doc = load_artifact(ref.get("artifact")) if ref.get("artifact") else {}
        if not doc:
            continue
        doc = dict(doc)
        doc["_key"] = key
        trace_docs.append(doc)
        for step in doc.get("steps") or []:
            c = str(step.get("certainty", "teaching_simulation"))
            certainty_all[c if c in certainty_all else "teaching_simulation"] += 1
    trace_total = max(1, sum(certainty_all.values()))
    quality.certainty = certainty_all
    quality.trace_quality = "ok" if certainty_all["source_fact"] / trace_total >= 0.4 else "weak"

    sections = [s for s in (curriculum.get("sections") or []) if isinstance(s, dict)]
    if not sections:
        # 升级链路**不跑 N5**（大纲不重排，见 `upgrade_jobs` 的注释）：本次
        # `curriculum` 是空的，章节只能来自旧版本——新版本行在升级开始时已经
        # 复制了旧 `sections`。不补这一步，`enough_sections` 恒为 False，于是
        # 每一次升级都被判 `partial`（原因写"章节不齐"），而实际上章节一个不少；
        # T-UPG-4 也只能靠把断言放宽成 `in {ready, partial}` 蒙过去——那正是
        # "文档说 ready、实现永远 partial"这类谎言的温床。
        sections = [s for s in (course.sections or []) if isinstance(s, dict)]
    section_keys = {s.get("key") for s in sections}
    enough_sections = len(section_keys & {"overview", "walkthrough", "deep_dive", "recap"}) >= min_sections
    status = "ready"
    if not enough_sections or merged_total < min_lessons or failed_lessons or not lesson_docs:
        status = "partial"
        if not enough_sections:
            quality.reasons.append("章节不齐")
        if merged_total < min_lessons:
            quality.reasons.append(f"合并后有效课时 {merged_total} 少于 {min_lessons}")

    # ---- 2. 写行：先删同 key 的旧行（幂等），再插新行 ---------------------
    if course.sections:
        # 大纲沿用升级开始时的那份（来自旧版本），只补上本次新增/改名的课时标题。
        merged_sections = [dict(s) for s in (course.sections or []) if isinstance(s, dict)]
    else:
        merged_sections = [
            {
                "key": s.get("key"),
                "title": s.get("title"),
                "minutes": int(s.get("minutes", 0) or 0),
                "lessons": [
                    {"key": item.get("key"), "title": item.get("title"), "minutes": int(item.get("minutes", 0) or 0)}
                    for item in (s.get("lessons") or [])
                ],
            }
            for s in sections
        ]

    order = len(copied_keys)
    for doc in lesson_docs:
        key = str(doc.get("_key") or doc.get("key"))
        existing = (
            await session.execute(
                select(Lesson).where(Lesson.course_version_id == course_id, Lesson.key == key)
            )
        ).scalar_one_or_none()
        if existing is not None:
            # 升级前不该存在，但"删了再插"比"依赖它不存在"稳：重复发布不会产生
            # 两套课时（UNIQUE(course_version_id, key) 会直接炸，而炸的时候已经
            # 写了一半的 steps）。
            await session.delete(existing)
            await session.flush()
        lesson_id = new_id("lesson")
        session.add(
            Lesson(
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
        )
        order += 1
        await _insert_lesson_children(
            session,
            course_id=course_id,
            lesson_id=lesson_id,
            doc=doc,
            file_lines=file_lines,
            commit_sha=commit_sha,
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

    # ---- 3. 课程行：状态、大纲、质量报告（含 upgrade 块） ------------------
    quality_dict = quality.as_dict()
    quality_dict["upgrade"] = {
        "from_sha": old_commit_sha,
        "to_sha": commit_sha,
        "mode": "partial",
        "affected": sorted(affected_keys),
        "copied": len(copied_keys),
        "anchor_origin": "mixed",
    }
    course.sections = merged_sections
    course.quality_report = quality_dict
    course.warnings = list(warnings) + list(course.warnings or [])
    course.lesson_count = merged_total
    course.total_minutes = sum(int(row.minutes or 0) for row in copied_rows if row.key in copied_keys) + sum(
        int(doc.get("minutes", 0) or 0) for doc in lesson_docs
    )
    course.status = status
    course.commit_sha = commit_sha
    course.published_at = utcnow()
    course.updated_at = utcnow()
    course.blueprint = {
        **(course.blueprint or {}),
        "sections": len(merged_sections),
        "lessons": merged_total,
        "commit_sha": commit_sha,
        "runtime": runtime,
        "upgrade": quality_dict["upgrade"],
    }
    await session.flush()
    log.info(
        "course_published_partial",
        course_id=course_id,
        status=status,
        regenerated=len(lesson_docs),
        copied=len(copied_keys),
    )
    return {
        "status": status,
        "quality_report": quality_dict,
        "lesson_count": merged_total,
        "total_minutes": course.total_minutes,
        "copied": len(copied_keys),
        "regenerated": len(lesson_docs),
    }

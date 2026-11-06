"""进度、答题与完课复盘（spec §5.2 第三组 / §6.2 quiz_attempts）。

答题幂等的实现方式值得单独说：`UNIQUE(user_id, quiz_item_id)` + `INSERT ... ON CONFLICT
DO NOTHING` + 读回首次结果。**不靠前端去重**——recap 的答题统计、`/metrics` 的
正确率、能力雷达三项都从这张表聚合，前端去重会让统计随刷新而漂移。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from repolearn.core.clock import utcnow
from repolearn.core.errors import AppError
from repolearn.core.ids import new_id
from repolearn.core.logging import get_logger
from repolearn.models import (
    CourseVersion,
    Lesson,
    QuizAttempt,
    QuizItem,
    SimulatedTrace,
    User,
    UserProgress,
)
from repolearn.schemas.progress import ProgressResponse, ProgressUpdate, QuizAnswerResponse, RecapResponse
from repolearn.services.course_service import get_course

log = get_logger("progress_service")

LOCAL_USER_ID = "usr_local"


async def ensure_local_user(session) -> User:
    user = await session.get(User, LOCAL_USER_ID)
    if user is None:
        user = User(
            id=LOCAL_USER_ID,
            handle="local",
            display_name="本机学习者",
            is_local=True,
            created_at=utcnow(),
        )
        session.add(user)
        await session.flush()
    return user


async def save_progress(session, course_id: str, update: ProgressUpdate) -> ProgressResponse:
    course, _repo = await get_course(session, course_id)
    user = await ensure_local_user(session)
    row = (
        await session.execute(
            select(UserProgress).where(
                UserProgress.user_id == user.id, UserProgress.course_version_id == course_id
            )
        )
    ).scalar_one_or_none()
    percent = max(0, min(100, update.percent))
    if row is None:
        row = UserProgress(
            id=new_id("event"),
            user_id=user.id,
            course_version_id=course_id,
            current_lesson_key=update.lesson_key,
            current_step_index=update.step_index,
            position_ms=update.position_ms,
            percent=percent,
            created_at=utcnow(),
            updated_at=utcnow(),
        )
        session.add(row)
    else:
        # 单调不减：用户往回拖进度条不应该让"完成度"倒退，
        # 否则完课判据会在拖拽后失效。
        row.current_lesson_key = update.lesson_key
        row.current_step_index = update.step_index
        row.position_ms = update.position_ms
        row.percent = max(row.percent, percent)
        row.updated_at = utcnow()
    if percent >= 100 and row.completed_at is None:
        row.completed_at = utcnow()
    await session.flush()
    return ProgressResponse(progress=row.percent, course_percent=row.percent)


async def answer_quiz(session, course_id: str, item_id: str, choice_id: str) -> QuizAnswerResponse:
    _course, _repo = await get_course(session, course_id, require_ready=True)
    item = await session.get(QuizItem, item_id)
    if item is None or item.course_version_id != course_id:
        raise AppError("OBJECT_MISSING", "题目不存在", status=404)
    user = await ensure_local_user(session)
    correct = item.answer_id == choice_id

    existing = (
        await session.execute(
            select(QuizAttempt).where(QuizAttempt.user_id == user.id, QuizAttempt.quiz_item_id == item_id)
        )
    ).scalar_one_or_none()
    if existing is not None:
        return QuizAnswerResponse(
            correct=existing.correct,
            explanation_md=item.explanation_md,
            evidence=list(item.evidence or []),
            replayed=True,
        )
    session.add(
        QuizAttempt(
            id=new_id("quiz"),
            user_id=user.id,
            quiz_item_id=item_id,
            course_version_id=course_id,
            choice_id=choice_id,
            correct=correct,
            submitted_at=utcnow(),
        )
    )
    try:
        await session.flush()
    except IntegrityError:
        # 两个并发提交：另一个先写进去了，读回首次结果（幂等）
        await session.rollback()
        row = (
            await session.execute(
                select(QuizAttempt).where(QuizAttempt.user_id == user.id, QuizAttempt.quiz_item_id == item_id)
            )
        ).scalar_one_or_none()
        return QuizAnswerResponse(
            correct=bool(row.correct) if row else correct,
            explanation_md=item.explanation_md,
            evidence=list(item.evidence or []),
            replayed=True,
        )
    return QuizAnswerResponse(
        correct=correct,
        explanation_md=item.explanation_md,
        evidence=list(item.evidence or []),
        replayed=False,
    )


async def recap(session, course_id: str) -> RecapResponse:
    course, _repo = await get_course(session, course_id, require_ready=True)
    user = await ensure_local_user(session)
    progress_row = (
        await session.execute(
            select(UserProgress).where(
                UserProgress.user_id == user.id, UserProgress.course_version_id == course_id
            )
        )
    ).scalar_one_or_none()

    lessons = (
        await session.execute(select(Lesson).where(Lesson.course_version_id == course_id).order_by(Lesson.order_index))
    ).scalars().all()
    total_items = int(
        (await session.execute(select(func.count(QuizItem.id)).where(QuizItem.course_version_id == course_id))).scalar()
        or 0
    )
    attempts = (
        await session.execute(select(QuizAttempt).where(QuizAttempt.course_version_id == course_id))
    ).scalars().all()
    correct = sum(1 for a in attempts if a.correct)

    chain = await _call_chain(session, course_id)
    knowledge_points = [
        {"key": lesson.key, "title": lesson.title, "goal": lesson.goal or "", "minutes": lesson.minutes}
        for lesson in lessons
    ]
    ability = _ability_scores(int(progress_row.percent if progress_row else 0), total_items, correct, len(lessons))
    return RecapResponse(
        knowledge_points=knowledge_points,
        call_chain=chain,
        pitfalls=_pitfalls(course),
        quiz_stats={
            "total": total_items,
            "answered": len(attempts),
            "correct": correct,
            "accuracy": round(correct / max(1, len(attempts)), 3),
        },
        next_steps=_next_steps(course),
        ability=ability,
        completed=bool(progress_row and (progress_row.completed_at or progress_row.percent >= 100)),
        percent=int(progress_row.percent if progress_row else 0),
    )


def _ability_scores(percent: int, total_items: int, correct: int, lesson_count: int) -> dict[str, float]:
    accuracy = correct / max(1, total_items)
    coverage = min(1.0, percent / 100)
    depth = min(1.0, lesson_count / 12)
    return {
        "架构理解": round(min(1.0, coverage * 1.05), 3),
        "调用链跟踪": round(min(1.0, coverage * 0.9 + accuracy * 0.3), 3),
        "源码定位": round(min(1.0, depth * 0.7 + coverage * 0.5), 3),
        "概念辨析": round(min(1.0, accuracy * 1.1), 3),
        "完成度": round(coverage, 3),
    }


def _pitfalls(course: CourseVersion) -> list[str]:
    quality = dict(course.quality_report or {})
    out: list[str] = []
    if quality.get("trace_quality") == "weak":
        out.append("本课程的执行链以推演为主：标注为「教学模拟」的变量值是示例，不是真实运行结果。")
    if quality.get("anchor_confidence") == "low":
        out.append("锚点置信度较低（语法分析降级），个别行号可能有偏差，请以文件内容为准。")
    if quality.get("degraded"):
        out.append("课程由静态分析模板生成，讲解深度有限；配置好 AI 服务后可重新生成完整版。")
    if not out:
        out.append("阅读时注意区分「源码事实」与「静态推断」：前者能直接读到，后者是从调用关系推出来的。")
    return out


def _next_steps(course: CourseVersion) -> list[str]:
    repo = str((course.blueprint or {}).get("repo_full_name", "该仓库"))
    return [
        f"挑一个你没被讲到的模块，用行内提问问「这个模块在整个 {repo} 里承担什么职责」",
        "打开一次真实调试会话，用断点验证课程里标注为「静态推断」的那条链路",
        "把课程书籍导出 PDF，作为团队新人 onboarding 材料",
    ]


async def _call_chain(session, course_id: str) -> dict[str, Any]:
    row = (
        await session.execute(
            select(SimulatedTrace)
            .where(SimulatedTrace.course_version_id == course_id)
            .order_by(SimulatedTrace.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if row is None:
        return {}
    return {
        "key": row.key,
        "title": row.title,
        "steps": [
            {"index": s.get("index", i), "title": s.get("title", ""), "certainty": s.get("certainty", "")}
            for i, s in enumerate(row.steps or [])
            if isinstance(s, dict)
        ],
    }


# --------------------------------------------------------------------------- #
# 进度迁移（增量升级用，hardening spec §3.5.3）
# --------------------------------------------------------------------------- #


def carry_forward_percent(*, old_percent: int, kept: int, old_lessons: int, new_lessons: int) -> int:
    """把旧版本的完成度换算到新版本（**确定性公式，不是"等比下调"四个字**）。

    不变式（两条都要能被断言，见 `tests/test_upgrade_pipeline.py::T-UPG-6`）：

    1. **只降不升**：`percent_new <= old_percent`。否则用户什么都没做，完成度
       却从 40% 跳回 90%——这类"凭空长出来的进度"会直接毁掉用户对进度的信任。
    2. **不超过按新课时数重算的上限**：`percent_new <= floor(100 * kept / new_lessons)`。
       否则新版本课时变多时，用户会看到"已学完 8/12"却只点开过 3 个课时。

    公式：
        lesson_ratio = kept / old_lessons          # 学过的内容里有多少还在
        percent_new  = floor(old_percent * lesson_ratio)
        percent_new  = min(percent_new, floor(100 * kept / new_lessons))
        percent_new  = max(0, percent_new)
    """
    if old_lessons <= 0 or new_lessons <= 0:
        return 0
    kept_clamped = max(0, min(kept, old_lessons, new_lessons))
    lesson_ratio = kept_clamped / old_lessons
    percent_new = int(old_percent * lesson_ratio)  # int() 在地板上对正数即 floor
    cap = int(100 * kept_clamped / new_lessons)
    percent_new = min(percent_new, cap)
    return max(0, percent_new)


async def carry_forward(session, old_version, new_version) -> dict[str, Any]:
    """把本地用户的进度从旧版本迁到新版本。

    三种情况，顺序有意义：

    * 新版本**已有**进度行 → 用户可能已经在新版本里学了一会儿，**以新版本为准**，
      只补空字段（`current_lesson_key` 为空才写）。反过来的话，用户刚在新版里
      点开第 5 节，一次后台迁移就把他送回第 2 节。
    * `current_lesson_key` 在新版本里仍存在 → 原样保留它、`current_step_index`
      与 `position_ms`（用户停在哪一步、音频拖到哪一秒），只按公式下调 `percent`。
    * 该 key 被删除 → 沿**旧版本的 order_index 往前找**最近一个仍存在的 key；
      `current_step_index = 0`、`position_ms = 0`（旧的位置在新的课时里没有意义）。
    """
    user = await ensure_local_user(session)
    old_row = (
        await session.execute(
            select(UserProgress).where(
                UserProgress.user_id == user.id, UserProgress.course_version_id == old_version.id
            )
        )
    ).scalar_one_or_none()
    if old_row is None:
        return {"migrated": False, "reason": "no_progress"}

    old_lessons = (
        await session.execute(
            select(Lesson).where(Lesson.course_version_id == old_version.id).order_by(Lesson.order_index)
        )
    ).scalars().all()
    new_lessons = (
        await session.execute(
            select(Lesson).where(Lesson.course_version_id == new_version.id).order_by(Lesson.order_index)
        )
    ).scalars().all()
    new_keys = {lesson.key for lesson in new_lessons}
    kept = sum(1 for lesson in old_lessons if lesson.key in new_keys)

    existing = (
        await session.execute(
            select(UserProgress).where(
                UserProgress.user_id == user.id, UserProgress.course_version_id == new_version.id
            )
        )
    ).scalar_one_or_none()

    target_key = old_row.current_lesson_key if old_row.current_lesson_key in new_keys else None
    step_index = old_row.current_step_index if target_key else 0
    position_ms = old_row.position_ms if target_key else 0
    if target_key is None:
        # 往前找最近一个仍然存在的课时（按旧版本的顺序，不是字典序）。
        for lesson in sorted(old_lessons, key=lambda row: row.order_index, reverse=True):
            if lesson.key in new_keys:
                target_key = lesson.key
                break

    percent = carry_forward_percent(
        old_percent=old_row.percent,
        kept=kept,
        old_lessons=len(old_lessons),
        new_lessons=len(new_lessons),
    )
    completed_at = old_row.completed_at if percent >= 100 else None

    if existing is not None:
        # 新版本已有的记录优先：只补空字段，不覆盖用户在新版本里的实际行为。
        if not existing.current_lesson_key and target_key:
            existing.current_lesson_key = target_key
            existing.current_step_index = step_index
            existing.position_ms = position_ms
        existing.percent = max(existing.percent, percent)
        if existing.completed_at is None:
            existing.completed_at = completed_at
        existing.updated_at = utcnow()
        await session.flush()
        return {"migrated": True, "mode": "merged", "percent": existing.percent, "kept": kept}

    session.add(
        UserProgress(
            id=new_id("event"),
            user_id=user.id,
            course_version_id=new_version.id,
            current_lesson_key=target_key,
            current_step_index=step_index,
            position_ms=position_ms,
            percent=percent,
            completed_at=completed_at,
            created_at=utcnow(),
            updated_at=utcnow(),
        )
    )
    await session.flush()
    log.info(
        "progress_carried_forward",
        from_course=old_version.id,
        to_course=new_version.id,
        percent=percent,
        kept=kept,
        old_lessons=len(old_lessons),
        new_lessons=len(new_lessons),
    )
    return {"migrated": True, "mode": "created", "percent": percent, "kept": kept}

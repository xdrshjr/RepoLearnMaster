"""增量升级 Job（hardening spec §3.5.2）。

流程与整门生成的区别只在"写哪些课时"：

```
N1 normalize → N2 resolve（已知新 sha）→ N3 fetch → N4 analyze
   ↓
copy_lessons(旧 → 新, keep=不受影响集合)
   ↓
N6 write_lessons(affected) → N7 simulate_trace(affected) → N8 synthesize_audio(affected)
   ↓
publish_partial（合并后的质量门禁 + 旧镜像校验复制来的锚点）
   ↓
progress_service.carry_forward(旧, 新)
```

**为什么复用 `make_nodes` 而不是另写一条流水线**：N4 的知识图、N6 的模板/LLM
双分支、N7 的模拟守卫、N8 的 TTS 拼接都有各自的降级语义。抄一份"升级专用的
分析"等于让两条链路慢慢分叉，而分叉的表现是"新生成的课有锚点、升级生成的课
没有"——这种差异没有任何页面会报错。
"""

from __future__ import annotations

import asyncio
from typing import Any

from repolearn.core.clock import utcnow
from repolearn.core.config import settings
from repolearn.core.db import session_scope
from repolearn.core.errors import AppError
from repolearn.core.logging import get_logger
from repolearn.jobs.handlers import JobOutcome
from repolearn.providers.agent_runtime import refresh_state
from repolearn.providers.budget_guard import JobBudget
from repolearn.providers.registry import build_resolver
from repolearn.services import progress_service
from repolearn.services.lesson_service import copy_lessons
from repolearn.services.setup_service import active_profile, profile_llm_configs
from repolearn.workflow import NODE_PROGRESS, NodeContext
from repolearn.workflow.nodes import make_nodes
from repolearn.workflow.publish import publish_partial
from repolearn.workflow.state import new_state

log = get_logger("upgrade_jobs")


async def _emit_noop(_node: str, _progress: int) -> None:
    return None


async def run_upgrade_job(*, job_id: str, course_id: str, payload: dict, emit: Any) -> JobOutcome:
    """只重讲受影响课时，其余从旧版本复制过来。"""
    from repolearn.jobs.handlers import _Ctx  # 私有但同包：复用它的预算/审计/TTS 装配

    from_sha = str(payload.get("from_course_id") or "")
    new_sha = str(payload.get("new_sha") or "")
    plan = payload.get("plan") or {}
    affected = [str(k) for k in (plan.get("affected_keys") or [])]
    if not affected:
        # 没有受影响课时却跑了 Job：说明入队判断与计划不一致。把新版本置为
        # `none` 而不是悄悄发布一份与旧版逐字节相同的"新版本"。
        async with session_scope() as session:
            from repolearn.models import CourseVersion

            version = await session.get(CourseVersion, course_id)
            if version is not None:
                version.status = "partial"
                version.warnings = list(version.warnings or []) + [
                    {
                        "code": "UPGRADE_PARTIAL",
                        "message": "没有需要重讲的课时（计划为空），未发布新内容",
                        "severity": "warning",
                        "node": "upgrade",
                    }
                ]
                version.updated_at = utcnow()
        return JobOutcome(status="partial", message="没有需要重讲的课时")

    runtime = await refresh_state(force=True)
    await emit("job.phase", {"node": "normalize_repo", "phase": "start", "progress": 1})

    budget = JobBudget(
        max_tokens=settings.job_max_tokens,
        max_usd=settings.job_max_usd,
        deadline_ms=settings.job_deadline_ms,
    )
    async with session_scope() as session:
        profile = await active_profile(session)
        if profile is None and runtime.mode != "template":
            raise AppError("SETUP_REQUIRED")
        configs, roles = ({}, {}) if profile is None else profile_llm_configs(profile)
        resolver = build_resolver(roles, configs)

    async def emit_node(node: str, progress: int) -> None:
        await emit("node.completed", {"node": node, "progress": progress or NODE_PROGRESS.get(node, 0)})

    ctx = _Ctx(
        job_id=job_id,
        course_id=course_id,
        resolver=resolver,
        budget=budget,
        tts=None,
        runtime_mode=runtime.mode,
        emit=emit_node,
    )
    node_ctx = NodeContext(
        run=ctx.run,
        read_file=ctx.read_file,
        line_count=ctx.line_count,
        save_artifact=ctx.save_artifact,
        emit_progress=ctx.emit_progress,
        job_id=job_id,
    )
    node_ctx.load_artifact = ctx.load_artifact
    node_ctx.publish = ctx.publish
    node_ctx.synthesize = ctx.synthesize
    node_ctx.runtime_mode = runtime.mode

    nodes = make_nodes(node_ctx)
    state = new_state(job_id, course_id)
    state["repo"] = {"repo_url": payload.get("repo_url", "")}
    state["commit"] = {"requested_ref": new_sha or payload.get("ref")}
    state["runtime"] = runtime.mode

    # N1–N4：只跑到"分析完成"。N5 的大纲**不重新规划**——大纲是旧版本已经发布的
    # 那份，重排它会让"只重讲 2 个课时"变成"整门课换了顺序"。
    for name in ("normalize_repo", "resolve_commit", "fetch_repo", "analyze_repo"):
        update = await nodes[name](state)
        if isinstance(update, dict):
            state.update(update)
        sha = str((state.get("commit") or {}).get("sha", ""))
        if sha:
            ctx.sha = sha
    resolved_sha = str((state.get("commit") or {}).get("sha", "")) or new_sha

    async with session_scope() as session:
        from repolearn.models import CourseVersion

        new_version = await session.get(CourseVersion, course_id)
        old_version = await session.get(CourseVersion, from_sha)
        if new_version is None or old_version is None:
            raise AppError("COURSE_NOT_READY", "升级的源/目标版本不存在")

        # 复制不受影响的课时（这一步在"重讲"之前：重讲失败的课时不会把旧内容也弄丢）。
        from sqlalchemy import select as sa_select

        from repolearn.models import Lesson

        old_lessons = {
            row.key
            for row in (
                await session.execute(sa_select(Lesson).where(Lesson.course_version_id == old_version.id))
            ).scalars().all()
        }
        keep = sorted(old_lessons - set(affected))
        await copy_lessons(session, old_version, new_version, keep_keys=keep)
        await session.commit()

    # N6–N8：只对受影响课时跑。`current_lesson` 是 N6 的单课时入口。
    lesson_plan_index: dict[str, dict] = {}
    for section in state.get("curriculum", {}).get("sections") or []:
        for item in section.get("lessons") or []:
            if isinstance(item, dict) and item.get("key"):
                lesson_plan_index[str(item["key"])] = item

    lessons_update: dict[str, dict] = {}
    quizzes_update: dict[str, dict] = {}
    warnings: list[dict] = []
    failed: list[str] = []
    for key in affected:
        plan_item = lesson_plan_index.get(key) or {"key": key, "title": key}
        try:
            update = await nodes["write_lessons"]({**state, "current_lesson": plan_item})
            lessons_update.update(update.get("lessons") or {})
            quizzes_update.update(update.get("quizzes") or {})
            warnings.extend(update.get("warnings") or [])
        except Exception as exc:  # noqa: BLE001 - 单课时失败不该整包失败
            failed.append(key)
            warnings.append(
                {
                    "code": "LESSON_FAILED",
                    "message": f"课时 {key} 重讲失败：{exc}",
                    "severity": "warning",
                    "node": "upgrade",
                }
            )
            log.warning("upgrade_lesson_failed", key=key, error=str(exc))

    state["lessons"] = lessons_update
    state["quizzes"] = quizzes_update
    state["failed_lessons"] = failed
    state["warnings"] = list(state.get("warnings") or []) + warnings

    for name in ("simulate_trace", "synthesize_audio"):
        try:
            update = await nodes[name](state)
            if isinstance(update, dict):
                state.update(update)
        except Exception as exc:  # noqa: BLE001 - 模拟/配音失败降级，不阻断发布
            warnings.append(
                {
                    "code": "UPGRADE_DEGRADED",
                    "message": f"{name} 失败，已降级：{exc}",
                    "severity": "warning",
                    "node": name,
                }
            )

    from repolearn.ingest.mirror import line_count as mirror_line_count
    from repolearn.ingest.mirror import list_files

    file_lines: dict[str, int] = {}
    for item in list_files(resolved_sha):
        try:
            file_lines[str(item["path"])] = mirror_line_count(resolved_sha, str(item["path"]))
        except Exception:  # noqa: BLE001
            continue

    async with session_scope() as session:
        from repolearn.models import CourseVersion

        new_version = await session.get(CourseVersion, course_id)
        old_version = await session.get(CourseVersion, from_sha)
        if new_version is None or old_version is None:
            raise AppError("COURSE_NOT_READY", "升级的源/目标版本不存在")
        result = await publish_partial(
            session,
            course_id=course_id,
            curriculum=state.get("curriculum") or {},
            lessons=lessons_update,
            traces=state.get("traces") or {},
            narration=state.get("narration") or {},
            commit_sha=resolved_sha,
            file_lines=file_lines,
            warnings=warnings,
            failed_lessons=failed,
            runtime=runtime.mode,
            load_artifact=ctx.load_artifact,
            affected_keys=[k for k in affected if k in lessons_update],
            old_commit_sha=old_version.commit_sha,
            min_lessons=settings.min_lessons_to_publish,
            min_coverage=settings.min_anchor_coverage,
            min_sections=settings.min_sections_to_publish,
        )
        await progress_service.carry_forward(session, old_version, new_version)
        await session.commit()

    status = str(result.get("status", "partial"))
    message = f"升级完成：重讲 {result.get('regenerated', 0)} 个课时，沿用 {result.get('copied', 0)} 个"
    if failed:
        message += f"（{len(failed)} 个课时失败，可继续生成）"
    return JobOutcome(
        status="ready" if status == "ready" else "partial",
        message=message,
        details={"quality_report": result.get("quality_report"), "commit_sha": resolved_sha},
    )


async def run_upgrade_plan_job(*, job_id: str, course_id: str | None, payload: dict, emit: Any) -> JobOutcome:
    """超时转后台的"算计划"任务。

    为什么它是一个独立 kind 而不是 `upgrade` 的一个参数：两者产物不同——计划任务
    不写课程内容，只写 `var/objects/upgrade-plan/*.json` 缓存；把它混进 `upgrade`
    会让"202 到底会不会生成新版本"这一步变成靠参数猜。
    """
    from repolearn.services import upgrade_service

    if not course_id:
        raise AppError("COURSE_NOT_READY", "计划任务缺少课程 id")
    async with session_scope() as session:
        body, code = await upgrade_service.start_upgrade(
            session, str(payload.get("course_id") or course_id), ref=payload.get("ref"), dry_run=True
        )
        await session.commit()
    await emit("job.completed", {"mode": body.get("mode"), "code": code})
    return JobOutcome(status="ready", message=f"检查更新完成：{body.get('mode')}", details={"plan": body})


__all__ = ["run_upgrade_job", "run_upgrade_plan_job", "asyncio", "_emit_noop"]

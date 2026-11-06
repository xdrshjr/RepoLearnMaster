"""增量升级服务（hardening spec §3.5.2）。

**`/upgrade` 与 `/rebuild` 的区别必须刻在代码里，不只是文档里**：

| | `/rebuild` | `/upgrade` |
|---|---|---|
| commit | 同一个 sha | **新的** sha |
| 旧数据 | 同一版本内被覆盖 | 旧版本**原样保留**，生成新版本 |
| 进度 | 不变 | 迁移到新版本 |

因此这里**绝不**把旧版本置 `generating`：那样用户正在学的课程会突然变成
"生成中"（既读不到、也不知道要等多久）。新版本另起一行，旧版本继续可读。

`dry_run` 的三道闸（P1-10）：这个接口看起来"只是检查一下"，实际上走到第 4 步
已经**下载并解包了整包 tarball**——对一个 50 MB 的仓库，用户点一下"检查更新"
就是一次 50 MB 下载 + 一次全量解包，而"不写库"意味着再点一次要再下一遍。
所以：① 体积受 `REPOLEARN_MAX_REPO_MB` 约束（复用 github 层已有的双检）；
② `UpgradePlan` 按 `(old_sha8, new_sha8, policy_version)` 落盘缓存，连点两次不
应该有第二次网络 IO；③ 同步路径 20s 预算，超时改为 `202 {job_id}`。
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path
from typing import Any

from sqlalchemy import select

from repolearn.analysis.diff import (
    UpgradePlan,
    diff_snapshots,
    lesson_files_from_rows,
    plan_upgrade,
)
from repolearn.core.clock import utcnow
from repolearn.core.config import settings
from repolearn.core.errors import AppError
from repolearn.core.ids import new_id
from repolearn.core.logging import get_logger
from repolearn.ingest import download_tarball, extract_tarball, mirror_path
from repolearn.ingest.github import fetch_repo_meta, parse_repo_url, resolve_commit
from repolearn.ingest.mirror import exists as mirror_exists
from repolearn.jobs import queue
from repolearn.models import CourseVersion, Lesson, Repository, SourceAnchor, Step
from repolearn.services.course_service import (
    DEFAULT_POLICY_VERSION,
    READABLE_STATUSES,
    cache_key_for,
    create_course,
    get_course,
    to_list_item,
)

log = get_logger("upgrade_service")

#: 同步路径（dry_run 与建版本）的时间预算。超过就转成后台 Job：
#: 一个"点了按钮没反应"的界面上，20 秒已经是用户耐心的上限；不设上限则大仓库上
#: 会出现"转圈直到浏览器超时"，而用户完全不知道发生了什么。
SYNC_BUDGET_S = 20.0

#: 计划缓存目录（相对 object_root）。命中时连 tarball 都不用下。
PLAN_CACHE_DIR = "upgrade-plan"


def _plan_cache_path(old_sha: str, new_sha: str, policy: str) -> Path:
    # 用 policy 的哈希而不是原文做文件名：policy 可能是任意版本串，直接拼进路径
    # 会引入路径分隔符与大小写敏感问题（Windows 上尤其）。
    policy_tag = hashlib.sha256(policy.encode("utf-8")).hexdigest()[:8]
    return settings.object_path / PLAN_CACHE_DIR / f"{old_sha[:8]}-{new_sha[:8]}-{policy_tag}.json"


def _read_cached_plan(path: Path) -> dict | None:
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 - 坏缓存等价于没有缓存
        return None


def _write_cached_plan(path: Path, payload: dict) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    except OSError as exc:  # noqa: BLE001 - 缓存失败不影响正确性
        log.warning("upgrade_plan_cache_write_failed", error=str(exc))


async def _lesson_refs(session, course_id: str):
    lessons = (
        await session.execute(
            select(Lesson).where(Lesson.course_version_id == course_id).order_by(Lesson.order_index)
        )
    ).scalars().all()
    steps = (
        await session.execute(select(Step).where(Step.lesson_id.in_([lesson.id for lesson in lessons])))
    ).scalars().all() if lessons else []
    anchors = (
        await session.execute(select(SourceAnchor).where(SourceAnchor.course_version_id == course_id))
    ).scalars().all()
    return lessons, lesson_files_from_rows(lessons, steps, anchors)


async def _prepare(session, course: CourseVersion, repo: Repository, *, ref: str | None):
    """解析新 sha → 取镜像 → 差分 → 出计划。**这是 `dry_run` 与真正升级共用的一段。**

    返回 `(new_sha, plan, cached)`
    """
    meta = await fetch_repo_meta(parse_repo_url(repo.full_name))
    commit = await resolve_commit(parse_repo_url(repo.full_name), meta.default_branch, ref)
    new_sha = commit.sha
    policy = course.policy_version or DEFAULT_POLICY_VERSION

    cache_path = _plan_cache_path(course.commit_sha, new_sha, policy)
    cached = _read_cached_plan(cache_path)
    lessons, refs = await _lesson_refs(session, course.id)
    if cached is not None:
        plan = UpgradePlan(
            mode=cached.get("mode", "none"),
            affected_keys=tuple(cached.get("affected_keys") or ()),
            reasons=tuple(cached.get("reasons") or ()),
            stats=dict(cached.get("stats") or {}),
        )
        return new_sha, plan, True

    old_root = mirror_path(course.commit_sha)
    old_mirror_ok = mirror_exists(course.commit_sha)
    new_root = mirror_path(new_sha)
    if not mirror_exists(new_sha):
        # 端点说多大不算数：`download_tarball` 会查 Content-Length 与流式累计，
        # `extract_tarball` 还会查解包后的累计字节（压缩比可以任意高）。
        data = await download_tarball(parse_repo_url(repo.full_name), new_sha)
        extract_tarball(data, new_root)

    deltas = diff_snapshots(old_root, new_root) if old_mirror_ok else []
    total_files = await _old_total_files(session, course, old_mirror_ok=old_mirror_ok)
    plan = plan_upgrade(refs, deltas, total_files=total_files, old_mirror_ok=old_mirror_ok)
    _write_cached_plan(cache_path, plan.as_dict())
    return new_sha, plan, False


async def _old_total_files(session, course: CourseVersion, *, old_mirror_ok: bool) -> int:
    """分母口径（spec P1-9）：**旧镜像**里被收录的可分析文件数。

    为什么不能拿 `resolve_commit(新 sha)` 的 `file_count`：那是 GitHub commits API
    的 `files` 数组长度——含 .md/图片/二进制、上限 300、GHE 常常不返回。拿它当
    分母，`plan_upgrade` 第 4 条（"新增文件占比"）的阈值就变成了"看端点心情"，
    同一份 delta 在两种端点上判 partial / 判 full。

    顺序：`Commit.file_count`（与本产品 analysis 收录口径同源）→ 旧镜像清单条数
    → 0（交给 `plan_upgrade` 用绝对下限 `NEW_FILES_MIN`，并把 `total_files=0`
    写进 `stats`，让"口径缺失"在响应里可见，而不是悄悄退化成 1）。
    """
    from repolearn.models import Commit

    row = (
        await session.execute(select(Commit.file_count).where(Commit.sha == course.commit_sha).limit(1))
    ).scalar()
    if row and int(row) > 0:
        return int(row)
    if old_mirror_ok:
        from repolearn.ingest.mirror import list_files

        try:
            return len(list_files(course.commit_sha))
        except Exception as exc:  # noqa: BLE001 - 镜像读不出来不该阻断升级计划
            log.warning("old_total_files_failed", sha=course.commit_sha[:8], error=str(exc)[:200])
    log.warning("old_total_files_missing", sha=course.commit_sha[:8])
    return 0


def _plan_response(
    plan: UpgradePlan,
    *,
    course_id: str,
    from_sha: str,
    to_sha: str,
    lessons: list[Lesson],
    mode: str | None = None,
    reasons: list[str] | None = None,
) -> dict[str, Any]:
    titles = {lesson.key: lesson.title for lesson in lessons}
    return {
        "mode": mode or plan.mode,
        "reasons": list(reasons if reasons is not None else plan.reasons),
        "stats": dict(plan.stats or {}),
        "affected_lessons": [
            {"key": key, "title": titles.get(key, "")} for key in plan.affected_keys
        ],
        "course_id": course_id,
        "from_sha": from_sha[:8],
        "to_sha": to_sha[:8],
    }


async def start_upgrade(
    session,
    course_id: str,
    *,
    ref: str | None = None,
    dry_run: bool = False,
) -> tuple[dict[str, Any], int]:
    """返回 `(响应体, HTTP 状态码)`。`202` 表示真的开始生成。"""
    course, repo = await get_course(session, course_id)
    if course.status not in READABLE_STATUSES:
        raise AppError("COURSE_NOT_READY", details={"status": course.status})
    policy = course.policy_version or DEFAULT_POLICY_VERSION

    try:
        new_sha, plan, cached = await asyncio.wait_for(
            _prepare(session, course, repo, ref=ref), timeout=SYNC_BUDGET_S
        )
    except TimeoutError:
        # 超时不是失败：把"算计划"这件事交给后台，UI 显示"正在检查更新…"。
        # 必须是 **202 + job_id**（spec P1-10 ③）。不能像 v1 那样借
        # `PROVIDER_UNAVAILABLE`（503）报出去：那个码的语义是"模型服务不可用"，
        # 与"这次算得慢"毫无关系，而且会给前端一个毫无用处的"重试"按钮。
        course_id_for_response = course.id
        from_sha8 = course.commit_sha[:8]
        job = await queue.enqueue(
            session,
            kind="upgrade-plan",
            payload={"course_id": course_id_for_response, "ref": ref, "dry_run": True},
            course_version_id=course_id_for_response,
            cache_key=f"upgrade-plan:{course.cache_key}:{ref or 'head'}",
        )
        # `queue.enqueue` 只 `flush` 不 `commit`；这里必须自己提交——否则请求结束
        # 时 session 回滚，202 里给出的 job_id 指向一个**不存在的任务**，
        # "已转后台继续"就变成了一句谎话。
        await session.commit()
        return (
            {
                "job_id": job.id,
                "course_id": course_id_for_response,
                "mode": "planning",
                "from_sha": from_sha8,
            },
            202,
        )

    lessons, _refs = await _lesson_refs(session, course.id)

    if new_sha == course.commit_sha:
        return (
            _plan_response(
                plan,
                course_id=course.id,
                from_sha=course.commit_sha,
                to_sha=new_sha,
                lessons=lessons,
                mode="none",
                reasons=["already_latest"],
            ),
            200,
        )

    key = cache_key_for(repo.full_name, new_sha, policy, course.language)
    existing = (
        await session.execute(select(CourseVersion).where(CourseVersion.cache_key == key))
    ).scalar_one_or_none()
    if existing is not None and existing.status in READABLE_STATUSES and existing.deleted_at is None:
        return (
            _plan_response(
                plan,
                course_id=existing.id,
                from_sha=course.commit_sha,
                to_sha=new_sha,
                lessons=lessons,
                mode="reused",
                reasons=["version_exists"],
            ),
            200,
        )

    if dry_run:
        # 不写库：dry_run 的产物是"给你看受影响课时清单"，不是一个新版本。
        return (
            _plan_response(
                plan,
                course_id=course.id,
                from_sha=course.commit_sha,
                to_sha=new_sha,
                lessons=lessons,
            ),
            200,
        )

    if plan.mode == "none":
        return (
            _plan_response(
                plan,
                course_id=course.id,
                from_sha=course.commit_sha,
                to_sha=new_sha,
                lessons=lessons,
            ),
            200,
        )

    if plan.mode == "full":
        # 全量：委托既有 `create_course` 语义（它已经处理了幂等、锁、commit 行、
        # 仓库行与入队）。唯一需要补的是 `upgraded_from_id`——"这门课是哪一门升
        # 上来的"不能用 cache_key 推出来。
        response, code = await create_course(
            session,
            repo_url=repo.full_name,
            ref=new_sha,
            language=course.language,
            policy_version=policy,
            idempotency_key=None,
            request_hash="",
        )
        upgraded = await session.get(CourseVersion, response.course_id)
        if upgraded is not None and upgraded.id != course.id:
            upgraded.upgraded_from_id = course.id
            upgraded.blueprint = {
                **(upgraded.blueprint or {}),
                "upgrade": {"plan": "full", "from_sha": course.commit_sha, "to_sha": new_sha},
            }
        return (
            {
                "job_id": response.job_id,
                "course_id": response.course_id,
                "mode": "full",
                "reasons": list(plan.reasons),
                "stats": dict(plan.stats or {}),
                "affected_lessons": [
                    {"key": key_, "title": {lesson.key: lesson.title for lesson in lessons}.get(key_, "")}
                    for key_ in plan.affected_keys
                ],
                "from_sha": course.commit_sha[:8],
                "to_sha": new_sha[:8],
            },
            202,
        )

    # partial：建占位版本 + 入队。旧版本**不动**（不置 generating）——这是与
    # `/rebuild` 的关键区别，也是"用户正在学的课不会突然消失"的保证。
    holder = await queue.active_lock_job(session, key)
    if holder is not None:
        raise AppError("JOB_CONFLICT", details={"job_id": holder, "course_cache_key": key})

    new_version = CourseVersion(
        id=new_id("course_version"),
        repository_id=repo.id,
        commit_sha=new_sha,
        cache_key=key,
        policy_version=policy,
        language=course.language,
        title=course.title,
        subtitle=course.subtitle,
        summary_md=course.summary_md,
        status="generating",
        # 大纲先沿用旧版：受影响课时重讲之后 N9.5（publish_partial）会用
        # 合并后的集合重新写一次。空大纲会让准备页显示"0 课时"，比旧大纲更新
        # 不及时得多。
        sections=list(course.sections or []),
        quality_report={},
        warnings=[],
        blueprint={
            "repo_full_name": repo.full_name,
            "upgrade": {
                "plan": "partial",
                "affected_keys": list(plan.affected_keys),
                "from_sha": course.commit_sha,
                "to_sha": new_sha,
                "started_at": utcnow().isoformat(),
            },
        },
        cover_palette=course.cover_palette,
        lesson_count=course.lesson_count,
        total_minutes=course.total_minutes,
        visibility=course.visibility,
        upgraded_from_id=course.id,
        created_at=utcnow(),
        updated_at=utcnow(),
    )
    session.add(new_version)
    await session.flush()

    job = await queue.enqueue(
        session,
        kind="upgrade",
        payload={
            "from_course_id": course.id,
            "to_course_id": new_version.id,
            "repo_url": repo.full_name,
            "ref": new_sha,
            "new_sha": new_sha,
            "plan": plan.as_dict(),
            "language": course.language,
        },
        course_version_id=new_version.id,
        cache_key=key,
        priority=60,
    )
    if not await queue.acquire_lock(session, key, job.id):
        raise AppError("JOB_CONFLICT", details={"course_cache_key": key})

    log.info(
        "upgrade_started",
        from_course=course.id,
        to_course=new_version.id,
        job_id=job.id,
        affected=len(plan.affected_keys),
        cached=cached,
    )
    return (
        {
            "job_id": job.id,
            "course_id": new_version.id,
            "mode": "partial",
            "reasons": list(plan.reasons),
            "stats": dict(plan.stats or {}),
            "affected_lessons": [
                {"key": key_, "title": {lesson.key: lesson.title for lesson in lessons}.get(key_, "")}
                for key_ in plan.affected_keys
            ],
            "from_sha": course.commit_sha[:8],
            "to_sha": new_sha[:8],
        },
        202,
    )


__all__ = ["PLAN_CACHE_DIR", "SYNC_BUDGET_S", "start_upgrade", "to_list_item"]

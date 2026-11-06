"""课程服务（spec §5.2 第二组）。

列表查询的两条纪律：
1. **纯函数投影**：`to_list_item(course, repo)` 不查库、不 N+1。v1 的列表实现在
   循环里为每行查一次 repository，10 条课程就是 11 次查询（F-REV-2 的教训）。
2. **`deleted_at IS NULL` 必须出现在每个读取路径上**（§6.1）。这里用
   `not_deleted()` 统一助手，避免"某个接口忘了过滤"——那种 bug 只在有软删数据时
   才出现，测试很难覆盖到。
"""

from __future__ import annotations

import hashlib
import sqlite3
from typing import Any

from sqlalchemy import Select, func, or_, select

from repolearn.core.clock import utcnow
from repolearn.core.config import settings
from repolearn.core.errors import AppError
from repolearn.core.ids import new_id
from repolearn.core.logging import get_logger
from repolearn.core.pagination import clamp_limit, decode_cursor, encode_cursor
from repolearn.ingest.github import fetch_repo_meta, parse_repo_url, resolve_commit
from repolearn.ingest.mirror import list_files, read_file
from repolearn.jobs import queue
from repolearn.models import Commit, CourseVersion, Lesson, Repository, SourceAnchor
from repolearn.schemas.course import (
    CommitBrief,
    CourseCreatedResponse,
    CourseDetail,
    CourseListItem,
    CourseListResponse,
    QualityBrief,
    RepoBrief,
    SectionBrief,
)

log = get_logger("course_service")

DEFAULT_POLICY_VERSION = "1"
READABLE_STATUSES = ("ready", "partial")


def not_deleted() -> Any:
    return CourseVersion.deleted_at.is_(None)


def cache_key_for(full_name: str, commit_sha: str, policy_version: str, language: str) -> str:
    """内容级缓存键（§3.10）。四个成分缺一不可：

    少了 `policy_version`，改了生成策略后旧课程永远不会被重建；
    少了 `language`，中英文课程会互相覆盖。
    """
    raw = f"{full_name}|{commit_sha}|{policy_version}|{language}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def to_list_item(course: CourseVersion, repo: Repository, *, highlights: Any = None) -> CourseListItem:
    quality = dict(course.quality_report or {})
    return CourseListItem(
        id=course.id,
        repo=RepoBrief(
            full_name=repo.full_name,
            owner=repo.owner,
            name=repo.name,
            description=repo.description,
            stars=repo.stars,
            license=repo.license_spdx,
            primary_language=repo.primary_language,
            default_branch=repo.default_branch,
            html_url=repo.html_url,
        ),
        title=course.title or repo.full_name,
        summary=(course.summary_md or "")[:280],
        lesson_count=course.lesson_count,
        minutes=course.total_minutes,
        status=course.status,
        quality=QualityBrief(
            anchor_coverage=float(quality.get("anchor_coverage", 0) or 0),
            lesson_completeness=float(quality.get("lesson_completeness", 0) or 0),
            degraded=bool(quality.get("degraded", False)),
            anchor_confidence=str(quality.get("anchor_confidence", "high")),
        ),
        updated_at=(course.updated_at or course.created_at).isoformat() if (course.updated_at or course.created_at) else None,
        cover_palette=course.cover_palette,
        highlights=highlights,
    )


async def list_courses(
    session,
    *,
    status: str | None = None,
    owner: str | None = None,
    q: str | None = None,
    limit: int | None = None,
    cursor: str | None = None,
    mode: str = "auto",
    offset: int = 0,
) -> CourseListResponse:
    """课程列表（scan / fts 双通道，hardening spec §3.4.3 / §3.4.4）。

    两条纪律：
    1. **生效模式必须回显**。`mode` 返回的是"这次真的用了哪条路"，不是配置值。
       旧实现答应 `REPOLEARN_SEARCH=fts` 却只有 `LIKE` 分支，而 Doctor 报 ok——
       一个骗过所有人的开关。回显是让这种谎言不可能再出现的唯一办法。
    2. **fts 与 scan 的分页语义不同且不可混用**：fts 用 `offset`（上限 200，
       `bm25` 是浮点分数，做 keyset 会在索引变化后产生幽灵行），scan 用 keyset
       游标。混着传由路由层直接 `VALIDATION_FAILED`，不在这里猜。
    """
    from repolearn.services.search import (
        MAX_OFFSET,
        SearchPlan,
        fts_capability,
        highlight_segments,
        plan_search,
    )
    from repolearn.services.search_ddl import FTSTable

    size = clamp_limit(limit)
    configured = settings.search if mode == "auto" else mode
    plan = plan_search(q, configured=configured, sqlite_version=sqlite3.sqlite_version)

    # 配置说 fts、但库里根本没有索引表（老 SQLite 上迁移跳过了建表）时，
    # 计划里只体现了版本判据；这里补一次**实际状态**探测，避免 `no such table`。
    if plan.mode == "fts":
        cap = await fts_capability(session)
        if not cap.available:
            plan = plan_search(q, configured="scan", sqlite_version=sqlite3.sqlite_version)
            plan = SearchPlan(
                mode="scan",
                tokens=plan.tokens,
                like_pattern=plan.like_pattern,
                fallback_reason=cap.reason,
            )

    # `offset` 与生效模式必须匹配（spec §5.1.1）。判在这里而不是路由层，是因为
    # "生效模式"要等 `plan_search` 按运行时能力与查询长度算完才知道：
    # 按参数值猜会让 `mode=auto` 在装得上 fts 的机器上可用、装不上的机器上 422，
    # 而前端 `useCourseSearch` 发的正是 `mode=auto`。
    if offset and plan.mode != "fts":
        raise AppError(
            "VALIDATION_FAILED",
            "offset 只用于 fts 模式",
            hint="本次请求实际走 scan（查询过短或本机没有 trigram 索引）；fts 用 offset（0–200）分页，scan 请用 cursor",
            details={"mode": plan.mode, "offset": offset, "fallback_reason": plan.fallback_reason},
        )

    if plan.mode == "none":
        stmt: Select = (
            select(CourseVersion, Repository)
            .join(Repository, Repository.id == CourseVersion.repository_id)
            .where(not_deleted())
        )
        if status:
            stmt = stmt.where(CourseVersion.status == status)
        if owner:
            stmt = stmt.where(Repository.owner == owner)
        decoded = decode_cursor(cursor)
        if decoded is not None:
            ts, row_id = decoded
            stmt = stmt.where(
                or_(
                    CourseVersion.created_at < ts,
                    (CourseVersion.created_at == ts) & (CourseVersion.id < row_id),
                )
            )
        stmt = stmt.order_by(CourseVersion.created_at.desc(), CourseVersion.id.desc()).limit(size + 1)
        rows = (await session.execute(stmt)).all()
        has_more = len(rows) > size
        rows = rows[:size]
        items = [to_list_item(course, repo) for course, repo in rows]
        next_cursor = encode_cursor(rows[-1][0].created_at, rows[-1][0].id) if has_more and rows else None
        return CourseListResponse(items=items, next_cursor=next_cursor, mode="none")

    if plan.mode == "fts":
        return await _list_courses_fts(
            session,
            plan=plan,
            status=status,
            owner=owner,
            size=size,
            offset=min(max(offset, 0), MAX_OFFSET),
            highlight_segments=highlight_segments,
            table=FTSTable,
        )

    # scan：既有 LIKE 分支（保持 v1 语义不变，including 排序与游标）
    stmt = (
        select(CourseVersion, Repository)
        .join(Repository, Repository.id == CourseVersion.repository_id)
        .where(not_deleted())
    )
    if status:
        stmt = stmt.where(CourseVersion.status == status)
    if owner:
        stmt = stmt.where(Repository.owner == owner)
    if plan.like_pattern:
        # 搜索不在 EXPLAIN 门禁内（§8.2 P1-9）：前缀通配符下任何 B 树索引都不生效。
        # 因此这里显式限流 limit ≤ 50，并在文档里写明"scan 模式"。
        # `summary_md` 只匹配**前 512 字**，与 FTS 索引的可搜边界保持一致
        # （`search_ddl.SUMMARY_INDEX_CHARS`）。不截断的话，关键词只出现在 512 字
        # 之后的课程会"scan 能搜到、fts 搜不到且 fallback_reason 为空"——正是本轮
        # 要消灭的"库里有、用户搜不到"，也是 T-E2E-R4 的 parity 断言在真实数据上
        # 必然踩到的一处不一致。
        from repolearn.services.search_ddl import SUMMARY_INDEX_CHARS

        like = plan.like_pattern
        stmt = stmt.where(
            or_(
                func.lower(CourseVersion.title).like(like),
                func.lower(func.substr(CourseVersion.summary_md, 1, SUMMARY_INDEX_CHARS)).like(like),
                func.lower(Repository.full_name).like(like),
            )
        )
    decoded = decode_cursor(cursor)
    if decoded is not None:
        ts, row_id = decoded
        stmt = stmt.where(
            or_(
                CourseVersion.created_at < ts,
                (CourseVersion.created_at == ts) & (CourseVersion.id < row_id),
            )
        )
    stmt = stmt.order_by(CourseVersion.created_at.desc(), CourseVersion.id.desc()).limit(size + 1)
    rows = (await session.execute(stmt)).all()
    has_more = len(rows) > size
    rows = rows[:size]
    items = [
        to_list_item(
            course,
            repo,
            highlights=_highlights(plan.tokens, course, repo, highlight_segments),
        )
        for course, repo in rows
    ]
    next_cursor = encode_cursor(rows[-1][0].created_at, rows[-1][0].id) if has_more and rows else None
    return CourseListResponse(
        items=items,
        next_cursor=next_cursor,
        mode="scan",
        fallback_reason=plan.fallback_reason,
    )


async def _list_courses_fts(
    session,
    *,
    plan,
    status: str | None,
    owner: str | None,
    size: int,
    offset: int,
    highlight_segments,
    table: str,
) -> CourseListResponse:
    """fts 分支：`MATCH` + `bm25` 排序 + offset 分页。

    三条实测结论写在这里，因为它们是**语法约束**而不是风格选择（spec 评审 E3）：
    * `MATCH` 与 `bm25()` 的参数只能写表名，写别名会 `no such column: s`；
    * `bm25()` 返回负数，升序即"最相关在前"；
    * 排序必须带 `created_at DESC, id DESC` 兜底，否则同分文档的顺序不稳定，
      同一页翻两次会看到不同的顺序。
    """
    from sqlalchemy import text as sql_text

    filters = ["course_search MATCH :expr", "c.deleted_at IS NULL"]
    params: dict[str, Any] = {
        "expr": plan.fts_expression or "",
        "limit": size + 1,
        "offset": offset,
    }
    if status:
        filters.append("c.status = :status")
        params["status"] = status
    if owner:
        filters.append("r.owner = :owner")
        params["owner"] = owner
    where = " AND ".join(filters)
    id_sql = sql_text(
        f"""
        SELECT c.id
        FROM {table} s
        JOIN course_versions c ON c.id = s.course_version_id
        JOIN repositories r ON r.id = c.repository_id
        WHERE {where}
        ORDER BY bm25({table}), c.created_at DESC, c.id DESC
        LIMIT :limit OFFSET :offset
        """
    )
    ids = [row[0] for row in (await session.execute(id_sql, params)).all()]
    has_more = len(ids) > size
    ids = ids[:size]
    total_sql = sql_text(
        f"""
        SELECT count(*)
        FROM {table} s
        JOIN course_versions c ON c.id = s.course_version_id
        JOIN repositories r ON r.id = c.repository_id
        WHERE {where}
        """
    )
    total_params = {k: v for k, v in params.items() if k not in {"limit", "offset"}}
    total = int((await session.execute(total_sql, total_params)).scalar() or 0)

    if not ids:
        return CourseListResponse(items=[], mode="fts", next_offset=None, total=total)

    rows = (
        await session.execute(
            select(CourseVersion, Repository)
            .join(Repository, Repository.id == CourseVersion.repository_id)
            .where(CourseVersion.id.in_(ids))
        )
    ).all()
    by_id = {course.id: (course, repo) for course, repo in rows}
    items = []
    for course_id in ids:  # 保持 bm25 的顺序，不能按 DB 返回顺序
        pair = by_id.get(course_id)
        if pair is None:
            continue
        course, repo = pair
        items.append(
            to_list_item(course, repo, highlights=_highlights(plan.tokens, course, repo, highlight_segments))
        )
    next_offset = offset + size if has_more else None
    return CourseListResponse(items=items, mode="fts", next_offset=next_offset, total=total)


def _highlights(tokens, course, repo, highlight_segments):
    """为一条课程生成三段高亮。没命中就返回 `None` 而不是空列表。

    空列表会让前端把整行渲染成空白（"有结果但看起来是空的"），而 `None` 的语义
    是"这里没有高亮"，前端据此回退到普通文本。
    """
    if not tokens:
        return None
    title = [s for s in highlight_segments(course.title or "", tokens)]
    summary = [s for s in highlight_segments((course.summary_md or "")[:512], tokens)]
    repo_name = [s for s in highlight_segments(repo.full_name or "", tokens)]
    if not any(any(seg.marked for seg in group) for group in (title, summary, repo_name)):
        return None
    from repolearn.schemas.course import HighlightGroup, HighlightSegment

    def to_model(group):
        marked = any(seg.marked for seg in group)
        return [HighlightSegment(text=seg.text, marked=seg.marked) for seg in group] if marked else None

    return HighlightGroup(
        title=to_model(title),
        summary=to_model(summary),
        repo=to_model(repo_name),
    )


async def get_course(session, course_id: str, *, require_ready: bool = False) -> tuple[CourseVersion, Repository]:
    course = await session.get(CourseVersion, course_id)
    if course is None or course.deleted_at is not None:
        raise AppError("COURSE_NOT_READY", "课程不存在", status=404)
    if require_ready and course.status not in READABLE_STATUSES:
        raise AppError("COURSE_NOT_READY", details={"status": course.status})
    repo = await session.get(Repository, course.repository_id)
    if repo is None:
        raise AppError("INTERNAL", "课程缺少仓库记录")
    return course, repo


def to_detail(course: CourseVersion, repo: Repository, commit: Commit | None) -> CourseDetail:
    sections = [
        SectionBrief(
            key=str(s.get("key", "")),
            title=str(s.get("title", "")),
            minutes=int(s.get("minutes", 0) or 0),
            lessons=list(s.get("lessons") or []),
        )
        for s in (course.sections or [])
        if isinstance(s, dict)
    ]
    return CourseDetail(
        id=course.id,
        repo=RepoBrief(
            full_name=repo.full_name,
            owner=repo.owner,
            name=repo.name,
            description=repo.description,
            stars=repo.stars,
            license=repo.license_spdx,
            primary_language=repo.primary_language,
            default_branch=repo.default_branch,
            html_url=repo.html_url,
        ),
        commit=CommitBrief(
            sha=course.commit_sha,
            committed_at=commit.committed_at.isoformat() if commit and commit.committed_at else None,
            file_count=commit.file_count if commit else 0,
        ),
        title=course.title or repo.full_name,
        subtitle=course.subtitle,
        summary_md=course.summary_md or "",
        status=course.status,
        language=course.language,
        lesson_count=course.lesson_count,
        minutes=course.total_minutes,
        sections=sections,
        blueprint=dict(course.blueprint or {}),
        quality_report=dict(course.quality_report or {}),
        warnings=list(course.warnings or []),
        cover_palette=course.cover_palette,
        created_at=course.created_at.isoformat() if course.created_at else None,
        published_at=course.published_at.isoformat() if course.published_at else None,
    )


async def create_course(
    session,
    *,
    repo_url: str,
    ref: str | None,
    language: str,
    policy_version: str | None,
    idempotency_key: str | None,
    request_hash: str,
) -> tuple[CourseCreatedResponse, int]:
    """返回 (响应, HTTP 状态码)。202 = 新建了 Job；200 = 命中复用。"""
    if idempotency_key:
        cached = await queue.check_idempotency(
            session, scope="courses.create", key=idempotency_key, request_hash=request_hash
        )
        if cached:
            return CourseCreatedResponse(**cached), 200

    parsed = parse_repo_url(repo_url)
    meta = await fetch_repo_meta(parsed)
    if meta.is_private:
        raise AppError("REPO_FORBIDDEN")
    commit = await resolve_commit(parsed, meta.default_branch, ref or parsed.ref)
    policy = policy_version or DEFAULT_POLICY_VERSION
    key = cache_key_for(meta.full_name, commit.sha, policy, language)

    # 内容级复用：同一仓库同一 commit 的课程只生成一次（T-JOB-2）
    # 注意这里**不带** `deleted_at IS NULL`：`cache_key` 是唯一约束，软删除的行
    # 依然占着这一格。过滤掉它会让下面的 INSERT 撞唯一约束（500 INTERNAL），
    # 用户看到的是"删过的课程再也生成不出来"。发现的软删除行走"复活"分支。
    existing = (
        await session.execute(select(CourseVersion).where(CourseVersion.cache_key == key))
    ).scalar_one_or_none()
    if existing is not None and existing.status in READABLE_STATUSES and existing.deleted_at is None:
        response = CourseCreatedResponse(course_id=existing.id, reused=True)
        await _store_idem(session, idempotency_key, request_hash, response, None)
        return response, 200

    # 同一 cache_key 已有 Job 在排队/运行 → 409 JOB_CONFLICT 并带上那个 job_id（T-JOB-1）。
    # 直接再排一个 Job 的后果不是"多跑一次"，而是两条流同时往同一个
    # course_version 写 lesson/step，最终内容互相覆盖。
    holder = await queue.active_lock_job(session, key)
    if holder is not None:
        raise AppError("JOB_CONFLICT", details={"job_id": holder, "course_cache_key": key})

    repo = (
        await session.execute(select(Repository).where(Repository.full_name == meta.full_name))
    ).scalar_one_or_none()
    if repo is None:
        repo = Repository(
            id=new_id("repository"),
            full_name=meta.full_name,
            owner=meta.owner,
            name=meta.name,
            description=meta.description,
            stars=meta.stars,
            license_spdx=meta.license_spdx,
            primary_language=meta.primary_language,
            default_branch=meta.default_branch,
            html_url=meta.html_url,
            is_public=True,
            created_at=utcnow(),
            updated_at=utcnow(),
        )
        session.add(repo)
        await session.flush()
    else:
        repo.stars = meta.stars
        repo.updated_at = utcnow()

    commit_row = (
        await session.execute(select(Commit).where(Commit.repository_id == repo.id, Commit.sha == commit.sha))
    ).scalar_one_or_none()
    if commit_row is None:
        commit_row = Commit(
            id=new_id("commit"),
            repository_id=repo.id,
            sha=commit.sha,
            committed_at=_parse_dt(commit.committed_at),
            file_count=commit.file_count,
            tarball_bytes=int(commit.extra.get("tarball_bytes", 0) or 0),
            license_note=meta.license_spdx,
            created_at=utcnow(),
        )
        session.add(commit_row)
        await session.flush()

    course = existing
    if course is None:
        course = CourseVersion(
            id=new_id("course_version"),
            repository_id=repo.id,
            commit_sha=commit.sha,
            cache_key=key,
            policy_version=policy,
            language=language,
            title=f"{meta.full_name} 带读课程",
            status="generating",
            sections=[],
            quality_report={},
            warnings=[],
            blueprint={"repo_full_name": meta.full_name, "license": meta.license_spdx},
            cover_palette="mint",
            owner_user_id=None,
            visibility="public",
            created_at=utcnow(),
            updated_at=utcnow(),
        )
        session.add(course)
        await session.flush()
    else:
        course.status = "generating"
        course.updated_at = utcnow()
        if course.deleted_at is not None:
            # 复活软删除的课程：cache_key 唯一，只能复用这一行。
            course.deleted_at = None
            course.visibility = "public"

    job = await queue.enqueue(
        session,
        kind="course",
        payload={
            "repo_url": repo_url,
            "ref": ref,
            "commit": {"sha": commit.sha, "requested_ref": ref},
            "language": language,
        },
        course_version_id=course.id,
        cache_key=key,
    )
    if not await queue.acquire_lock(session, key, job.id):
        # 并发竞争的败者：锁被别人抢到，同一个事务里的写入会被提交但**不能被用**。
        # 抛 409 让调用方直接跳转到已有的 job_id；请求事务回滚，不留半成品。
        raise AppError("JOB_CONFLICT", details={"course_cache_key": key})

    response = CourseCreatedResponse(course_id=course.id, job_id=job.id, status_url=f"/v1/jobs/{job.id}")
    await _store_idem(session, idempotency_key, request_hash, response, job.id)
    log.info("course_created", course_id=course.id, job_id=job.id, sha=commit.sha[:8])
    return response, 202


async def _store_idem(session, key: str | None, request_hash: str, response: CourseCreatedResponse, job_id: str | None) -> None:
    if not key:
        return
    await queue.store_idempotency(
        session,
        scope="courses.create",
        key=key,
        request_hash=request_hash,
        response=response.model_dump(),
        job_id=job_id,
    )


def _parse_dt(value: str | None):
    if not value:
        return None
    from datetime import datetime

    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


async def rebuild_course(session, course_id: str, *, from_stage: str | None, reason: str) -> str:
    course, repo = await get_course(session, course_id)
    job = await queue.enqueue(
        session,
        kind="course",
        payload={
            "repo_url": repo.full_name,
            "commit": {"sha": course.commit_sha},
            "from": from_stage or "curriculum",
            "reason": reason,
        },
        course_version_id=course.id,
        cache_key=course.cache_key,
        priority=80,
    )
    course.status = "generating"
    course.updated_at = utcnow()
    await session.flush()
    return job.id


async def soft_delete(session, course_id: str) -> None:
    course, _repo = await get_course(session, course_id)
    course.deleted_at = utcnow()
    course.visibility = "private"
    await session.flush()


async def anchors(session, course_id: str, *, file: str | None = None) -> list[SourceAnchor]:
    stmt = select(SourceAnchor).where(SourceAnchor.course_version_id == course_id)
    if file:
        stmt = stmt.where(SourceAnchor.file == file)
    return list((await session.execute(stmt.limit(500))).scalars().all())


async def file_content(session, course_id: str, path: str) -> dict[str, Any]:
    """读取课程对应 commit 的源文件内容。

    路径必须经过 `guard.check_path` 且必须在镜像白名单里——这是"用户不能通过
    `?path=../../etc/passwd` 读宿主机"的唯一防线。
    """
    from repolearn.ingest.guard import check_path

    course, _repo = await get_course(session, course_id)
    decision = check_path(path)
    if not decision.ok:
        raise AppError("INGEST_BLOCKED_PATH", f"路径不被允许：{decision.reason}")
    files = {str(f.get("path")): f for f in list_files(course.commit_sha)}
    if decision.rel_path not in files:
        raise AppError("OBJECT_MISSING", "该文件不在本课程的镜像内", status=404)
    try:
        content = read_file(course.commit_sha, decision.rel_path, max_bytes=512 * 1024)
    except FileNotFoundError as exc:
        raise AppError("OBJECT_MISSING", status=404) from exc
    return {
        "path": decision.rel_path,
        "lang": str(files[decision.rel_path].get("lang", "text")),
        "line_count": content.count("\n") + 1,
        "content": content,
        "truncated": len(content) >= 512 * 1024,
    }


async def lesson_count(session, course_id: str) -> int:
    return int(
        (await session.execute(select(func.count(Lesson.id)).where(Lesson.course_version_id == course_id))).scalar() or 0
    )


def search_mode() -> str:
    return settings.search

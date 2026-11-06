"""仓库解析服务（spec §5.2 `POST /v1/repos/resolve`）。

它只做"看一眼这个仓库是什么"——不建 Job、不写镜像。理由：首页的输入框需要
即时反馈（"这个仓库有多少 star、有没有已有课程"），而建 Job 是要花钱的动作，
两者不能混在一个接口里。
"""

from __future__ import annotations

from sqlalchemy import select

from repolearn.core.errors import AppError
from repolearn.ingest.github import fetch_repo_meta, parse_repo_url, resolve_commit
from repolearn.models import CourseVersion
from repolearn.schemas.course import ResolveRepoResponse


async def resolve(session, repo_url: str) -> ResolveRepoResponse:
    ref = parse_repo_url(repo_url)
    meta = await fetch_repo_meta(ref)
    if meta.is_private:
        raise AppError("REPO_FORBIDDEN")
    head = None
    try:
        commit = await resolve_commit(ref, meta.default_branch, ref.ref)
        head = commit.sha
    except AppError:
        # 拿不到 commit 不是致命错误：resolve 的用途是"看元数据"，
        # 真正需要 sha 的是创建课程那一步，那里会再取一次并给出明确错误。
        head = None
    existing = None
    if head:
        row = (
            await session.execute(
                select(CourseVersion)
                .where(CourseVersion.commit_sha == head, CourseVersion.deleted_at.is_(None))
                .order_by(CourseVersion.created_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        existing = row.id if row else None
    return ResolveRepoResponse(
        full_name=meta.full_name,
        description=meta.description,
        stars=meta.stars,
        license=meta.license_spdx,
        default_branch=meta.default_branch,
        head_sha=head,
        existing_course_id=existing,
    )

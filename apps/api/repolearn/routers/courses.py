"""课程路由（spec §5.2 第二组）。

`POST /v1/courses` 的三种终态必须同时存在且语义分明：
* `202 {job_id}` —— 真的新建了生成任务（要花钱）；
* `200 {reused:true}` —— 内容级缓存命中（一分钱不花）；
* `409 JOB_CONFLICT` —— 同一 cache_key 已有任务在跑。
把三者合成一个 200 会掩盖"用户以为重建了、其实拿到旧课程"这件事。
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Header, Query, Response, status

from repolearn.models import Commit
from repolearn.routers.deps import SessionDep, body_hash, require_csrf, require_internal_token
from repolearn.schemas.course import (
    AnchorItem,
    AnchorListResponse,
    CourseCreatedResponse,
    CourseCreateRequest,
    CourseDetail,
    CourseListResponse,
    FileContentResponse,
    RebuildRequest,
    UpgradePlanResponse,
    UpgradeRequest,
    UpgradeStartedResponse,
)
from repolearn.services import course_service, upgrade_service

router = APIRouter(prefix="/v1/courses", tags=["courses"], dependencies=[Depends(require_internal_token)])


@router.post("", response_model=CourseCreatedResponse)
async def create_course(
    payload: CourseCreateRequest,
    session: SessionDep,
    response: Response,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
    _csrf: None = Depends(require_csrf),
) -> CourseCreatedResponse:
    body, code = await course_service.create_course(
        session,
        repo_url=payload.repo_url,
        ref=payload.ref,
        language=payload.language,
        policy_version=payload.policy_version,
        idempotency_key=idempotency_key,
        request_hash=body_hash(payload.model_dump()),
    )
    response.status_code = code
    return body


@router.get("", response_model=CourseListResponse)
async def list_courses(
    session: SessionDep,
    status_: Annotated[str | None, Query(alias="status")] = None,
    owner: str | None = None,
    q: Annotated[str | None, Query(max_length=120)] = None,
    limit: int = 20,
    cursor: str | None = None,
    mode: Annotated[str, Query(pattern="^(auto|scan|fts)$")] = "auto",
    offset: Annotated[int, Query(ge=0, le=200)] = 0,
) -> CourseListResponse:
    """课程列表。

    `q` 的 `max_length=120` 与 `offset` 的 `0..200` 都是**契约的一环**（spec
    §5.1.1 早就写死了范围，而 v1 的 router 一个约束都没有——文档与实现分叉时，
    用户遇到的是"输了一大段话，服务端 500"）。

    `offset` 只在 fts **生效**时才有意义：scan 用 keyset 游标，两者混用会让用户
    以为"翻到第二页"而实际拿到第一页的重复行。但"是否生效"要等 `plan_search`
    按运行时能力与查询长度算完才知道（`mode=auto` 时尤甚），因此在
    `course_service.list_courses` 里判，不在这里按参数值猜——按参数值猜的后果是
    "同一份请求在装得上 fts 的机器上能用、在装不上的机器上 422"。
    """
    return await course_service.list_courses(
        session, status=status_, owner=owner, q=q, limit=limit, cursor=cursor, mode=mode, offset=offset
    )


@router.get("/{course_id}", response_model=CourseDetail)
async def get_course(course_id: str, session: SessionDep) -> CourseDetail:
    from sqlalchemy import select

    course, repo = await course_service.get_course(session, course_id)
    commit_row = (
        await session.execute(
            select(Commit).where(Commit.repository_id == repo.id, Commit.sha == course.commit_sha)
        )
    ).scalar_one_or_none()
    return course_service.to_detail(course, repo, commit_row)


@router.post("/{course_id}/rebuild", status_code=status.HTTP_202_ACCEPTED)
async def rebuild(
    course_id: str, payload: RebuildRequest, session: SessionDep, _csrf: None = Depends(require_csrf)
) -> dict:
    job_id = await course_service.rebuild_course(
        session, course_id, from_stage=payload.from_stage, reason=payload.reason
    )
    return {"job_id": job_id}


@router.post(
    "/{course_id}/upgrade",
    status_code=status.HTTP_200_OK,
    response_model=UpgradePlanResponse | UpgradeStartedResponse,
)
async def upgrade_course(
    course_id: str,
    payload: UpgradeRequest,
    session: SessionDep,
    response: Response,
    _csrf: None = Depends(require_csrf),
):
    """仓库有新 commit 时生成**新版本**（spec §3.5 / §5.1.2）。

    与 `/rebuild` 的语义区别必须刻在两处：这里是**新的 sha**、且旧版本**全程保持
    可读**（不置 `generating`）；`/rebuild` 是同一个 sha 覆盖本版本内容。混用会
    让用户"以为看了新版，其实旧版被打断"。

    三种终态：`200 {mode: none|partial|full}`（dry_run 或无需生成）、
    `202 {job_id}`（真的开始生成）、`409 JOB_CONFLICT`（同一新 cache_key 已有任务）。
    """
    result, code = await upgrade_service.start_upgrade(
        session,
        course_id,
        ref=payload.ref,
        dry_run=payload.dry_run,
    )
    response.status_code = code
    return result


@router.delete("/{course_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_course(course_id: str, session: SessionDep, _csrf: None = Depends(require_csrf)) -> Response:
    await course_service.soft_delete(session, course_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/{course_id}/anchors", response_model=AnchorListResponse)
async def anchors(course_id: str, session: SessionDep, file: str | None = None) -> AnchorListResponse:
    rows = await course_service.anchors(session, course_id, file=file)
    return AnchorListResponse(
        items=[
            AnchorItem(
                id=row.id,
                file=row.file,
                symbol=row.symbol,
                line_start=row.line_start,
                line_end=row.line_end,
                kind=row.kind,
            )
            for row in rows
        ]
    )


@router.get("/{course_id}/files", response_model=FileContentResponse)
async def file_content(course_id: str, session: SessionDep, path: str) -> Response:
    """单文件内容。响应头带 `Cache-Control: private, max-age=3600`（内容随 commit 不变）。"""
    from fastapi.responses import JSONResponse

    data = await course_service.file_content(session, course_id, path)
    return JSONResponse(content=data, headers={"Cache-Control": "private, max-age=3600"})

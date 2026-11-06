"""仓库解析路由（spec §5.2 `POST /v1/repos/resolve`）。"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from repolearn.routers.deps import SessionDep, require_csrf, require_internal_token
from repolearn.schemas.course import ResolveRepoRequest, ResolveRepoResponse
from repolearn.services import repo_service

router = APIRouter(prefix="/v1/repos", tags=["repos"], dependencies=[Depends(require_internal_token)])


@router.post("/resolve", response_model=ResolveRepoResponse, dependencies=[Depends(require_csrf)])
async def resolve(payload: ResolveRepoRequest, session: SessionDep) -> ResolveRepoResponse:
    return await repo_service.resolve(session, payload.repo_url)

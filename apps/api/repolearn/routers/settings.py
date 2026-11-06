"""设置路由（spec §5.2 第一组后半 / §3.6.3 / §3.13）。

与 `/v1/setup/*` 分开的理由：setup 是"首次配置"的一次性流程，settings 是"长期
调整"。它们共享数据模型，但**权限与失败语义不同**——setup 的失败要不锁死向导，
settings 的失败要明确告诉用户"当前配置没有被改动"。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from repolearn.routers.deps import SessionDep, require_csrf, require_internal_token
from repolearn.schemas.setup import (
    ActivateResponse,
    DoctorResponse,
    ProfileListResponse,
    RevisionListResponse,
    RevisionResponse,
    RolesPatch,
    RotateSecretRequest,
    RotateSecretResponse,
)
from repolearn.services import setup_service

router = APIRouter(prefix="/v1/settings", tags=["settings"], dependencies=[Depends(require_internal_token)])


@router.get("/profiles", response_model=ProfileListResponse)
async def list_profiles(session: SessionDep) -> ProfileListResponse:
    return ProfileListResponse(items=await setup_service.list_profiles(session))


@router.post("/profiles/{profile_id}/activate", response_model=ActivateResponse, dependencies=[Depends(require_csrf)])
async def activate(profile_id: str, session: SessionDep) -> ActivateResponse:
    revision = await setup_service.activate_profile(session, profile_id)
    return ActivateResponse(active_profile_id=profile_id, revision=revision)


@router.patch("/roles", response_model=RevisionResponse, dependencies=[Depends(require_csrf)])
async def patch_roles(payload: RolesPatch, session: SessionDep) -> RevisionResponse:
    revision = await setup_service.patch_roles(session, payload.roles)
    return RevisionResponse(revision=revision)


@router.get("/revisions", response_model=RevisionListResponse)
async def list_revisions(session: SessionDep, limit: int = 20) -> RevisionListResponse:
    return RevisionListResponse(items=await setup_service.list_revisions(session, limit))


@router.post("/revisions/{rev}/rollback", response_model=RevisionResponse, dependencies=[Depends(require_csrf)])
async def rollback(rev: int, session: SessionDep) -> RevisionResponse:
    revision = await setup_service.rollback(session, rev)
    return RevisionResponse(revision=revision)


@router.post("/rotate-secret", response_model=RotateSecretResponse, dependencies=[Depends(require_csrf)])
async def rotate_secret(payload: RotateSecretRequest, session: SessionDep) -> RotateSecretResponse:
    rotated = await setup_service.rotate_secret(session, payload.new_secret)
    return RotateSecretResponse(rotated=rotated)


@router.get("/doctor", response_model=DoctorResponse)
async def doctor(session: SessionDep) -> DoctorResponse:
    return DoctorResponse(checks=await setup_service.doctor(session))

"""配置引导路由（spec §5.2 `/v1/setup/*`）。

`/v1/setup/state` 被 `/setup` 页在**客户端**调用（不是 SSR），因为 RSC 里没有
"超时后仍返回"的能力——那正是 v1 的 302 死循环的成因（P1-6）。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from repolearn.routers.deps import SessionDep, require_csrf, require_internal_token
from repolearn.schemas.setup import (
    LlmProbeRequest,
    LlmProbeResponse,
    SetupCommitRequest,
    SetupCommitResponse,
    SetupStateResponse,
    TtsProbeRequest,
    TtsProbeResponse,
)
from repolearn.services import setup_service

router = APIRouter(prefix="/v1/setup", tags=["setup"], dependencies=[Depends(require_internal_token)])


@router.get("/state", response_model=SetupStateResponse)
async def setup_state(session: SessionDep) -> SetupStateResponse:
    return await setup_service.setup_state(session)


@router.post("/llm/probe", response_model=LlmProbeResponse)
async def probe_llm(payload: LlmProbeRequest) -> LlmProbeResponse:
    """测量接口：失败也是 200 + `ok=false`（§5.2 唯一例外，P2-1）。"""
    return await setup_service.probe_llm(payload)


@router.post("/tts/probe", response_model=TtsProbeResponse)
async def probe_tts(payload: TtsProbeRequest) -> TtsProbeResponse:
    return await setup_service.probe_tts(payload)


@router.post("/commit", response_model=SetupCommitResponse, dependencies=[Depends(require_csrf)])
async def commit_setup(payload: SetupCommitRequest, session: SessionDep) -> SetupCommitResponse:
    profile, revision, warnings = await setup_service.commit_setup(session, payload)
    return SetupCommitResponse(profile_id=profile.id, revision=revision, warnings=warnings)

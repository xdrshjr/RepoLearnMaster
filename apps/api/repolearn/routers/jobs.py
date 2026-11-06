"""任务与 SSE 路由（spec §5.2 / §5.5）。

`GET /v1/jobs/{id}/events` 是整条链路里最容易被缓冲坏掉的端点（P1-5）。
它必须：
* 先**补发** `Last-Event-ID` 之后的历史事件（来自 `job_events`）；
* 若无历史可补（超出保留窗口）→ 发一帧 `job.snapshot`（规则 2）；
* 之后订阅 `event_bus`，逐条写帧，每 15 秒一个 `: keepalive`；
* 响应头禁缓冲（`no-cache, no-transform` + `X-Accel-Buffering: no`）。

**不用原生 EventSource 的客户端原因**在 §7.5：它不能带自定义头、不能可靠设置
`Last-Event-ID`。服务端这一侧则必须对两种客户端都成立。
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import APIRouter, Depends, Header, Query
from fastapi.responses import StreamingResponse

from repolearn.core.errors import AppError
from repolearn.routers.deps import SessionDep, require_csrf, require_internal_token
from repolearn.schemas.job import (
    JobCancelResponse,
    JobDetail,
    JobListResponse,
    JobRetryResponse,
)
from repolearn.services import job_service
from repolearn.services.event_bus import KEEPALIVE_FRAME, bus, sse_frame

router = APIRouter(prefix="/v1/jobs", tags=["jobs"], dependencies=[Depends(require_internal_token)])

SSE_HEADERS = {
    "Cache-Control": "no-cache, no-transform",
    "X-Accel-Buffering": "no",
    "Connection": "keep-alive",
}


@router.get("", response_model=JobListResponse)
async def list_jobs(
    session: SessionDep,
    status_: Annotated[str | None, Query(alias="status")] = None,
    kind: str | None = None,
    limit: int = 20,
) -> JobListResponse:
    items = await job_service.list_jobs(session, status=status_, kind=kind, limit=limit)
    return JobListResponse(items=items)


@router.get("/{job_id}", response_model=JobDetail)
async def get_job(job_id: str, session: SessionDep) -> JobDetail:
    return await job_service.get_job(session, job_id)


@router.get("/{job_id}/events")
async def job_events(
    job_id: str,
    session: SessionDep,
    last_event_id: Annotated[int | None, Header(alias="Last-Event-ID")] = None,
    since: int | None = None,
) -> StreamingResponse:
    cursor = last_event_id if last_event_id is not None else (since or 0)
    history, snapshot_needed = await job_service.job_events(session, job_id, cursor or 0)
    detail = await job_service.get_job(session, job_id)

    async def stream() -> AsyncIterator[bytes]:
        queue = await bus.subscribe(job_id)
        try:
            if snapshot_needed:
                snap = _snapshot_frame(detail, max(cursor or 0, 1))
                yield snap.encode("utf-8")
            for env in history:
                yield sse_frame(env).encode("utf-8")
            while True:
                try:
                    env = await asyncio.wait_for(queue.get(), timeout=15.0)
                except asyncio.TimeoutError:
                    yield KEEPALIVE_FRAME.encode("utf-8")
                    continue
                yield sse_frame(env).encode("utf-8")
                if env.type in ("job.completed", "job.failed") and env.data.get("status") in (
                    "ready",
                    "partial",
                    "failed",
                    "failed_budget",
                    "cancelled",
                ):
                    return
                if env.type == "job.failed":
                    return
        finally:
            await bus.unsubscribe(job_id, queue)

    return StreamingResponse(stream(), media_type="text/event-stream; charset=utf-8", headers=SSE_HEADERS)


def _snapshot_frame(detail: JobDetail, seq: int) -> str:
    """超出保留窗口时的一帧快照（§5.5 规则 2）：让前端**重建**而不是从中间态硬拼。"""
    import json

    payload = {
        "schemaVersion": 1,
        "type": "job.snapshot",
        "seq": seq,
        "ts": 0,
        "jobId": detail.id,
        "runId": None,
        "data": detail.model_dump(),
    }
    return f"id: {seq}\nevent: job.snapshot\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


@router.post("/{job_id}/cancel", response_model=JobCancelResponse, dependencies=[Depends(require_csrf)])
async def cancel(job_id: str, session: SessionDep) -> JobCancelResponse:
    status_value = await job_service.cancel(session, job_id)
    return JobCancelResponse(status=status_value)


@router.post("/{job_id}/retry", response_model=JobRetryResponse, dependencies=[Depends(require_csrf)])
async def retry(job_id: str, session: SessionDep) -> JobRetryResponse:
    return JobRetryResponse(job_id=await job_service.retry(session, job_id))

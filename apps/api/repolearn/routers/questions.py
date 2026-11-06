"""提问路由（spec §5.2 `POST /v1/courses/{id}/questions` 返回 SSE）。

SSE 的四条流式规则（§5.5）在 BFF 侧最容易丢，但这里要先保证**服务端本身**是
流式的：`StreamingResponse` + 生成器，逐事件 yield，绝不在服务端聚合。

`X-Accel-Buffering: no` 与 `Cache-Control: no-cache, no-transform` 是给中间层看的：
少了它们，nginx / next start 会把整条流缓冲到结束，用户体感是"卡 30 秒后一次性出现"。
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from repolearn.routers.deps import SessionDep, require_csrf, require_internal_token
from repolearn.schemas.job import EventEnvelope
from repolearn.schemas.question import AskRequest, QuestionListResponse
from repolearn.services import question_service

router = APIRouter(prefix="/v1/courses/{course_id}/questions", tags=["questions"], dependencies=[Depends(require_internal_token)])

SSE_HEADERS = {
    "Cache-Control": "no-cache, no-transform",
    "X-Accel-Buffering": "no",
    "Connection": "keep-alive",
}


@router.post("", dependencies=[Depends(require_csrf)])
async def ask(course_id: str, payload: AskRequest, session: SessionDep) -> StreamingResponse:
    async def stream() -> AsyncIterator[bytes]:
        seq = 0
        try:
            async for event_type, data in question_service.ask_stream(session, course_id, payload):
                seq += 1
                env = EventEnvelope(
                    schemaVersion=1,
                    type=event_type,
                    seq=seq,
                    ts=0,
                    jobId=None,
                    runId=None,
                    data=data,
                )
                frame = f"id: {seq}\nevent: {event_type}\ndata: {json.dumps(env.model_dump(), ensure_ascii=False)}\n\n"
                yield frame.encode("utf-8")
            await session.commit()
        except Exception as exc:  # noqa: BLE001 - 流已开始，只能以事件形式报错
            seq += 1
            payload_data = {"code": "INTERNAL", "message": str(exc)[:300], "retryable": True}
            env = EventEnvelope(schemaVersion=1, type="question.failed", seq=seq, ts=0, data=payload_data)
            yield f"id: {seq}\nevent: question.failed\ndata: {json.dumps(env.model_dump(), ensure_ascii=False)}\n\n".encode()

    return StreamingResponse(stream(), media_type="text/event-stream; charset=utf-8", headers=SSE_HEADERS)


@router.get("", response_model=QuestionListResponse)
async def list_questions(course_id: str, session: SessionDep, lesson_key: str | None = None) -> QuestionListResponse:
    return QuestionListResponse(items=await question_service.list_questions(session, course_id, lesson_key))

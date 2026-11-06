"""进度、答题与完课路由（spec §5.2 第三组）。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request, Response, status

from repolearn.routers.deps import SessionDep, require_csrf, require_internal_token
from repolearn.schemas.progress import (
    ProgressResponse,
    ProgressUpdate,
    QuizAnswerRequest,
    QuizAnswerResponse,
    RecapResponse,
)
from repolearn.services import progress_service

router = APIRouter(prefix="/v1/courses/{course_id}", tags=["progress"], dependencies=[Depends(require_internal_token)])


@router.put("/progress", response_model=ProgressResponse, dependencies=[Depends(require_csrf)])
async def put_progress(course_id: str, payload: ProgressUpdate, session: SessionDep) -> ProgressResponse:
    return await progress_service.save_progress(session, course_id, payload)


@router.post("/progress/beacon", status_code=status.HTTP_204_NO_CONTENT)
async def progress_beacon(course_id: str, request: Request, session: SessionDep) -> Response:
    """`navigator.sendBeacon` 专用：浏览器不读响应，因此返回 204 且**不校验 CSRF**。

    为什么这是个例外：`sendBeacon` 无法自定义请求头，所以它既带不了
    `X-CSRF-Token` 也带不了 `Idempotency-Key`。这个端点只写"进度"这一种
    幂等覆盖型数据（不是创建/删除），缺少 CSRF 的风险面可以接受。
    """
    raw = await request.body()
    try:
        payload = ProgressUpdate.model_validate_json(raw.decode("utf-8", "ignore"))
    except Exception:  # noqa: BLE001 - beacon 的失败不可见，安静丢弃
        from fastapi import HTTPException

        raise HTTPException(status_code=204) from None
    await progress_service.save_progress(session, course_id, payload)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/quiz/{item_id}/answer", response_model=QuizAnswerResponse, dependencies=[Depends(require_csrf)])
async def answer_quiz(course_id: str, item_id: str, payload: QuizAnswerRequest, session: SessionDep) -> QuizAnswerResponse:
    return await progress_service.answer_quiz(session, course_id, item_id, payload.choice_id)


@router.get("/recap", response_model=RecapResponse)
async def recap(course_id: str, session: SessionDep) -> RecapResponse:
    return await progress_service.recap(session, course_id)

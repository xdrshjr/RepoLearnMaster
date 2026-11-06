"""课时路由（spec §5.2）。"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from repolearn.routers.deps import SessionDep, require_internal_token
from repolearn.schemas.lesson import LessonDetail, LessonListResponse
from repolearn.services import lesson_service

router = APIRouter(prefix="/v1/courses/{course_id}/lessons", tags=["lessons"], dependencies=[Depends(require_internal_token)])


@router.get("", response_model=LessonListResponse)
async def list_lessons(course_id: str, session: SessionDep) -> LessonListResponse:
    return await lesson_service.list_lessons(session, course_id)


@router.get("/{lesson_key}", response_model=LessonDetail)
async def get_lesson(course_id: str, lesson_key: str, session: SessionDep) -> LessonDetail:
    return await lesson_service.lesson_detail(session, course_id, lesson_key)

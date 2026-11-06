"""播放路由（spec §5.2 / §5.3）。

单独一个 router 而不是塞进 lessons：`playback` 是**播放器的唯一数据源**，
它的响应体最大、被调用最频繁、也最容易被缓存策略影响（`no-store` 而不是
`max-age`，因为进度与音频 URL 会随重新生成变化）。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Response

from repolearn.routers.deps import SessionDep, require_internal_token
from repolearn.schemas.playback import PlaybackBundle
from repolearn.services import lesson_service

router = APIRouter(prefix="/v1/courses/{course_id}/lessons", tags=["playback"], dependencies=[Depends(require_internal_token)])


@router.get("/{lesson_key}/playback", response_model=PlaybackBundle)
async def playback(course_id: str, lesson_key: str, session: SessionDep, response: Response) -> PlaybackBundle:
    # 播放数据必须每次校验（重新生成后旧 bundle 会失效），因此显式 no-store。
    response.headers["Cache-Control"] = "no-store"
    return await lesson_service.playback(session, course_id, lesson_key)

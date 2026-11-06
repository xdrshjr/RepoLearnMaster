"""Pydantic schema 统一出口。

**schema 与表结构不共享命名**（`CourseDetail` vs `course_versions`），映射在
`services/*_service.py` 里显式完成。这一层"多写一点代码"换来的是"数据库可以重构
而不破坏 API 契约"——对本项目（后期要加私有仓库/多人协作）是必要投资。
"""

from __future__ import annotations

from repolearn.schemas.book import (
    BookChapterDetail,
    BookDetail,
    BookGenerateRequest,
    PdfStatus,
)
from repolearn.schemas.course import (
    CourseCreateRequest,
    CourseDetail,
    CourseListItem,
    CourseListResponse,
    RepoBrief,
    ResolveRepoRequest,
    ResolveRepoResponse,
    SectionBrief,
)
from repolearn.schemas.job import JobDetail, JobListResponse, MetricsResponse
from repolearn.schemas.lesson import LessonBrief, LessonDetail, LessonListResponse
from repolearn.schemas.note import NoteCreate, NoteDetail, NoteListResponse, NotePatch
from repolearn.schemas.playback import PlaybackBundle, StepBundle
from repolearn.schemas.progress import ProgressResponse, ProgressUpdate
from repolearn.schemas.question import AskRequest, QuestionDetail, QuestionListResponse
from repolearn.schemas.setup import (
    DoctorCheck,
    DoctorResponse,
    LlmProbeRequest,
    LlmProbeResponse,
    ProfileItem,
    ProfileListResponse,
    RevisionItem,
    RevisionListResponse,
    RolesPatch,
    SetupCommitRequest,
    SetupCommitResponse,
    SetupStateResponse,
    TtsProbeRequest,
    TtsProbeResponse,
)

__all__ = [
    "AskRequest",
    "BookChapterDetail",
    "BookDetail",
    "BookGenerateRequest",
    "CourseCreateRequest",
    "CourseDetail",
    "CourseListItem",
    "CourseListResponse",
    "DoctorCheck",
    "DoctorResponse",
    "JobDetail",
    "JobListResponse",
    "LessonBrief",
    "LessonDetail",
    "LessonListResponse",
    "LlmProbeRequest",
    "LlmProbeResponse",
    "MetricsResponse",
    "NoteCreate",
    "NoteDetail",
    "NoteListResponse",
    "NotePatch",
    "PdfStatus",
    "PlaybackBundle",
    "ProfileItem",
    "ProfileListResponse",
    "ProgressResponse",
    "ProgressUpdate",
    "QuestionDetail",
    "QuestionListResponse",
    "RepoBrief",
    "ResolveRepoRequest",
    "ResolveRepoResponse",
    "RevisionItem",
    "RevisionListResponse",
    "RolesPatch",
    "SectionBrief",
    "SetupCommitRequest",
    "SetupCommitResponse",
    "SetupStateResponse",
    "StepBundle",
    "TtsProbeRequest",
    "TtsProbeResponse",
]

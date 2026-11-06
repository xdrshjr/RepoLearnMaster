"""课程与仓库 schema（spec §5.2 第二组接口）。"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ResolveRepoRequest(BaseModel):
    repo_url: str = Field(min_length=3, max_length=400)


class RepoBrief(BaseModel):
    full_name: str
    owner: str = ""
    name: str = ""
    description: str | None = None
    stars: int = 0
    license: str | None = None
    primary_language: str | None = None
    default_branch: str = "main"
    html_url: str | None = None


class CommitBrief(BaseModel):
    sha: str
    committed_at: str | None = None
    file_count: int = 0


class ResolveRepoResponse(BaseModel):
    full_name: str
    description: str | None = None
    stars: int = 0
    license: str | None = None
    default_branch: str = "main"
    head_sha: str | None = None
    existing_course_id: str | None = None


class CourseCreateRequest(BaseModel):
    repo_url: str = Field(min_length=3, max_length=400)
    ref: str | None = Field(default=None, max_length=120)
    language: str = Field(default="zh", max_length=10)
    policy_version: str | None = Field(default=None, max_length=40)


class CourseCreatedResponse(BaseModel):
    """未命中缓存 → 202 `{job_id, course_id, status_url}`；命中 → 200 `{course_id, reused}`。"""

    course_id: str
    job_id: str | None = None
    reused: bool = False
    status_url: str | None = None


class QualityBrief(BaseModel):
    anchor_coverage: float = 0.0
    lesson_completeness: float = 0.0
    degraded: bool = False
    anchor_confidence: str = "high"


class CourseListItem(BaseModel):
    id: str
    repo: RepoBrief
    title: str
    summary: str = ""
    lesson_count: int = 0
    minutes: int = 0
    status: str = "generating"
    quality: QualityBrief = Field(default_factory=QualityBrief)
    updated_at: str | None = None
    cover_palette: str = "mint"


class CourseListResponse(BaseModel):
    items: list[CourseListItem] = Field(default_factory=list)
    next_cursor: str | None = None


class SectionBrief(BaseModel):
    key: str
    title: str
    minutes: int = 0
    lessons: list[dict[str, Any]] = Field(default_factory=list)


class CourseDetail(BaseModel):
    id: str
    repo: RepoBrief
    commit: CommitBrief
    title: str
    subtitle: str | None = None
    summary_md: str = ""
    status: str
    language: str = "zh"
    lesson_count: int = 0
    minutes: int = 0
    sections: list[SectionBrief] = Field(default_factory=list)
    blueprint: dict[str, Any] = Field(default_factory=dict)
    quality_report: dict[str, Any] = Field(default_factory=dict)
    warnings: list[dict[str, Any]] = Field(default_factory=list)
    cover_palette: str = "mint"
    created_at: str | None = None
    published_at: str | None = None


class RebuildRequest(BaseModel):
    reason: str = Field(default="user", max_length=200)
    from_stage: str | None = Field(default=None, alias="from", max_length=20)

    model_config = {"populate_by_name": True}


class AnchorItem(BaseModel):
    id: str
    file: str
    symbol: str | None = None
    line_start: int = 1
    line_end: int = 1
    kind: str = "definition"


class AnchorListResponse(BaseModel):
    items: list[AnchorItem] = Field(default_factory=list)


class FileContentResponse(BaseModel):
    path: str
    lang: str = "text"
    line_count: int = 0
    content: str = ""
    truncated: bool = False

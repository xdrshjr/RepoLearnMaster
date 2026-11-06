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


class HighlightSegment(BaseModel):
    """高亮片段。`marked=True` 的片段由前端渲染成 `<mark>`（**服务端不返回 HTML**）。"""

    text: str
    marked: bool = False


class HighlightGroup(BaseModel):
    """一条课程在三个可搜索字段上的高亮（未命中/未搜索时为 `None`）。"""

    title: list[HighlightSegment] | None = None
    summary: list[HighlightSegment] | None = None
    repo: list[HighlightSegment] | None = None


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
    #: 搜索高亮。未搜索时为 `None`（老前端不受影响：加的是有默认值的新字段）。
    highlights: HighlightGroup | None = None


class CourseListResponse(BaseModel):
    items: list[CourseListItem] = Field(default_factory=list)
    #: keyset 游标（scan 模式）。fts 模式恒为 `None`——bm25 是浮点分数，
    #: 把浮点编进游标会在索引变化后产生幽灵重复行（spec §10 第 2 条）。
    next_cursor: str | None = None
    #: **实际生效**模式（不是配置值）。G3 的本质是"系统说了谎"，回显实际
    #: 生效模式是让撒谎变得不可能的唯一办法。
    mode: str = "none"
    #: `query_too_short` / `sqlite_too_old` / None
    fallback_reason: str | None = None
    #: fts 模式的下一页偏移；其他模式为 `None`。
    next_offset: int | None = None
    #: fts 模式的 `COUNT(*)`；scan 为 `None`（scan 不额外数一遍）。
    total: int | None = None


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


class UpgradeRequest(BaseModel):
    """`POST /v1/courses/{id}/upgrade`。

    `dry_run=True` 只算不改：返回受影响课时清单供 UI 抽屉展示，**不写库**。
    注意它并不免费——走到那一步已经下载并解包了整包 tarball，因此服务端还有
    三道闸（体积上限 / 计划缓存 / 20s 预算，spec §3.5.2）。
    """

    ref: str | None = Field(default=None, max_length=120)
    dry_run: bool = False


class AffectedLesson(BaseModel):
    key: str
    title: str = ""


class UpgradePlanResponse(BaseModel):
    """200：计划（dry_run 或 `mode in {none, reused}`）。"""

    mode: str
    reasons: list[str] = Field(default_factory=list)
    stats: dict[str, int] = Field(default_factory=dict)
    affected_lessons: list[AffectedLesson] = Field(default_factory=list)
    course_id: str
    from_sha: str = ""
    to_sha: str = ""


class UpgradeStartedResponse(BaseModel):
    """202：真的开始生成新版本。旧版本全程保持可读（与 `/rebuild` 的关键区别）。"""

    job_id: str
    course_id: str
    mode: str


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

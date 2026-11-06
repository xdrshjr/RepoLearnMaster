"""任务与系统 schema（spec §5.2 第五组 / §5.5 事件信封）。"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class JobCost(BaseModel):
    tokens: int = 0
    usd: float = 0.0


class JobDetail(BaseModel):
    id: str
    kind: str
    status: str
    progress: int = 0
    node: str | None = None
    message: str | None = None
    course_id: str | None = None
    book_id: str | None = None
    started_at: str | None = None
    finished_at: str | None = None
    error: dict[str, Any] | None = None
    cost: JobCost = Field(default_factory=JobCost)
    created_at: str | None = None
    attempts: int = 0


class JobListResponse(BaseModel):
    items: list[JobDetail] = Field(default_factory=list)
    next_cursor: str | None = None


class JobCancelResponse(BaseModel):
    status: str = "cancelling"


class JobRetryResponse(BaseModel):
    job_id: str


class MetricsResponse(BaseModel):
    jobs: dict[str, Any] = Field(default_factory=dict)
    cache: dict[str, Any] = Field(default_factory=dict)
    providers: dict[str, Any] = Field(default_factory=dict)
    learning: dict[str, Any] = Field(default_factory=dict)
    generated_at: str | None = None


class HealthResponse(BaseModel):
    ok: bool
    db: bool
    kernel: bool
    migration: bool
    version: str
    gates: dict[str, str] = Field(default_factory=dict)


class EventEnvelope(BaseModel):
    """§5.5 的事件信封。前端对未知 `type` 只记日志不崩。"""

    schemaVersion: int = 1
    type: str
    seq: int
    ts: int
    jobId: str | None = None
    runId: str | None = None
    data: dict[str, Any] = Field(default_factory=dict)

"""课时 schema（spec §5.2）。"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class LessonBrief(BaseModel):
    key: str
    title: str
    status: str = "ready"
    minutes: int = 0
    step_count: int = 0


class LessonSection(BaseModel):
    key: str
    title: str
    minutes: int = 0
    lessons: list[LessonBrief] = Field(default_factory=list)


class LessonListResponse(BaseModel):
    sections: list[LessonSection] = Field(default_factory=list)


class LessonDetail(BaseModel):
    key: str
    title: str
    layer: str = "overview"
    minutes: int = 0
    goal: str | None = None
    anchors: list[dict[str, Any]] = Field(default_factory=list)
    steps: list[dict[str, Any]] = Field(default_factory=list)
    quiz: list[dict[str, Any]] = Field(default_factory=list)
    files: list[dict[str, Any]] = Field(default_factory=list)
    trace_key: str | None = None

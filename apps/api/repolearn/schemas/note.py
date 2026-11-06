"""笔记 schema（spec §5.2）。"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class NoteCreate(BaseModel):
    course_version_id: str | None = None
    lesson_id: str | None = None
    anchor_id: str | None = None
    body_md: str = Field(min_length=1, max_length=8000)
    tags: list[str] = Field(default_factory=list)


class NotePatch(BaseModel):
    body_md: str | None = Field(default=None, max_length=8000)
    tags: list[str] | None = None


class NoteDetail(BaseModel):
    id: str
    course_version_id: str | None = None
    lesson_id: str | None = None
    anchor_id: str | None = None
    body_md: str = ""
    tags: list[str] = Field(default_factory=list)
    created_at: str | None = None
    updated_at: str | None = None
    meta: dict[str, Any] = Field(default_factory=dict)


class NoteListResponse(BaseModel):
    items: list[NoteDetail] = Field(default_factory=list)

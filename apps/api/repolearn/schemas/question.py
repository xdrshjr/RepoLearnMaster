"""行内提问 schema（spec §5.2 / §3.9 S4）。"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class AskRequest(BaseModel):
    file: str = Field(min_length=1, max_length=400)
    line_start: int = 1
    line_end: int = 1
    question: str = Field(min_length=1, max_length=2000)
    layer: str = Field(default="deep_dive", max_length=20)
    lesson_key: str | None = Field(default=None, max_length=40)


class QuestionDetail(BaseModel):
    id: str
    lesson_id: str | None = None
    file: str = ""
    line_start: int = 0
    line_end: int = 0
    layer: str = "deep_dive"
    question: str = ""
    answer_md: str = ""
    evidence: list[dict[str, Any]] = Field(default_factory=list)
    runtime: str = "template"
    created_at: str | None = None


class QuestionListResponse(BaseModel):
    items: list[QuestionDetail] = Field(default_factory=list)

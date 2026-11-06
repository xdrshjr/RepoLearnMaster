"""进度、答题、笔记、提问 schema（spec §5.2 第三组）。"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ProgressUpdate(BaseModel):
    lesson_key: str = Field(max_length=40)
    step_index: int = 0
    position_ms: int = 0
    percent: int = 0


class ProgressResponse(BaseModel):
    progress: int = 0
    course_percent: int = 0


class QuizAnswerRequest(BaseModel):
    choice_id: str = Field(max_length=20)


class QuizAnswerResponse(BaseModel):
    correct: bool
    explanation_md: str = ""
    evidence: list[dict[str, Any]] = Field(default_factory=list)
    replayed: bool = False


class RecapResponse(BaseModel):
    knowledge_points: list[dict[str, Any]] = Field(default_factory=list)
    call_chain: dict[str, Any] = Field(default_factory=dict)
    pitfalls: list[str] = Field(default_factory=list)
    quiz_stats: dict[str, Any] = Field(default_factory=dict)
    next_steps: list[str] = Field(default_factory=list)
    ability: dict[str, float] = Field(default_factory=dict)
    completed: bool = False
    percent: int = 0

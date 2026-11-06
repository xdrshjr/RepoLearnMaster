"""书籍与 PDF schema（spec §5.2 第四组）。"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class BookGenerateRequest(BaseModel):
    preset: Literal["standard", "deep"] = "standard"
    include_audio: bool = False


class BookCreatedResponse(BaseModel):
    book_id: str
    job_id: str | None = None
    reused: bool = False


class ChapterBrief(BaseModel):
    key: str
    title: str
    words: int = 0


class BookDetail(BaseModel):
    id: str
    course_version_id: str
    preset: str = "standard"
    status: str = "generating"
    title: str = ""
    chapters: list[ChapterBrief] = Field(default_factory=list)
    toc: list[dict[str, Any]] = Field(default_factory=list)
    quality: dict[str, Any] = Field(default_factory=dict)
    word_count: int = 0


class BookBlock(BaseModel):
    type: str = "md"
    text: str = ""
    lang: str | None = None
    caption: str | None = None


class BookChapterDetail(BaseModel):
    key: str
    title: str
    blocks: list[BookBlock] = Field(default_factory=list)
    source_refs: list[dict[str, Any]] = Field(default_factory=list)


class PdfCreateRequest(BaseModel):
    engine: Literal["chromium", "browser-print"] = "chromium"


class PdfCreatedResponse(BaseModel):
    job_id: str


class PdfStatus(BaseModel):
    status: str = "queued"
    pdf_url: str | None = None
    pages: int = 0
    bytes: int = 0
    generated_at: str | None = None
    commit_sha: str = ""
    engine: str = "chromium"
    print_view_url: str | None = None
    error: dict[str, Any] = Field(default_factory=dict)

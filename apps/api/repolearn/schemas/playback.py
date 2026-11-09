"""`PlaybackBundle`（spec §5.3）——播放器的唯一数据源。

三条约束写在 schema 旁边而不是只写在文档里：
* `segments` 必须覆盖 `[0, duration_ms]` 且不重叠（§5.3），由发布前校验保证；
* `code` 内容**不内联**到 playback（体积大），走 `GET /courses/{id}/files?path=`；
* 所有二进制地址一律是同源的 `/api/objects/<kind>/<name>`（P1-4）。
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class FocusRef(BaseModel):
    file: str
    line_start: int = 1
    line_end: int = 1


class Segment(BaseModel):
    id: str
    text: str
    start_ms: int = 0
    end_ms: int = 0
    focus: FocusRef | None = None
    board_actions: list[dict[str, Any]] = Field(default_factory=list)
    subtitle_style: str = "normal"


class AudioRef(BaseModel):
    url: str
    duration_ms: int = 0
    voice: str = ""


class BoardNode(BaseModel):
    id: str
    label: str
    source: dict[str, Any] | None = None


class Board(BaseModel):
    kind: str = "architecture"
    mermaid: str = ""
    nodes: list[BoardNode] = Field(default_factory=list)


class CodeNote(BaseModel):
    file: str
    line: int
    text: str


class QuizChoice(BaseModel):
    id: str
    text: str


class QuizItemOut(BaseModel):
    id: str
    stem: str
    choices: list[QuizChoice] = Field(default_factory=list)
    answer_id: str
    explanation_md: str = ""
    evidence: list[dict[str, Any]] = Field(default_factory=list)


class StepBundle(BaseModel):
    index: int
    title: str
    duration_ms: int = 0
    timing_source: str = "estimated"
    audio: AudioRef | None = None
    segments: list[Segment] = Field(default_factory=list)
    board: Board | None = None
    code_notes: list[CodeNote] = Field(default_factory=list)
    quiz: list[QuizItemOut] = Field(default_factory=list)
    certainty_legend: dict[str, str] = Field(default_factory=dict)


class LessonBriefOut(BaseModel):
    key: str
    title: str
    layer: str = "overview"
    minutes: int = 0


class FileRef(BaseModel):
    path: str
    content_ref: str = ""
    lang: str = "text"
    line_count: int = 0


class TraceStepOut(BaseModel):
    index: int
    title: str
    certainty: str = "teaching_simulation"
    evidence: list[dict[str, Any]] = Field(default_factory=list)
    variables: list[dict[str, Any]] = Field(default_factory=list)
    note: str | None = None


class TraceOut(BaseModel):
    id: str
    steps: list[TraceStepOut] = Field(default_factory=list)
    certainty_summary: dict[str, Any] = Field(default_factory=dict)


class PlaybackBundle(BaseModel):
    course_id: str
    commit_sha: str = ""
    lesson: LessonBriefOut
    steps: list[StepBundle] = Field(default_factory=list)
    files: list[FileRef] = Field(default_factory=list)
    trace: TraceOut | None = None
    #: 为什么这一课没有配音（TTS 未配置 / 凭据错 / 网关不支持…）。
    #: 没有它，前端只能显示"本节暂无配音"，用户无法区分"我没配"和"配错了"。
    no_voice_reason: str | None = None

"""配置引导与设置相关 schema（spec §5.2 第一组接口）。"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

Protocol = Literal[
    "anthropic_messages",
    "anthropic_compatible",
    "openai_chat",
    "openai_compatible",
    "openai_responses",
    "google_generate",
    "gemini_compatible",
]

Role = Literal["planner", "writer", "critic", "vision", "quiz", "embed"]

ROLE_NAMES: tuple[str, ...] = ("planner", "writer", "critic", "vision", "quiz", "embed")


class LlmProbeRequest(BaseModel):
    provider: str = Field(description="anthropic | openai | google | custom")
    protocol: Protocol
    api_key: str = Field(min_length=1, max_length=400)
    base_url: str | None = Field(default=None, max_length=400)
    org: str | None = Field(default=None, max_length=120)
    model_id: str | None = Field(default=None, max_length=160)


class ModelCapability(BaseModel):
    text: bool = True
    vision: bool = False
    audio_in: bool = False
    audio_out: bool = False
    tools: bool = False
    json_mode: bool = False
    streaming: bool = True
    thinking: bool = False
    context_window: int = 0
    price_in: float = 0.0
    price_out: float = 0.0


class ModelItem(BaseModel):
    id: str
    display_name: str = ""
    capabilities: ModelCapability = Field(default_factory=ModelCapability)
    context_window: int = 0
    price: float = 0.0


class ProbeError(BaseModel):
    """`probe` 是测量接口：失败也是 200，但错误体形状与 §5.6 一致。"""

    code: str
    message: str
    hint: str | None = None
    retryable: bool = False


class LlmProbeResponse(BaseModel):
    ok: bool
    latency_ms: int = 0
    models: list[ModelItem] = Field(default_factory=list)
    error: ProbeError | None = None


class TtsProbeRequest(BaseModel):
    provider: Literal["doubao"] = "doubao"
    app_id: str = Field(default="", max_length=120)
    access_token: str = Field(default="", max_length=400)
    cluster: str = Field(default="volcano_tts", max_length=80)
    voice_type: str = Field(default="", max_length=160)
    text: str = Field(default="你好，这里是 RepoLearn", max_length=200)


class TtsProbeResponse(BaseModel):
    ok: bool
    latency_ms: int = 0
    sample_audio_url: str | None = None
    duration_ms: int = 0
    error: ProbeError | None = None


class TtsConfig(BaseModel):
    provider: Literal["doubao"] = "doubao"
    app_id: str = ""
    access_token: str = ""
    cluster: str = "volcano_tts"
    voice_type: str = ""


class LlmConfigIn(BaseModel):
    provider: str
    protocol: Protocol
    api_key: str = ""
    base_url: str | None = None
    org: str | None = None
    label: str = ""
    model_id: str | None = None


class RoleAssignment(BaseModel):
    planner: str = ""
    writer: str = ""
    critic: str = ""
    vision: str | None = None
    quiz: str | None = None
    embed: str | None = None


class SetupCommitRequest(BaseModel):
    llm: LlmConfigIn
    tts: TtsConfig | None = None
    roles: RoleAssignment


class SetupCommitResponse(BaseModel):
    profile_id: str
    revision: int
    warnings: list[str] = Field(default_factory=list)


class ActiveProfile(BaseModel):
    id: str
    provider: str
    protocol: str
    models: list[str] = Field(default_factory=list)


class KernelState(BaseModel):
    ok: bool
    runtime: str


class Gates(BaseModel):
    g1: str = "unknown"
    g2: str = "unknown"
    g3: str = "unknown"


class SetupStateResponse(BaseModel):
    required: bool
    next_step: int = 1
    steps_done: list[int] = Field(default_factory=list)
    active_profile: ActiveProfile | None = None
    kernel: KernelState
    gates: Gates = Field(default_factory=Gates)
    roles: dict[str, str] = Field(default_factory=dict)


class ProfileItem(BaseModel):
    id: str
    label: str
    provider: str
    protocol: str
    base_url: str | None = None
    model_count: int = 0
    api_key_last4: str = ""
    active: bool = False
    last_probe: dict[str, Any] = Field(default_factory=dict)
    created_at: str | None = None


class ProfileListResponse(BaseModel):
    items: list[ProfileItem] = Field(default_factory=list)


class ActivateResponse(BaseModel):
    active_profile_id: str
    revision: int


class RolesPatch(BaseModel):
    roles: dict[str, str] = Field(default_factory=dict)


class RevisionItem(BaseModel):
    id: str
    rev: int
    created_at: str | None = None
    author: str = "local"
    summary: str = ""
    changes: list[str] = Field(default_factory=list)


class RevisionListResponse(BaseModel):
    items: list[RevisionItem] = Field(default_factory=list)


class RevisionResponse(BaseModel):
    revision: int


class RotateSecretRequest(BaseModel):
    new_secret: str = Field(min_length=8, max_length=400)


class RotateSecretResponse(BaseModel):
    rotated: int


class DoctorCheck(BaseModel):
    name: str
    status: Literal["ok", "degraded", "fail", "unknown"]
    detail: str = ""
    hint: str | None = None


class DoctorResponse(BaseModel):
    checks: list[DoctorCheck] = Field(default_factory=list)

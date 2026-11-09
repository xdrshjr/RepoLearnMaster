"""Provider 抽象层（spec §3.7 / §3.8 / §3.5.3）。

这个文件只放**协议与数据结构**，不放任何 HTTP 细节。理由：四类适配器（Anthropic /
OpenAI Chat / OpenAI Responses / Gemini）在"要不要重试、算多少钱、怎么降级"上的
语义必须一致，而它们的 HTTP 形状完全不同。把共同语义钉在 Protocol 上，适配器就
只剩下"翻译请求/响应"这一件简单的事。
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


class LlmError(Exception):
    """模型调用的统一异常。

    `retryable` 是**给调用方的决策依据**，不是日志字段：N6 的失败策略是"该课时失败
    还是换备用模型"，而这个判断只取决于 `retryable`。把所有 provider 错误映射成
    一个布尔值，是让上层不必认识 20 种 HTTP 状态码的唯一办法。
    """

    def __init__(
        self,
        message: str,
        *,
        code: str = "PROVIDER_UNAVAILABLE",
        retryable: bool = True,
        status: int | None = None,
        retry_after_s: float | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.code = code
        self.retryable = retryable
        self.status = status
        self.retry_after_s = retry_after_s
        #: 上游响应的头部（已小写化）。限流的**真实原因**在头里而不在 body 里：
        #: `X-RateLimit-Remaining: 0` + `X-RateLimit-Reset: <epoch>` 才能回答
        #: "什么时候能重试、还剩多少额度"，而 body 只说 "rate limit exceeded"。
        #: 只放头部，不放 body 之外的任何凭据（Authorization 不会出现在响应头里）。
        self.headers = headers or {}


@dataclass(frozen=True)
class LlmConfig:
    """一次调用的连接配置。**包含明文 api_key**——只在内存里活一次调用。"""

    protocol: str
    api_key: str
    base_url: str | None = None
    org: str | None = None
    model_id: str = ""
    provider: str = ""

    def redacted(self) -> dict[str, Any]:
        return {
            "protocol": self.protocol,
            "base_url": self.base_url,
            "provider": self.provider,
            "model_id": self.model_id,
            "has_key": bool(self.api_key),
        }


@dataclass
class ModelCapabilities:
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

    def as_dict(self) -> dict[str, Any]:
        return {
            "text": self.text,
            "vision": self.vision,
            "audio_in": self.audio_in,
            "audio_out": self.audio_out,
            "tools": self.tools,
            "json_mode": self.json_mode,
            "streaming": self.streaming,
            "thinking": self.thinking,
            "context_window": self.context_window,
            "price_in": self.price_in,
            "price_out": self.price_out,
        }


@dataclass
class ModelInfo:
    id: str
    display_name: str = ""
    capabilities: ModelCapabilities = field(default_factory=ModelCapabilities)
    context_window: int = 0
    price: float = 0.0


@dataclass
class ProbeResult:
    """`ok=False` 不是异常——probe 是"测量接口"（spec §5.2 P2-1）。"""

    ok: bool
    latency_ms: int = 0
    models: list[ModelInfo] = field(default_factory=list)
    error: dict[str, Any] | None = None


@dataclass
class CompletionRequest:
    model_id: str
    messages: list[dict[str, Any]]
    system: str | None = None
    max_tokens: int = 4096
    temperature: float = 0.2
    tools: list[dict[str, Any]] = field(default_factory=list)
    json_mode: bool = False
    #: 多模态输入：`[{"type":"image","media_type":"image/png","data":"<base64>"}]`
    images: list[dict[str, str]] = field(default_factory=list)


@dataclass
class Usage:
    tokens_in: int = 0
    tokens_out: int = 0
    source: str = "reported"

    def as_dict(self) -> dict[str, Any]:
        return {"tokens_in": self.tokens_in, "tokens_out": self.tokens_out, "source": self.source}


@dataclass
class CompletionResult:
    text: str
    usage: Usage = field(default_factory=Usage)
    model_id: str = ""
    stop_reason: str = "end_turn"
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class Chunk:
    delta: str
    done: bool = False
    usage: Usage | None = None


@runtime_checkable
class LlmAdapter(Protocol):
    """四个协议的共同出口（spec §3.7.1）。"""

    protocol: str

    async def probe(self, cfg: LlmConfig) -> ProbeResult: ...

    async def list_models(self, cfg: LlmConfig) -> list[ModelInfo]: ...

    async def complete(self, cfg: LlmConfig, req: CompletionRequest) -> CompletionResult: ...

    def stream(self, cfg: LlmConfig, req: CompletionRequest) -> AsyncIterator[Chunk]: ...


# --------------------------------------------------------------------------- #
# AgentRuntime 协议（spec §3.5.3）                                              #
# --------------------------------------------------------------------------- #


@dataclass
class AgentBudget:
    max_turns: int = 16
    max_tokens: int = 12_000
    max_usd: float = 1.0
    deadline_ms: int = 120_000

    def as_kernel_payload(self) -> dict[str, Any]:
        return {
            "maxTurns": self.max_turns,
            "maxTokens": self.max_tokens,
            "maxUsd": self.max_usd,
            "deadlineMs": self.deadline_ms,
        }


@dataclass
class AgentRunRequest:
    run_id: str
    role: str
    config: LlmConfig
    system_prompt: str
    prompt: str
    tools: list[str] = field(default_factory=list)
    schema_ref: str | None = None
    budget: AgentBudget = field(default_factory=AgentBudget)
    mirror_dir: str | None = None
    job_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class AgentEvent:
    type: str
    seq: int = 0
    ts: int = 0
    data: dict[str, Any] = field(default_factory=dict)


@dataclass
class AgentRunResult:
    """一次 run 的终态。`status` 直接映射到 §3.5.3 的 A/B/C 三分支与预算超限。"""

    status: str  # completed | failed | cancelled | budget_exceeded | degraded
    result: dict[str, Any] = field(default_factory=dict)
    usage: dict[str, Any] = field(default_factory=dict)
    error: dict[str, Any] | None = None
    runtime: str = "kernel"


@runtime_checkable
class AgentRuntime(Protocol):
    name: str

    async def run(self, req: AgentRunRequest) -> tuple[list[AgentEvent], AgentRunResult]: ...

    async def cancel(self, run_id: str) -> None: ...

    async def available(self) -> bool: ...


# --------------------------------------------------------------------------- #
# TTS（spec §3.8）                                                             #
# --------------------------------------------------------------------------- #


@dataclass
class TtsConfigIn:
    provider: str = "doubao"
    app_id: str = ""
    access_token: str = ""
    cluster: str = "volcano_tts"
    voice_type: str = "zh_female_wanwanxiaohe_moon_bigtts"
    speed_ratio: float = 1.0
    emotion: str | None = None


@dataclass
class TtsResult:
    ok: bool
    audio_bytes: bytes = b""
    duration_ms: int = 0
    duration_source: str = "estimated"
    error: dict[str, Any] | None = None
    latency_ms: int = 0

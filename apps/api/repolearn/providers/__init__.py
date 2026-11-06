"""Provider 层。

对外只导出"调用者真正需要的东西"：适配器注册表、AgentRuntime 选择器、TTS、
预算守卫。适配器的内部实现不该被 services 直接看到——否则"换一个协议"就不再是
一个文件的事。
"""

from __future__ import annotations

from repolearn.providers.agent_runtime import (
    ExecCliRuntime,
    HttpKernelRuntime,
    RuntimeSelector,
    get_selector,
    refresh_state,
    runtime_report,
)
from repolearn.providers.base import (
    AgentBudget,
    AgentEvent,
    AgentRunRequest,
    AgentRunResult,
    AgentRuntime,
    Chunk,
    CompletionRequest,
    CompletionResult,
    LlmAdapter,
    LlmConfig,
    LlmError,
    ModelCapabilities,
    ModelInfo,
    ProbeResult,
    TtsConfigIn,
    TtsResult,
    Usage,
)
from repolearn.providers.budget_guard import CallGuard, JobBudget, estimate_tokens, usd_for
from repolearn.providers.registry import ROLES, Resolver, adapter_for, build_resolver
from repolearn.providers.tts.doubao import DoubaoTts

__all__ = [
    "AgentBudget",
    "AgentEvent",
    "AgentRunRequest",
    "AgentRunResult",
    "AgentRuntime",
    "CallGuard",
    "Chunk",
    "CompletionRequest",
    "CompletionResult",
    "DoubaoTts",
    "ExecCliRuntime",
    "HttpKernelRuntime",
    "JobBudget",
    "LlmAdapter",
    "LlmConfig",
    "LlmError",
    "ModelCapabilities",
    "ModelInfo",
    "ProbeResult",
    "ROLES",
    "Resolver",
    "RuntimeSelector",
    "TtsConfigIn",
    "TtsResult",
    "Usage",
    "adapter_for",
    "build_resolver",
    "estimate_tokens",
    "get_selector",
    "refresh_state",
    "runtime_report",
    "usd_for",
]

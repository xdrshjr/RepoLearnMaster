"""适配器注册表与角色解析（spec §3.7.3）。

`resolver.resolve(role) -> [ModelCandidate]` 是**主模型 + 备用链**的唯一入口。
把"哪个角色用哪个模型"从字符串判断变成一个可测试的解析器，是因为它决定了
"主模型挂了会不会自动切备用"——这条逻辑散落在节点里就没法验证。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from repolearn.core.errors import AppError
from repolearn.providers.base import LlmAdapter, LlmConfig
from repolearn.providers.llm.anthropic_adapter import AnthropicAdapter
from repolearn.providers.llm.google_adapter import GoogleAdapter
from repolearn.providers.llm.model_catalog import capabilities_for
from repolearn.providers.llm.openai_adapter import OpenAIAdapter
from repolearn.providers.llm.openai_responses_adapter import OpenAIResponsesAdapter

ANTHROPIC = AnthropicAdapter()
OPENAI = OpenAIAdapter()
OPENAI_RESPONSES = OpenAIResponsesAdapter()
GOOGLE = GoogleAdapter()

_ADAPTERS: dict[str, LlmAdapter] = {
    "anthropic_messages": ANTHROPIC,
    "anthropic_compatible": ANTHROPIC,
    "openai_chat": OPENAI,
    "openai_compatible": OPENAI,
    "openai_responses": OPENAI_RESPONSES,
    "google_generate": GOOGLE,
    "gemini_compatible": GOOGLE,
}

ROLES = ("planner", "writer", "critic", "vision", "quiz", "embed")

#: 角色 → 是否必须支持图片输入
ROLE_NEEDS_VISION = {"vision"}


def adapter_for(protocol: str) -> LlmAdapter:
    """未知协议一律按 OpenAI 兼容处理——这是行业事实标准，也是唯一"总能试一下"的选择。"""
    return _ADAPTERS.get(protocol, OPENAI)


@dataclass
class ModelCandidate:
    model_id: str
    protocol: str
    config: LlmConfig
    role: str = ""
    capabilities: dict = field(default_factory=dict)


@dataclass
class Resolver:
    """角色 → 候选模型链。

    `fallbacks` 是"主模型失败后再试"的模型 id 列表；为空时直接抛
    `NO_MODEL_FOR_ROLE`，由节点决定降级（spec §3.7.3）。
    """

    roles: dict[str, str]
    configs: dict[str, LlmConfig]
    fallbacks: dict[str, list[str]] = field(default_factory=dict)

    def resolve(self, role: str) -> list[ModelCandidate]:
        primary = (self.roles.get(role) or "").strip()
        if not primary:
            # vision 是可选角色：没有多模态模型时**不是错误**，而是跳过并记 VISION_SKIPPED
            if role in ROLE_NEEDS_VISION:
                return []
            raise AppError("NO_MODEL_FOR_ROLE", details={"role": role})
        out: list[ModelCandidate] = []
        for model_id in [primary, *self.fallbacks.get(role, [])]:
            cfg = self.configs.get(model_id)
            if cfg is None:
                continue
            # 能力/价格必须随候选一起带出去：`_Ctx.run` 用它算 USD，
            # 恒为 0 会让 `job_max_usd` 这一道成本闸门永远不可能触发，
            # `cost_ledger.usd` 也会一直是 0（成本面板变成装饰）。
            out.append(
                ModelCandidate(
                    model_id=model_id,
                    protocol=cfg.protocol,
                    config=cfg,
                    role=role,
                    capabilities=capabilities_for(cfg.provider, model_id).as_dict(),
                )
            )
        if not out:
            raise AppError("NO_MODEL_FOR_ROLE", details={"role": role})
        return out

    def primary(self, role: str) -> ModelCandidate | None:
        chain = self.resolve(role)
        return chain[0] if chain else None

    def has_role(self, role: str) -> bool:
        return bool((self.roles.get(role) or "").strip())

    def vision_available(self) -> bool:
        return self.has_role("vision")


def build_resolver(profile_roles: dict[str, str], configs: dict[str, LlmConfig]) -> Resolver:
    """从 profile 的角色分配构造 resolver。

    `profile_roles` 的形状是 `{role: model_id}`；`configs` 是 `{model_id: LlmConfig}`。
    """
    clean = {r: (profile_roles.get(r) or "") for r in ROLES}
    return Resolver(roles=clean, configs=configs)

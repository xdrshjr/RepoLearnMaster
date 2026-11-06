"""自定义协议 → 官方协议的字段覆盖表（spec §3.7.1 / P2-8）。

为什么需要这个文件：任务书要求"LLM 支持 openai/anthropic/google 以及自定义多种协议"。
自定义网关有 90% 与官方一致、10% 不一样（路径前缀、header 名、Azure 的 deployment
形态）。如果不把 10% 收敛到一张表里，就得为每个网关写一个适配器——那是无穷的。
"""

from __future__ import annotations

from dataclasses import dataclass, field

DEFAULT_BASE_URLS = {
    "anthropic": "https://api.anthropic.com",
    "openai": "https://api.openai.com/v1",
    "google": "https://generativelanguage.googleapis.com/v1beta",
}

#: 每个协议族的请求形状。`family` 决定用哪个适配器。
PROTOCOL_FAMILY = {
    "anthropic_messages": "anthropic",
    "anthropic_compatible": "anthropic",
    "openai_chat": "openai",
    "openai_compatible": "openai",
    "openai_responses": "openai_responses",
    "google_generate": "google",
    "gemini_compatible": "google",
}

PROVIDER_FAMILY = {
    "anthropic": "anthropic",
    "openai": "openai",
    "google": "google",
    "azure": "openai",
    "custom": "openai",
}


@dataclass
class CompatMap:
    """一个协议的 URL 模板与 header 约定。"""

    family: str
    chat_path: str
    models_path: str
    auth_header: str
    auth_prefix: str = "Bearer "
    extra_headers: dict[str, str] = field(default_factory=dict)
    #: Azure 风格：deployment name 取代 model 出现在 URL 里
    deployment_in_path: bool = False


MAPS: dict[str, CompatMap] = {
    "anthropic": CompatMap(
        family="anthropic",
        chat_path="/v1/messages",
        models_path="/v1/models",
        auth_header="x-api-key",
        auth_prefix="",
        extra_headers={"anthropic-version": "2023-06-01"},
    ),
    "openai": CompatMap(
        family="openai",
        chat_path="/chat/completions",
        models_path="/models",
        auth_header="Authorization",
        auth_prefix="Bearer ",
    ),
    "openai_responses": CompatMap(
        family="openai_responses",
        chat_path="/responses",
        models_path="/models",
        auth_header="Authorization",
        auth_prefix="Bearer ",
    ),
    "google": CompatMap(
        family="google",
        chat_path="/models/{model}:generateContent",
        models_path="/models",
        auth_header="x-goog-api-key",
        auth_prefix="",
    ),
}

AZURE_MAP = CompatMap(
    family="openai",
    chat_path="/openai/deployments/{model}/chat/completions?api-version=2024-10-21",
    models_path="/openai/models?api-version=2024-10-21",
    auth_header="api-key",
    auth_prefix="",
    deployment_in_path=True,
)


def compat_for(protocol: str, provider: str = "", base_url: str | None = None) -> CompatMap:
    """按 protocol → provider → base_url 的优先级选映射。"""
    family = PROTOCOL_FAMILY.get(protocol, "openai")
    if provider == "azure" or (base_url and "openai.azure.com" in base_url):
        return AZURE_MAP
    if protocol.endswith("_compatible"):
        # 自定义网关一律按"被兼容的那一家"的官方形状走，只换 base_url。
        return MAPS[family]
    return MAPS[family]


def default_base_url(protocol: str, provider: str = "") -> str:
    family = PROTOCOL_FAMILY.get(protocol, PROVIDER_FAMILY.get(provider, "openai"))
    return DEFAULT_BASE_URLS.get(provider) or DEFAULT_BASE_URLS.get(family, DEFAULT_BASE_URLS["openai"])


def join_url(base: str, path: str) -> str:
    if not base:
        return path
    return base.rstrip("/") + ("" if path.startswith("/") else "/") + path

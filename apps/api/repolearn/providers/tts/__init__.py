"""TTS 适配器注册表与工厂（`REPOLEARN_TTS_PROVIDER` 的唯一解析点）。

为什么需要工厂：今天 `run_course_job` 只用 `payload["tts"]` 构 `DoubaoTts`，而那个
payload 从来没被赋值过 → 课程**永远没有配音**。修法是把"用哪个 TTS"收进一个地方，
让 `.env` 成为唯一真源，同时保留按课程覆盖的能力。
"""

from __future__ import annotations

from typing import Any

from repolearn.core.config import settings
from repolearn.core.logging import get_logger
from repolearn.providers.base import TtsConfigIn
from repolearn.providers.tts.doubao import DoubaoTts, split_sentences, text_hash

log = get_logger("tts")

PROVIDERS = ("doubao", "qwen", "none")


def normalize_provider(name: str | None) -> str:
    """把配置值收敛到合法实现；未知值按 none 处理并记一条警告。

    未知值静默回退到 doubao 是更糟的选择：用户写了 `qwen2` 却悄悄用豆包，
    症状会变成"凭据明明填了却没声音"。
    """
    value = (name or "").strip().lower()
    if value in PROVIDERS:
        return value
    if value:
        log.warning("tts_provider_unknown", value=value, using="none")
    return "none" if value else "doubao"


def config_from_dict(payload: dict[str, Any] | None) -> TtsConfigIn | None:
    """课程 payload 里的 `tts`（显式覆盖）。字段不全就视为"没指定"。"""
    if not payload:
        return None
    allowed = {field for field in TtsConfigIn.__dataclass_fields__}
    data = {key: value for key, value in payload.items() if key in allowed}
    return TtsConfigIn(**data) if data else None


def config_from_settings(provider: str) -> TtsConfigIn | None:
    """`.env` 里的配置 → `TtsConfigIn`。

    Qwen 把 API Key / base_url / 音色塞进 TtsConfigIn 的 token / cluster / voice_type
    三个槽位：那个 dataclass 是豆包形状的，为第二个 provider 再复制一份 schema
    只会让"两个形状慢慢分叉"，而槽位语义在这里是显式写清楚的。
    """
    if provider == "doubao":
        return TtsConfigIn(
            provider="doubao",
            app_id=settings.doubao_app_id,
            access_token=settings.doubao_access_token,
            cluster=settings.doubao_cluster,
            voice_type=settings.doubao_voice_type,
        )
    if provider == "qwen":
        return TtsConfigIn(
            provider="qwen",
            app_id="",
            access_token=settings.qwen_api_key,
            cluster=settings.qwen_base_url,
            voice_type=settings.qwen_tts_voice,
        )
    return None


def make_tts(payload_tts: dict[str, Any] | None = None) -> DoubaoTts | Any | None:
    """返回一个 TTS 客户端，或 None（= 字幕模式）。

    优先级：课程 payload 显式给的 → `.env` 的 provider 配置。两条都拿不到就返回
    None，调用方据此走 `TTS_DEGRADED`（字幕推进），这是设计内的正常路径。
    """
    explicit = config_from_dict(payload_tts)
    if explicit is not None and explicit.provider in ("doubao", "qwen"):
        return _build(explicit.provider, explicit)
    provider = normalize_provider(settings.tts_provider)
    cfg = config_from_settings(provider)
    return _build(provider, cfg) if cfg is not None else None


def _build(provider: str, cfg: TtsConfigIn):
    if provider == "qwen":
        from repolearn.providers.tts.qwen import QwenTts

        return QwenTts(cfg)
    if provider == "doubao":
        return DoubaoTts(cfg)
    return None


def describe() -> dict:
    """给 doctor / `/healthz` 的脱敏视图。"""
    provider = normalize_provider(settings.tts_provider)
    cfg = config_from_settings(provider)
    configured = bool(cfg) and bool(
        cfg.access_token if provider == "qwen" else (cfg.app_id and cfg.access_token)
    )
    return {
        "provider": provider,
        "configured": configured,
        "voice": (cfg.voice_type if cfg else "") or "",
        "base_url": (cfg.cluster if provider == "qwen" and cfg else "") or "",
        "has_key": bool(cfg.access_token) if cfg else False,
        "has_app_id": bool(cfg.app_id) if cfg else False,
    }


__all__ = [
    "PROVIDERS",
    "config_from_dict",
    "config_from_settings",
    "describe",
    "make_tts",
    "normalize_provider",
    "split_sentences",
    "text_hash",
]

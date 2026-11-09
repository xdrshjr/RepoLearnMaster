"""TTS 必须真的接进生成流程（T-TTS-1..4）。

真实缺陷（2026-11-09 排查）：`run_course_job` 里只有

    tts = None
    if payload.get("tts"):
        tts = DoubaoTts(TtsConfigIn(**payload["tts"]))

而 `payload["tts"]` **从来没有被任何代码写入过**：`create_course` / `rebuild_course` 的
payload 只有 repo_url / ref / commit / language；`/setup` 提交的 TTS 只被
`bool(req.tts)` 用了一下塞进 `last_probe`。于是**不管怎么配置，课程永远没有配音**，
而页面只会说"本节无配音"，看起来像豆包配额问题。

这组用例把"配置 → 生成流程"这条线钉住：provider 解析、env 取值、payload 覆盖、
未知值不静默回退。
"""

from __future__ import annotations

import httpx
import pytest

from repolearn.core.config import settings
from repolearn.providers.tts import (
    config_from_dict,
    config_from_settings,
    describe,
    make_tts,
    normalize_provider,
)
from repolearn.providers.tts.qwen import QwenTts, audio_from_chat


def test_unknown_provider_does_not_silently_fall_back_to_doubao():
    """T-TTS-1：写了 `qwen2` 却悄悄用豆包，症状会变成"凭据填了却没声音"。"""
    assert normalize_provider("qwen2") == "none"
    assert normalize_provider("QWEN") == "qwen"
    assert normalize_provider("") == "doubao"
    assert normalize_provider(None) == "doubao"


def test_make_tts_reads_settings_when_payload_has_no_tts(monkeypatch):
    """T-TTS-2：payload 没给 tts 时，必须用 `.env` 的配置（这就是原来断掉的那一环）。"""
    monkeypatch.setattr(settings, "tts_provider", "qwen", raising=False)
    monkeypatch.setattr(settings, "qwen_api_key", "sk-test", raising=False)
    monkeypatch.setattr(settings, "qwen_base_url", "https://example.test/compatible-mode/v1", raising=False)

    client = make_tts(None)

    assert isinstance(client, QwenTts)
    assert client.configured is True
    assert client.base_url == "https://example.test/compatible-mode/v1"


def test_payload_tts_overrides_settings(monkeypatch):
    """T-TTS-3：课程级的显式配置优先于 .env。"""
    monkeypatch.setattr(settings, "tts_provider", "qwen", raising=False)

    client = make_tts(
        {
            "provider": "doubao",
            "app_id": "1234567",
            "access_token": "tok",
            "cluster": "volcano_tts",
            "voice_type": "zh_female_x",
        }
    )

    assert client is not None
    assert client.provider == "doubao"
    assert client.configured is True


def test_provider_none_returns_no_client():
    """T-TTS-4：`REPOLEARN_TTS_PROVIDER=none` 时明确返回 None（= 字幕模式）。"""
    import repolearn.providers.tts as tts_module

    original = settings.tts_provider
    try:
        settings.tts_provider = "none"
        assert make_tts(None) is None
        assert describe()["provider"] == "none"
        assert describe()["configured"] is False
    finally:
        settings.tts_provider = original
    assert tts_module.PROVIDERS == ("doubao", "qwen", "none")


def test_config_from_dict_ignores_unknown_keys():
    cfg = config_from_dict({"provider": "qwen", "access_token": "k", "junk": 1})
    assert cfg is not None
    assert cfg.provider == "qwen"
    assert not hasattr(cfg, "junk")
    assert config_from_dict(None) is None
    assert config_from_dict({}) is None


def test_config_from_settings_reuses_slots():
    """qwen 复用 app_id/access_token/cluster 三个槽位，映射关系必须写死在这里。"""
    original = (settings.qwen_api_key, settings.qwen_base_url, settings.qwen_tts_voice)
    try:
        settings.qwen_api_key = "sk-abc"
        settings.qwen_base_url = "https://x/compatible-mode/v1"
        settings.qwen_tts_voice = "Cherry"
        cfg = config_from_settings("qwen")
        assert cfg is not None
        assert cfg.access_token == "sk-abc"
        assert cfg.cluster == "https://x/compatible-mode/v1"
        assert cfg.voice_type == "Cherry"
    finally:
        settings.qwen_api_key, settings.qwen_base_url, settings.qwen_tts_voice = original


def _audio_response(b64: str) -> httpx.Response:
    return httpx.Response(
        200,
        json={"choices": [{"message": {"audio": {"data": b64}}}]},
        request=httpx.Request("POST", "http://x/chat/completions"),
    )


def test_audio_from_chat_extracts_base64():
    assert audio_from_chat({"choices": [{"message": {"audio": {"data": "aGk="}}}]}) == b"hi"
    # 没有 audio 字段时必须返回 None —— 假装"成功但空音频"是最坏的一种谎
    assert audio_from_chat({"choices": [{"message": {}}]}) is None
    assert audio_from_chat({}) is None


@pytest.mark.asyncio
async def test_qwen_returns_tts_result_not_exception_on_failure(monkeypatch):
    """合成失败必须是 `TtsResult(ok=False)`（降级为字幕），不是异常。"""
    monkeypatch.setattr(settings, "qwen_api_key", "sk-test", raising=False)
    client = QwenTts()
    calls: list[str] = []

    class _Failing:
        def __init__(self, *args, **kwargs) -> None:  # noqa: ANN002, ANN003
            pass

        async def post(self, url, **kwargs):  # noqa: ANN001, ANN003, ANN201
            calls.append(url)
            return httpx.Response(
                500,
                json={"code": "InternalError", "message": "Unexpected error: UNKNOWN"},
                request=httpx.Request("POST", url),
            )

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):  # noqa: ANN002
            return None

    import repolearn.providers.tts.qwen as qwen_module

    monkeypatch.setattr(qwen_module, "new_client", lambda **_kw: _Failing())

    result = await client.synthesize("你好")

    assert result.ok is False
    assert result.error is not None
    assert "Unexpected error" in result.error["message"] or "500" in result.error["message"]
    # 两条候选路径都要试过，错误信息才不会误导成"模型不可用"
    assert len(calls) == 2


@pytest.mark.asyncio
async def test_qwen_success_path_returns_audio_bytes(monkeypatch):
    monkeypatch.setattr(settings, "qwen_api_key", "sk-test", raising=False)
    client = QwenTts()

    class _Ok:
        def __init__(self, *args, **kwargs) -> None:  # noqa: ANN002, ANN003
            pass

        async def post(self, url, **kwargs):  # noqa: ANN001, ANN003, ANN201
            return httpx.Response(
                200,
                headers={"content-type": "audio/mpeg"},
                content=b"ID3fakeaudio" * 20,
                request=httpx.Request("POST", url),
            )

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):  # noqa: ANN002
            return None

    import repolearn.providers.tts.qwen as qwen_module

    monkeypatch.setattr(qwen_module, "new_client", lambda **_kw: _Ok())

    result = await client.synthesize("你好")

    assert result.ok is True
    assert result.audio_bytes.startswith(b"ID3")
    assert result.duration_ms > 0

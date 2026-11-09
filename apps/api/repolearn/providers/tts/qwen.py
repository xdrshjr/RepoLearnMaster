"""阿里百炼（DashScope）兼容模式 TTS 适配器（spec §3.8 的第二个 provider）。

为什么按"OpenAI 兼容的 `/audio/speech`"写：百炼兼容模式把语音合成也做成了这个
形状（`POST {base}/audio/speech`，`{model, input, voice, response_format}`，
响应体是**音频字节**）。同时保留对 `chat/completions` + `modalities:["audio"]`
的解析：qwen-audio 系列走的是那条路，响应里音频在
`choices[0].message.audio.data`（base64）。

失败一律降级为字幕：`TtsResult(ok=False, error=…)` 是**正常路径**，不是异常——
没有配音也必须能完课（与 `Doubao` 同一约定）。
"""

from __future__ import annotations

import base64
import json
import time

import httpx

from repolearn.core.config import settings
from repolearn.core.logging import get_logger
from repolearn.providers.base import LlmError, TtsConfigIn, TtsResult
from repolearn.providers.http import new_client
from repolearn.providers.tts.doubao import mp3_duration_ms

log = get_logger("tts.qwen")

AUDIO_CTYPES = ("audio/", "application/octet-stream", "binary/octet-stream")


def _is_audio(resp: httpx.Response) -> bool:
    ctype = (resp.headers.get("content-type") or "").lower()
    return any(ctype.startswith(prefix) or prefix in ctype for prefix in AUDIO_CTYPES)


def audio_from_chat(body: dict) -> bytes | None:
    """从 `chat/completions` 的音频模态响应里取音频。

    形状：`choices[0].message.audio.data`（base64）。取不到就返回 None——
    **不要**把"没有音频字段"当成"成功但空音频"，那会让上层以为配音成功。
    """
    for choice in body.get("choices") or []:
        message = (choice or {}).get("message") or {}
        audio = message.get("audio") or {}
        data = audio.get("data")
        if isinstance(data, str) and data:
            try:
                return base64.b64decode(data)
            except Exception:  # noqa: BLE001 - 坏数据当成"没有音频"
                return None
    return None


class QwenTts:
    """阿里百炼兼容模式 TTS。"""

    provider = "qwen"

    def __init__(self, cfg: TtsConfigIn | None = None) -> None:
        self.cfg = cfg or TtsConfigIn(
            provider="qwen",
            app_id="",
            access_token=settings.qwen_api_key,
            cluster=settings.qwen_base_url,
            voice_type=settings.qwen_tts_voice,
        )
        # `TtsConfigIn` 是为豆包设计的（app_id + access_token + cluster + voice）。
        # Qwen 复用它的三个槽位，避免为了一个 provider 再改一次 schema：
        #   access_token → API Key，cluster → base_url，voice_type → 音色。

    @property
    def base_url(self) -> str:
        return (self.cfg.cluster or settings.qwen_base_url).rstrip("/")

    @property
    def configured(self) -> bool:
        return bool(self.cfg.access_token and self.base_url)

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.cfg.access_token}", "Content-Type": "application/json"}

    async def synthesize(self, text: str) -> TtsResult:
        started = time.perf_counter()
        if not self.configured:
            return TtsResult(
                ok=False,
                error={
                    "code": "TTS_NOT_CONFIGURED",
                    "message": "未配置百炼 TTS 的 API Key",
                    "hint": "在 .env 里填 REPOLEARN_QWEN_API_KEY，或把 REPOLEARN_TTS_PROVIDER 设为 none",
                    "retryable": False,
                },
                latency_ms=0,
            )
        try:
            audio = await self._synth_once(text)
        except LlmError as exc:
            log.warning("qwen_tts_failed", code=exc.code, message=exc.message[:200])
            return TtsResult(
                ok=False,
                error={"code": exc.code, "message": exc.message, "retryable": exc.retryable},
                latency_ms=int((time.perf_counter() - started) * 1000),
            )
        duration, source = mp3_duration_ms(audio)
        return TtsResult(
            ok=True,
            audio_bytes=audio,
            duration_ms=duration,
            duration_source=source,
            latency_ms=int((time.perf_counter() - started) * 1000),
        )

    async def _synth_once(self, text: str) -> bytes:
        """先试 OpenAI 兼容的 `/audio/speech`，再退回 `chat/completions` 音频模态。

        两条路都是百炼真实存在过的形态，而"哪条对你这个网关可用"取决于开通的模型；
        顺序固定（便宜的 stateless 接口优先），失败信息两条都带上——只报第一条会
        让人以为模型本身不可用。
        """
        payload = {
            "model": settings.qwen_tts_model,
            "input": text,
            "voice": self.cfg.voice_type or settings.qwen_tts_voice,
            "response_format": settings.qwen_tts_format,
        }
        errors: list[str] = []
        async with new_client(timeout_read=90.0) as client:
            speech_url = f"{self.base_url}/audio/speech"
            try:
                resp = await client.post(speech_url, json=payload, headers=self._headers())
            except httpx.HTTPError as exc:
                errors.append(f"{speech_url}: {exc.__class__.__name__}")
            else:
                if resp.status_code < 400:
                    if _is_audio(resp):
                        return resp.content
                    base64_audio = audio_from_chat(_safe_json(resp))
                    if base64_audio:
                        return base64_audio
                    errors.append(f"{speech_url}: 200 但不是音频（{resp.headers.get('content-type')}）")
                else:
                    errors.append(f"{speech_url}: {resp.status_code} {resp.text[:200]}")

            chat_url = f"{self.base_url}/chat/completions"
            chat_payload = {
                "model": settings.qwen_tts_model,
                "messages": [{"role": "user", "content": text}],
                "modalities": ["text", "audio"],
                "audio": {"voice": payload["voice"], "format": settings.qwen_tts_format},
            }
            try:
                resp = await client.post(chat_url, json=chat_payload, headers=self._headers())
            except httpx.HTTPError as exc:
                errors.append(f"{chat_url}: {exc.__class__.__name__}")
            else:
                if resp.status_code < 400:
                    base64_audio = audio_from_chat(_safe_json(resp))
                    if base64_audio:
                        return base64_audio
                    errors.append(f"{chat_url}: 200 但没有 audio 字段（{resp.text[:160]}）")
                else:
                    errors.append(f"{chat_url}: {resp.status_code} {resp.text[:200]}")

        raise LlmError(
            "百炼 TTS 合成失败：" + " | ".join(errors[:2]),
            code="PROVIDER_UNAVAILABLE",
            retryable=True,
        )

    async def probe(self, text: str = "你好，这里是 RepoLearn") -> TtsResult:
        return await self.synthesize(text)


def _safe_json(resp: httpx.Response) -> dict:
    try:
        data = json.loads(resp.text)
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


__all__ = ["QwenTts", "audio_from_chat"]

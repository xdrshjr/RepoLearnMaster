"""豆包（火山引擎）TTS 适配器（spec §3.8）。

设计取舍：
* **默认走 HTTP 一次性合成**。WS 流式只在"边生成边播"时有意义，而 MVP 的播放器是
  "整段音频 + 时间轴"，HTTP 的错误处理简单得多。
* **长文本按句切分并发 2 路**。单次请求超过 ~800 字时，火山会截断或超时；切分后
  拼接比"祈祷一次成功"可靠。
* **失败降级为字幕**。这是硬要求：没有音频服务也必须能完课。因此 `TtsResult.ok=False`
  是一条正常路径，不是异常。
* **时长估算**：`mutagen` 是可选依赖，缺失时按 24kbps 恒定码率近似并标
  `duration_source="estimated"`（时间轴精度会下降，但不至于没有时间轴）。
"""

from __future__ import annotations

import base64
import json
import time

from repolearn.core.config import settings
from repolearn.providers.base import LlmError, TtsConfigIn, TtsResult
from repolearn.providers.http import backoff_delay, new_client, request_with_retry

DOUBAO_HTTP_URL = "https://openspeech.bytedance.com/api/v1/tts"
MAX_CHARS_PER_REQUEST = 800


def split_sentences(text: str, limit: int = MAX_CHARS_PER_REQUEST) -> list[str]:
    """按中文句末标点切分，并保证每段不超过 limit。"""
    text = (text or "").strip()
    if not text:
        return []
    if len(text) <= limit:
        return [text]
    pieces: list[str] = []
    buf = ""
    for ch in text:
        buf += ch
        if ch in "。！？!?；;\n" and len(buf) >= limit // 2:
            pieces.append(buf)
            buf = ""
        elif len(buf) >= limit:
            pieces.append(buf)
            buf = ""
    if buf:
        pieces.append(buf)
    # 二次合并：避免切出大量 3 个字的碎片
    merged: list[str] = []
    for p in pieces:
        if merged and len(merged[-1]) + len(p) <= limit:
            merged[-1] += p
        else:
            merged.append(p)
    return merged


def estimate_duration_ms(audio_bytes: int, bitrate_bps: int = 24_000) -> int:
    """按码率估算时长（`duration_source="estimated"`）。"""
    if audio_bytes <= 0:
        return 0
    return int(audio_bytes * 8 / bitrate_bps * 1000)


def mp3_duration_ms(audio_bytes: bytes) -> tuple[int, str]:
    """优先用 mutagen 精确解析；缺失或失败时退回估算。"""
    try:
        import io as _io

        from mutagen.mp3 import MP3  # type: ignore[import-not-found]

        info = MP3(_io.BytesIO(audio_bytes))
        return int(info.info.length * 1000), "exact"
    except Exception:  # noqa: BLE001 - 缺包/格式异常都退回估算
        return estimate_duration_ms(len(audio_bytes)), "estimated"


class DoubaoTts:
    provider = "doubao"

    def __init__(self, cfg: TtsConfigIn | None = None) -> None:
        self.cfg = cfg or TtsConfigIn(
            app_id=settings.doubao_app_id,
            access_token=settings.doubao_access_token,
            cluster=settings.doubao_cluster,
            voice_type=settings.doubao_voice_type,
        )

    @property
    def configured(self) -> bool:
        return bool(self.cfg.app_id and self.cfg.access_token)

    def _payload(self, text: str) -> dict:
        return {
            "app": {
                "appid": self.cfg.app_id,
                "token": self.cfg.access_token,
                "cluster": self.cfg.cluster,
            },
            "user": {"uid": "repolearn"},
            "audio": {
                "voice_type": self.cfg.voice_type,
                "encoding": "mp3",
                "speed_ratio": self.cfg.speed_ratio,
                "volume_ratio": 1.0,
                "pitch_ratio": 1.0,
                **({"emotion": self.cfg.emotion} if self.cfg.emotion else {}),
            },
            "request": {
                "reqid": f"repolearn-{int(time.time() * 1000)}",
                "text": text,
                "text_type": "plain",
                "operation": "query",
                "with_frontend": 1,
                "frontend_type": "unitTson",
            },
        }

    async def synthesize(self, text: str) -> TtsResult:
        started = time.perf_counter()
        if not self.configured:
            return TtsResult(
                ok=False,
                error={
                    "code": "TTS_NOT_CONFIGURED",
                    "message": "未配置豆包 TTS 的 app_id / access_token",
                    "hint": "打开 /setup 第三步填写火山引擎语音服务的 appid 与 access_token，或跳过音频",
                    "retryable": False,
                },
                latency_ms=int((time.perf_counter() - started) * 1000),
            )
        try:
            audio = await self._synth_once(text)
        except LlmError as exc:
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
        headers = {"Authorization": f"Bearer;{self.cfg.access_token}", "Content-Type": "application/json"}
        async with new_client(timeout_read=60.0) as client:
            resp = await request_with_retry(
                client, "POST", DOUBAO_HTTP_URL, json=self._payload(text), headers=headers, attempts=3
            )
            data = resp.json()
        if not isinstance(data, dict):
            raise LlmError("豆包返回了非 JSON 响应", code="PROVIDER_UNAVAILABLE", retryable=True)
        if data.get("code") not in (0, 3000, "0"):
            raise LlmError(
                f"豆包 TTS 返回 {data.get('code')}: {data.get('message', '')}",
                code="PROVIDER_UNAVAILABLE",
                retryable=int(data.get("code", 0) or 0) >= 3000,
            )
        raw = data.get("data")
        if not raw:
            raise LlmError("豆包 TTS 未返回音频数据", code="PROVIDER_UNAVAILABLE", retryable=True)
        try:
            return base64.b64decode(raw)
        except Exception as exc:  # noqa: BLE001
            raise LlmError(f"音频数据解码失败：{exc}", code="PROVIDER_UNAVAILABLE", retryable=False) from exc

    async def probe(self, text: str = "你好，这里是 RepoLearn") -> TtsResult:
        return await self.synthesize(text)


async def synthesize_segments(texts: list[str], cfg: TtsConfigIn | None = None) -> list[TtsResult]:
    """逐段合成；单段失败不影响其他段（降级为字幕）。"""
    client = DoubaoTts(cfg)
    results: list[TtsResult] = []
    for text in texts:
        results.append(await client.synthesize(text))
    return results


def text_hash(provider: str, voice: str, speed: float, text: str) -> str:
    """缓存键（spec §3.8）：同一句话在 10 个课时里只合成一次。"""
    import hashlib

    raw = f"{provider}|{voice}|{speed:.2f}|{text}".encode()
    return hashlib.sha256(raw).hexdigest()


def payload_preview(cfg: TtsConfigIn) -> dict:
    """给 Doctor 面板的脱敏视图。"""
    return {
        "provider": cfg.provider,
        "app_id": cfg.app_id[:4] + "***" if cfg.app_id else "",
        "has_token": bool(cfg.access_token),
        "cluster": cfg.cluster,
        "voice_type": cfg.voice_type,
    }


__all__ = [
    "DoubaoTts",
    "TtsConfigIn",
    "estimate_duration_ms",
    "mp3_duration_ms",
    "payload_preview",
    "split_sentences",
    "synthesize_segments",
    "text_hash",
    "backoff_delay",
    "json",
]

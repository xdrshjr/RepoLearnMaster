"""Google Gemini 适配器（spec §3.7.1）。

差异点：`generateContent` 的 model 在**路径里**、图片走 `inline_data`、
system 是 `systemInstruction`、安全设置在教学场景要显式放宽（否则代码里的
"如何绕过鉴权"一类文本会被误伤成不安全内容而整段拒答）。
"""

from __future__ import annotations

from collections.abc import AsyncIterator

from repolearn.providers.base import (
    Chunk,
    CompletionRequest,
    CompletionResult,
    LlmConfig,
    LlmError,
    ModelInfo,
    ProbeResult,
    Usage,
)
from repolearn.providers.compat_map import compat_for, default_base_url, join_url
from repolearn.providers.http import new_client, request_with_retry
from repolearn.providers.llm import model_catalog

#: 教学场景的安全阈值。BLOCK_ONLY_HIGH 而不是默认的 BLOCK_MEDIUM_AND_ABOVE：
#: 讲解漏洞/鉴权代码时默认阈值会整段拒答，这不是"安全"，是"不可用"。
SAFETY_SETTINGS = [
    {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_ONLY_HIGH"},
    {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_ONLY_HIGH"},
    {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_ONLY_HIGH"},
    {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_ONLY_HIGH"},
]


class GoogleAdapter:
    protocol = "google_generate"
    provider = "google"

    def _base(self, cfg: LlmConfig) -> str:
        return cfg.base_url or default_base_url("google_generate", "google")

    def _headers(self, cfg: LlmConfig) -> dict[str, str]:
        return {"content-type": "application/json", "x-goog-api-key": cfg.api_key}

    def _body(self, cfg: LlmConfig, req: CompletionRequest) -> dict:
        parts: list[dict] = [{"text": "\n".join(str(m.get("content", "")) for m in req.messages)}]
        for img in req.images:
            parts.append(
                {"inline_data": {"mime_type": img.get("media_type", "image/png"), "data": img["data"]}}
            )
        body: dict = {
            "contents": [{"role": "user", "parts": parts}],
            "generationConfig": {
                "maxOutputTokens": max(1, min(req.max_tokens, 65_000)),
                "temperature": req.temperature,
            },
            "safetySettings": SAFETY_SETTINGS,
        }
        if req.system:
            body["systemInstruction"] = {"parts": [{"text": req.system}]}
        if req.json_mode:
            body["generationConfig"]["responseMimeType"] = "application/json"
        if req.tools:
            body["tools"] = [{"functionDeclarations": req.tools}]
        return body

    async def probe(self, cfg: LlmConfig) -> ProbeResult:
        import time

        started = time.perf_counter()
        try:
            models = await self.list_models(cfg)
            return ProbeResult(ok=True, latency_ms=int((time.perf_counter() - started) * 1000), models=models)
        except LlmError as exc:
            return ProbeResult(
                ok=False,
                latency_ms=int((time.perf_counter() - started) * 1000),
                error={
                    "code": exc.code,
                    "message": exc.message,
                    "hint": "确认 API Key 来自 Google AI Studio，且该 Key 已启用 Generative Language API",
                    "retryable": exc.retryable,
                },
            )

    async def list_models(self, cfg: LlmConfig) -> list[ModelInfo]:
        cmap = compat_for(cfg.protocol)
        url = join_url(self._base(cfg), cmap.models_path)
        async with new_client(timeout_read=30.0) as client:
            resp = await request_with_retry(
                client, "GET", url, headers=self._headers(cfg), params={"pageSize": 50}, attempts=2
            )
            data = resp.json()
        models: list[ModelInfo] = []
        for item in (data.get("models") or []) if isinstance(data, dict) else []:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name", "")).removeprefix("models/")
            if not name:
                continue
            if item.get("supportedGenerationMethods") and "generateContent" not in item["supportedGenerationMethods"]:
                continue
            models.append(ModelInfo(id=name, display_name=str(item.get("displayName") or name)))
        if not models:
            models = model_catalog.enrich("google", [ModelInfo(id=k[1]) for k in model_catalog.CATALOG if k[0] == "google"])
        return model_catalog.enrich("google", models)

    async def complete(self, cfg: LlmConfig, req: CompletionRequest) -> CompletionResult:
        cmap = compat_for(cfg.protocol)
        model_id = req.model_id or cfg.model_id
        path = cmap.chat_path.replace("{model}", model_id)
        url = join_url(self._base(cfg), path)
        async with new_client() as client:
            resp = await request_with_retry(
                client, "POST", url, json=self._body(cfg, req), headers=self._headers(cfg), attempts=3
            )
            data = resp.json()
        candidates = data.get("candidates") or []
        text_parts: list[str] = []
        if candidates:
            for part in (candidates[0].get("content") or {}).get("parts", []) or []:
                if isinstance(part, dict) and "text" in part:
                    text_parts.append(str(part["text"]))
        usage = data.get("usageMetadata") or {}
        return CompletionResult(
            text="".join(text_parts),
            usage=Usage(
                tokens_in=int(usage.get("promptTokenCount", 0) or 0),
                tokens_out=int(usage.get("candidatesTokenCount", 0) or 0),
            ),
            model_id=model_id,
            stop_reason=str(candidates[0].get("finishReason", "STOP") if candidates else "STOP"),
            raw=data if isinstance(data, dict) else {},
        )

    async def stream(self, cfg: LlmConfig, req: CompletionRequest) -> AsyncIterator[Chunk]:
        result = await self.complete(cfg, req)
        yield Chunk(delta=result.text, done=True, usage=result.usage)

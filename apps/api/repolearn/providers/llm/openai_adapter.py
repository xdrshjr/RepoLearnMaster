"""OpenAI Chat Completions 适配器（spec §3.7.1）。同时服务 Azure 与各类兼容网关。"""

from __future__ import annotations

import json
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


class OpenAIAdapter:
    protocol = "openai_chat"
    provider = "openai"

    def _base(self, cfg: LlmConfig) -> str:
        return cfg.base_url or default_base_url("openai_chat", "openai")

    def _headers(self, cfg: LlmConfig) -> dict[str, str]:
        cmap = compat_for(cfg.protocol, "openai", cfg.base_url)
        headers = {
            "content-type": "application/json",
            cmap.auth_header: f"{cmap.auth_prefix}{cfg.api_key}",
            **cmap.extra_headers,
        }
        if cfg.org and not cmap.deployment_in_path:
            headers["OpenAI-Organization"] = cfg.org
        return headers

    def _body(self, cfg: LlmConfig, req: CompletionRequest, *, stream: bool = False) -> dict:
        messages: list[dict] = []
        if req.system:
            messages.append({"role": "system", "content": req.system})
        for m in req.messages:
            messages.append({"role": m.get("role", "user"), "content": m.get("content", "")})
        if req.images:
            # 多模态走 content 数组的 image_url（data URI 是最通用的形态）
            last_user = None
            for i in range(len(messages) - 1, -1, -1):
                if messages[i]["role"] == "user":
                    last_user = i
                    break
            if last_user is not None:
                parts: list[dict] = [{"type": "text", "text": str(messages[last_user]["content"])}]
                for img in req.images:
                    parts.append(
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:{img.get('media_type', 'image/png')};base64,{img['data']}"},
                        }
                    )
                messages[last_user]["content"] = parts
        body: dict = {
            "model": req.model_id or cfg.model_id,
            "messages": messages,
            "max_tokens": max(1, min(req.max_tokens, 64_000)),
            "temperature": req.temperature,
        }
        if stream:
            body["stream"] = True
            body["stream_options"] = {"include_usage": True}
        if req.tools:
            body["tools"] = [{"type": "function", "function": t} for t in req.tools]
        if req.json_mode:
            body["response_format"] = {"type": "json_object"}
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
                    "hint": "检查 API Key 与 base_url；OpenAI 兼容网关通常需要以 /v1 结尾",
                    "retryable": exc.retryable,
                },
            )

    async def list_models(self, cfg: LlmConfig) -> list[ModelInfo]:
        cmap = compat_for(cfg.protocol, "openai", cfg.base_url)
        url = join_url(self._base(cfg), cmap.models_path)
        async with new_client(timeout_read=30.0) as client:
            resp = await request_with_retry(client, "GET", url, headers=self._headers(cfg), attempts=2)
            data = resp.json()
        raw = data.get("data") if isinstance(data, dict) else None
        models: list[ModelInfo] = []
        for item in raw or []:
            mid = item.get("id") if isinstance(item, dict) else None
            if mid:
                models.append(ModelInfo(id=str(mid), display_name=str(item.get("display_name") or mid)))
        if not models:
            models = model_catalog.enrich("openai", [ModelInfo(id=k[1]) for k in model_catalog.CATALOG if k[0] == "openai"])
        return model_catalog.enrich("openai", models)

    async def complete(self, cfg: LlmConfig, req: CompletionRequest) -> CompletionResult:
        cmap = compat_for(cfg.protocol, "openai", cfg.base_url)
        path = cmap.chat_path.replace("{model}", req.model_id or cfg.model_id)
        url = join_url(self._base(cfg), path)
        async with new_client() as client:
            resp = await request_with_retry(
                client, "POST", url, json=self._body(cfg, req), headers=self._headers(cfg), attempts=3
            )
            data = resp.json()
        choices = data.get("choices") or []
        text = ""
        if choices:
            msg = choices[0].get("message") or {}
            text = str(msg.get("content") or "")
        usage = data.get("usage") or {}
        return CompletionResult(
            text=text,
            usage=Usage(
                tokens_in=int(usage.get("prompt_tokens", 0) or 0),
                tokens_out=int(usage.get("completion_tokens", 0) or 0),
            ),
            model_id=str(data.get("model", req.model_id)),
            stop_reason=str((choices[0].get("finish_reason") if choices else "stop") or "stop"),
            raw=data if isinstance(data, dict) else {},
        )

    async def stream(self, cfg: LlmConfig, req: CompletionRequest) -> AsyncIterator[Chunk]:
        cmap = compat_for(cfg.protocol, "openai", cfg.base_url)
        path = cmap.chat_path.replace("{model}", req.model_id or cfg.model_id)
        url = join_url(self._base(cfg), path)
        async with new_client(timeout_read=180.0) as client:
            async with client.stream(
                "POST", url, json=self._body(cfg, req, stream=True), headers=self._headers(cfg)
            ) as resp:
                if resp.status_code >= 400:
                    body = await resp.aread()
                    from repolearn.providers.http import classify_status

                    raise classify_status(resp.status_code, body.decode("utf-8", "ignore"))
                usage: Usage | None = None
                async for line in resp.aiter_lines():
                    if not line or not line.startswith("data:"):
                        continue
                    payload = line[5:].strip()
                    if payload == "[DONE]":
                        yield Chunk(delta="", done=True, usage=usage)
                        return
                    try:
                        obj = json.loads(payload)
                    except json.JSONDecodeError:
                        continue
                    if obj.get("usage"):
                        usage = Usage(
                            tokens_in=int(obj["usage"].get("prompt_tokens", 0) or 0),
                            tokens_out=int(obj["usage"].get("completion_tokens", 0) or 0),
                        )
                    for choice in obj.get("choices") or []:
                        delta = (choice.get("delta") or {}).get("content")
                        if delta:
                            yield Chunk(delta=str(delta))
                yield Chunk(delta="", done=True, usage=usage)

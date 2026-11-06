"""Anthropic Messages 适配器（spec §3.7.1）。

三个与其他协议不同的地方，也是这个文件存在的理由：
1. `system` 是**顶层字段**，不在 messages 里；
2. `max_tokens` **必填**（缺少就直接 400）；
3. 图片走 `image` block，`source` 可以是 base64 或 url。
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


class AnthropicAdapter:
    protocol = "anthropic_messages"
    provider = "anthropic"

    def _base(self, cfg: LlmConfig) -> str:
        return cfg.base_url or default_base_url("anthropic_messages", "anthropic")

    def _headers(self, cfg: LlmConfig) -> dict[str, str]:
        cmap = compat_for(cfg.protocol, "anthropic", cfg.base_url)
        h = {
            "content-type": "application/json",
            cmap.auth_header: f"{cmap.auth_prefix}{cfg.api_key}",
            **cmap.extra_headers,
        }
        if cfg.org:
            h["anthropic-beta"] = cfg.org
        return h

    def _body(self, cfg: LlmConfig, req: CompletionRequest) -> dict:
        content: list[dict] = []
        for img in req.images:
            content.append(
                {
                    "type": "image",
                    "source": {"type": "base64", "media_type": img.get("media_type", "image/png"), "data": img["data"]},
                }
            )
        messages = []
        for m in req.messages:
            text = m.get("content", "")
            if m.get("role") == "user" and content:
                messages.append({"role": "user", "content": [*content, {"type": "text", "text": text}]})
            else:
                messages.append({"role": m.get("role", "user"), "content": text})
        body: dict = {
            "model": req.model_id or cfg.model_id,
            "max_tokens": max(1, min(req.max_tokens, 64_000)),
            "messages": messages,
            "temperature": req.temperature,
        }
        if req.system:
            body["system"] = req.system
        if req.tools:
            body["tools"] = [
                {
                    "name": t.get("name", "tool"),
                    "description": t.get("description", ""),
                    "input_schema": t.get("parameters") or {"type": "object", "properties": {}},
                }
                for t in req.tools
            ]
        return body

    async def probe(self, cfg: LlmConfig) -> ProbeResult:
        import time

        started = time.perf_counter()
        try:
            models = await self.list_models(cfg)
            latency = int((time.perf_counter() - started) * 1000)
            return ProbeResult(ok=True, latency_ms=latency, models=models)
        except LlmError as exc:
            latency = int((time.perf_counter() - started) * 1000)
            return ProbeResult(
                ok=False,
                latency_ms=latency,
                error={
                    "code": exc.code,
                    "message": exc.message,
                    "hint": "检查 API Key 是否正确、base_url 是否指向 Anthropic 网关；企业网络下可能需要配置代理",
                    "retryable": exc.retryable,
                },
            )

    async def list_models(self, cfg: LlmConfig) -> list[ModelInfo]:
        cmap = compat_for(cfg.protocol, "anthropic", cfg.base_url)
        url = join_url(self._base(cfg), cmap.models_path)
        async with new_client(timeout_read=30.0) as client:
            resp = await request_with_retry(client, "GET", url, headers=self._headers(cfg), attempts=2)
            data = resp.json()
        raw = data.get("data") if isinstance(data, dict) else None
        models: list[ModelInfo] = []
        for item in raw or []:
            mid = item.get("id") if isinstance(item, dict) else None
            if not mid:
                continue
            models.append(model_catalog.enrich("anthropic", [ModelInfo(id=mid, display_name=item.get("display_name", mid) or mid)])[0])
        if not models:
            # provider 没有 /models（某些兼容网关）时，退回目录里的已知型号，
            # 让向导 S2 至少能让人选一个模型，而不是空白页。
            models = [ModelInfo(id=k[1]) for k in model_catalog.CATALOG if k[0] == "anthropic"]
            models = model_catalog.enrich("anthropic", models)
        return models

    async def complete(self, cfg: LlmConfig, req: CompletionRequest) -> CompletionResult:
        cmap = compat_for(cfg.protocol, "anthropic", cfg.base_url)
        url = join_url(self._base(cfg), cmap.chat_path)
        async with new_client() as client:
            resp = await request_with_retry(
                client, "POST", url, json=self._body(cfg, req), headers=self._headers(cfg), attempts=3
            )
            data = resp.json()
        text_parts: list[str] = []
        for block in data.get("content", []) or []:
            if isinstance(block, dict) and block.get("type") == "text":
                text_parts.append(str(block.get("text", "")))
        usage = data.get("usage") or {}
        return CompletionResult(
            text="".join(text_parts),
            usage=Usage(
                tokens_in=int(usage.get("input_tokens", 0) or 0),
                tokens_out=int(usage.get("output_tokens", 0) or 0),
            ),
            model_id=str(data.get("model", req.model_id)),
            stop_reason=str(data.get("stop_reason", "end_turn")),
            raw=data if isinstance(data, dict) else {},
        )

    async def stream(self, cfg: LlmConfig, req: CompletionRequest) -> AsyncIterator[Chunk]:
        # 流式只用于"行内提问"与"设置页试听"这类需要即时反馈的场景；
        # 生成课程走 complete（结构化产出必须完整才可用）。
        result = await self.complete(cfg, req)
        yield Chunk(delta=result.text, done=True, usage=result.usage)

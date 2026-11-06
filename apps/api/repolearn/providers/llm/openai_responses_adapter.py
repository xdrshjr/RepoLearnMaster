"""OpenAI Responses API 适配器（spec §3.7.1 / P2 保留项）。

为什么不砍掉它：Responses API 的工具调用与流事件形状与 Chat Completions 不同，
砍掉会在主机型升级时被动。这里实现最小可用面（输入/输出/用量），并把
工具调用形状差异显式标出——宁可少支持，也不静默错。
"""

from __future__ import annotations

from collections.abc import AsyncIterator

from repolearn.providers.base import (
    Chunk,
    CompletionRequest,
    CompletionResult,
    LlmConfig,
    ModelInfo,
    ProbeResult,
    Usage,
)
from repolearn.providers.compat_map import compat_for, default_base_url, join_url
from repolearn.providers.http import new_client, request_with_retry
from repolearn.providers.llm.openai_adapter import OpenAIAdapter


class OpenAIResponsesAdapter:
    protocol = "openai_responses"
    provider = "openai"

    def _base(self, cfg: LlmConfig) -> str:
        # Responses API 与 Chat 共用 base，但路径不同（/responses）
        return cfg.base_url or default_base_url("openai_chat", "openai")

    def _headers(self, cfg: LlmConfig) -> dict[str, str]:
        return {
            "content-type": "application/json",
            "Authorization": f"Bearer {cfg.api_key}",
        }

    def _body(self, cfg: LlmConfig, req: CompletionRequest) -> dict:
        parts: list[dict] = [{"type": "input_text", "text": "\n".join(str(m.get("content", "")) for m in req.messages)}]
        for img in req.images:
            parts.append(
                {
                    "type": "input_image",
                    "image_url": f"data:{img.get('media_type', 'image/png')};base64,{img['data']}",
                }
            )
        body: dict = {
            "model": req.model_id or cfg.model_id,
            "input": [{"role": "user", "content": parts}],
            "max_output_tokens": max(1, min(req.max_tokens, 64_000)),
        }
        if req.system:
            body["instructions"] = req.system
        return body

    async def probe(self, cfg: LlmConfig) -> ProbeResult:
        # 模型列表与 Chat 共用 /models，直接复用 OpenAI 适配器的实现
        helper = OpenAIAdapter()
        return await helper.probe(cfg)

    async def list_models(self, cfg: LlmConfig) -> list[ModelInfo]:
        return await OpenAIAdapter().list_models(cfg)

    async def complete(self, cfg: LlmConfig, req: CompletionRequest) -> CompletionResult:
        cmap = compat_for(cfg.protocol)
        url = join_url(self._base(cfg), cmap.chat_path)
        async with new_client() as client:
            resp = await request_with_retry(
                client, "POST", url, json=self._body(cfg, req), headers=self._headers(cfg), attempts=3
            )
            data = resp.json()
        text_parts: list[str] = []
        for item in data.get("output", []) or []:
            if not isinstance(item, dict):
                continue
            for part in item.get("content", []) or []:
                if isinstance(part, dict) and part.get("type") in ("output_text", "text"):
                    text_parts.append(str(part.get("text", "")))
        usage = data.get("usage") or {}
        return CompletionResult(
            text="".join(text_parts),
            usage=Usage(
                tokens_in=int(usage.get("input_tokens", 0) or 0),
                tokens_out=int(usage.get("output_tokens", 0) or 0),
            ),
            model_id=str(data.get("model", req.model_id)),
            raw=data if isinstance(data, dict) else {},
        )

    async def stream(self, cfg: LlmConfig, req: CompletionRequest) -> AsyncIterator[Chunk]:
        result = await self.complete(cfg, req)
        yield Chunk(delta=result.text, done=True, usage=result.usage)

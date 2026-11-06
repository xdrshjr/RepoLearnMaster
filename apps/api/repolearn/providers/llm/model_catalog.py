"""内置模型目录（spec §3.7.1 的来源②）。

为什么需要静态表：provider 的 `/models` 接口**不返回价格，也常常不返回模态**。
没有这张表，"多模态能力"就只能靠猜，而"成本门禁 ≤0.35 USD"会直接变成 0。

规则（§3.4）：**没有价格的模型记 0 并在 warnings 里带 `PRICE_UNKNOWN`** ——不猜价格。
因此本表只收录确实公开过价格的型号；不在表里的模型照常可用，只是成本记为 0。
"""

from __future__ import annotations

from repolearn.providers.base import ModelCapabilities, ModelInfo

#: (provider, model_id) → (context_window, price_in, price_out, caps)
#: 价格为 USD / 1M tokens。这是一个**会过期的表**，所以它只是来源②而不是唯一来源。
CATALOG: dict[tuple[str, str], tuple[int, float, float, dict[str, bool]]] = {
    ("anthropic", "claude-sonnet-4-5"): (200_000, 3.0, 15.0, {"vision": True, "tools": True}),
    ("anthropic", "claude-opus-4-1"): (200_000, 15.0, 75.0, {"vision": True, "tools": True}),
    ("anthropic", "claude-3-7-sonnet-latest"): (200_000, 3.0, 15.0, {"vision": True, "tools": True}),
    ("anthropic", "claude-3-5-haiku-latest"): (200_000, 0.8, 4.0, {"vision": True, "tools": True}),
    ("openai", "gpt-4o"): (128_000, 2.5, 10.0, {"vision": True, "tools": True, "json_mode": True}),
    ("openai", "gpt-4o-mini"): (128_000, 0.15, 0.6, {"vision": True, "tools": True, "json_mode": True}),
    ("openai", "gpt-4.1"): (1_047_576, 2.0, 8.0, {"vision": True, "tools": True, "json_mode": True}),
    ("openai", "o4-mini"): (200_000, 1.1, 4.4, {"tools": True, "thinking": True}),
    ("google", "gemini-2.5-pro"): (1_048_576, 1.25, 10.0, {"vision": True, "tools": True, "thinking": True}),
    ("google", "gemini-2.5-flash"): (1_048_576, 0.3, 2.5, {"vision": True, "tools": True}),
    ("google", "gemini-2.0-flash"): (1_048_576, 0.1, 0.4, {"vision": True, "tools": True}),
}

#: 模态线索：模型名里出现这些片段时，即使 provider 没声明也按"支持图片输入"处理。
VISION_HINTS = ("vision", "vl", "4o", "gemini", "claude-3", "claude-sonnet", "claude-opus", "gpt-4.1", "gpt-5")

#: 上下文窗口的保守兜底（provider 没给且目录里没有时使用）。
FALLBACK_CONTEXT = 32_000


def capabilities_for(provider: str, model_id: str) -> ModelCapabilities:
    key = (provider or "", model_id or "")
    ctx, pin, pout, caps = CATALOG.get(key, (0, 0.0, 0.0, {}))
    lowered = (model_id or "").lower()
    vision = caps.get("vision")
    if vision is None:
        vision = any(h in lowered for h in VISION_HINTS)
    return ModelCapabilities(
        text=True,
        vision=bool(vision),
        audio_in="audio" in lowered,
        audio_out=False,
        tools=caps.get("tools", True),
        json_mode=caps.get("json_mode", True),
        streaming=True,
        thinking=caps.get("thinking", False),
        context_window=ctx or FALLBACK_CONTEXT,
        price_in=pin,
        price_out=pout,
    )


def price_known(provider: str, model_id: str) -> bool:
    return (provider or "", model_id or "") in CATALOG


def enrich(provider: str, models: list[ModelInfo]) -> list[ModelInfo]:
    """provider 只返回了 id 时，用目录补全能力与价格。"""
    out: list[ModelInfo] = []
    for m in models:
        caps = capabilities_for(provider, m.id)
        out.append(
            ModelInfo(
                id=m.id,
                display_name=m.display_name or m.id,
                capabilities=caps,
                context_window=m.context_window or caps.context_window,
                price=m.price or caps.price_in,
            )
        )
    return out


def catalog_rows() -> list[dict[str, object]]:
    """供 `model_catalog` 表首次填充/刷新使用。"""
    rows: list[dict[str, object]] = []
    for (provider, model_id), (ctx, pin, pout, caps) in CATALOG.items():
        c = capabilities_for(provider, model_id)
        rows.append(
            {
                "provider": provider,
                "model_id": model_id,
                "display_name": model_id,
                "capabilities": c.as_dict(),
                "context_window": ctx,
                "price_in": pin,
                "price_out": pout,
            }
        )
    return rows

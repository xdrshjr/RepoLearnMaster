"""共享 HTTP 工具：超时、重试、退避抖动、错误分类（spec §3.11.3）。

放在 providers 而不是 core，是因为只有出站调用需要它；但四个适配器与 TTS 都共用
同一份实现，否则"GitHub 重试 3 次、Anthropic 重试 0 次"这种不一致会在故障时暴露。
"""

from __future__ import annotations

import asyncio
import random
from typing import Any

import httpx

from repolearn.core.config import settings
from repolearn.providers.base import LlmError

RETRY_STATUS = {408, 409, 425, 429, 500, 502, 503, 504, 529}


def new_client(timeout_read: float | None = None) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        timeout=httpx.Timeout(
            connect=settings.http_timeout_connect,
            read=timeout_read or settings.http_timeout_read,
            write=60.0,
            pool=30.0,
        ),
        limits=httpx.Limits(max_connections=32, max_keepalive_connections=16),
        follow_redirects=True,
    )


def backoff_delay(attempt: int, retry_after: float | None = None) -> float:
    """指数退避 + 抖动。抖动是为了避免 12 个并行课时在同一毫秒一起重试。"""
    if retry_after is not None:
        return min(max(retry_after, 0.1), 30.0)
    base = min(2 ** (attempt - 1), 8)
    return base + random.uniform(0, 0.4)


def _lower_headers(headers: Any) -> dict[str, str]:
    """把 httpx 的头部复制成小写键的普通 dict。

    为什么要复制：`LlmError` 会活到调用方，而 `response.headers` 属于一个已经
    关闭的响应对象；把两者绑在一起等于在异常里藏一个失效引用。
    """
    if not headers:
        return {}
    try:
        return {str(k).lower(): str(v) for k, v in headers.items()}
    except Exception:  # noqa: BLE001 - 头部不可枚举不该让错误处理本身失败
        return {}


def quota_exhausted(headers: Any) -> bool:
    """`X-RateLimit-Remaining: 0` 意味着**重试毫无意义**，只会再烧一次配额。

    这是"限流"里唯一能确定的一件事：剩余额度是 0 时，退避 1 秒再打一次仍然是
    403/429，而用户要多等 1~3 秒才看到同一句话。
    """
    try:
        raw = headers.get("x-ratelimit-remaining") if headers else None
    except Exception:  # noqa: BLE001
        return False
    return str(raw).strip() == "0"


def classify_status(status: int, body: str, headers: Any = None) -> LlmError:
    """HTTP 状态 → 统一异常。`retryable` 是唯一需要上层关心的事。"""
    snippet = (body or "")[:300]
    hdrs = _lower_headers(headers)
    kwargs = {"status": status, "headers": hdrs}
    if status in (401, 403):
        return LlmError(
            f"鉴权失败（{status}）：{snippet}",
            code="INVALID_KEY",
            retryable=False,
            **kwargs,
        )
    if status == 429:
        return LlmError(
            f"限流（429）：{snippet}",
            code="RATE_LIMITED",
            retryable=True,
            retry_after_s=parse_retry_after(headers),
            **kwargs,
        )
    if status in RETRY_STATUS:
        return LlmError(
            f"上游服务错误（{status}）：{snippet}",
            code="PROVIDER_UNAVAILABLE",
            retryable=True,
            **kwargs,
        )
    if status == 400:
        return LlmError(f"请求被拒绝（400）：{snippet}", code="PROVIDER_BAD_REQUEST", retryable=False, **kwargs)
    return LlmError(f"上游返回 {status}：{snippet}", code="PROVIDER_UNAVAILABLE", retryable=False, **kwargs)


def parse_retry_after(headers: Any) -> float | None:
    raw = None
    try:
        raw = headers.get("retry-after") if headers else None
    except Exception:  # noqa: BLE001
        raw = None
    if not raw:
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


async def request_with_retry(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    *,
    json: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    params: dict[str, Any] | None = None,
    attempts: int = 3,
) -> httpx.Response:
    """指数退避重试。**只在 5xx/429/网络错误上重试**——401 重试 3 次只是浪费 3 秒。"""
    last: LlmError | None = None
    for attempt in range(1, attempts + 1):
        try:
            resp = await client.request(method, url, json=json, headers=headers, params=params)
        except httpx.TimeoutException as exc:
            last = LlmError(f"请求超时：{exc.__class__.__name__}", code="PROVIDER_UNAVAILABLE", retryable=True)
        except httpx.HTTPError as exc:
            last = LlmError(f"网络错误：{exc.__class__.__name__}", code="PROVIDER_UNAVAILABLE", retryable=True)
        else:
            if resp.status_code < 400:
                return resp
            raise_err = classify_status(resp.status_code, resp.text, resp.headers)
            # 额度已耗尽（`X-RateLimit-Remaining: 0`）时不重试：退避再打一次仍然是
            # 同一个 403/429，只是让用户多等几秒。把"何时能重试"交给错误提示。
            if not raise_err.retryable or attempt >= attempts or quota_exhausted(resp.headers):
                raise raise_err
            last = raise_err
            await asyncio.sleep(backoff_delay(attempt, parse_retry_after(resp.headers)))
            continue
        if attempt >= attempts:
            raise last
        await asyncio.sleep(backoff_delay(attempt))
    raise last or LlmError("请求失败", retryable=True)

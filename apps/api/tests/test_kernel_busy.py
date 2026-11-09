"""内核 429（`KERNEL_BUSY`）是**背压**，不是故障（T-KRN-5 / T-KRN-6）。

真实现场（2026-11-09 浏览器实测，job `job_01M6ZCNVY0CGT1GHGV24CNKPZN`）：

    planner : ok（38,012 tokens，课程骨架已交付）
    writer  : HTTP 429  {"error":{"code":"KERNEL_BUSY","message":"too many concurrent runs"}}
    job     : failed · PROVIDER_UNAVAILABLE · 12 个课时一个都没留下

内核 `/v1/run` 在并发超过 8 时主动返回 429（这是它该做的事：保护自己）。
错在客户端把它当成"模型不可用"：`HttpKernelRuntime.run` 只对 5xx 重试一次，
429 直接返回 → `_Ctx.run` 抛 PROVIDER_UNAVAILABLE → job 失败。
等一两秒再试就能成功，所以正确语义是**退避重试**。
"""

from __future__ import annotations

import json

import httpx
import pytest

from repolearn.providers import agent_runtime
from repolearn.providers.agent_runtime import HttpKernelRuntime
from repolearn.providers.base import AgentBudget, AgentRunRequest, LlmConfig

BUSY_BODY = b'{"error":{"code":"KERNEL_BUSY","message":"too many concurrent runs"}}'


class _FakeStream:
    """`client.stream(...)` 的上下文管理器替身。"""

    def __init__(self, response: httpx.Response) -> None:
        self.response = response

    async def __aenter__(self) -> httpx.Response:
        return self.response

    async def __aexit__(self, *exc: object) -> None:
        return None


class _FakeClient:
    def __init__(self, responses: list[httpx.Response], record: list[str]) -> None:
        self._responses = responses
        self._record = record

    def stream(self, method: str, url: str, **kwargs: object):  # noqa: ANN201
        self._record.append(url)
        response = self._responses.pop(0) if self._responses else self._responses[-1]
        return _FakeStream(response)

    async def __aenter__(self) -> _FakeClient:
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None


def _req() -> AgentRunRequest:
    return AgentRunRequest(
        run_id="run_x",
        role="writer",
        config=LlmConfig(provider="custom", protocol="openai_compatible", api_key="k", model_id="m"),
        system_prompt="s",
        prompt="p",
        budget=AgentBudget(max_turns=8, max_tokens=10_000, max_usd=1.0, deadline_ms=60_000),
    )


def _sse_ok() -> httpx.Response:
    # 必须是**信封**形状（schemaVersion/type/seq/ts/runId/data）：
    # `_parse_sse` 只从 `data` 字段里取事件体（内核 `envelope()` 的契约）。
    envelope = {
        "schemaVersion": 1,
        "type": "run.completed",
        "seq": 1,
        "ts": 1,
        "jobId": None,
        "runId": "run_x",
        "data": {"result": {"lessons": {"1.1": {"key": "1.1"}}}, "usage": {"tokensIn": 10, "tokensOut": 2}},
    }
    body = f"id: 1\nevent: run.completed\ndata: {json.dumps(envelope)}\n\n".encode()
    return httpx.Response(
        200,
        headers={"content-type": "text/event-stream"},
        content=body,
        request=httpx.Request("POST", "http://x/v1/run"),
    )


def _busy() -> httpx.Response:
    return httpx.Response(429, content=BUSY_BODY, request=httpx.Request("POST", "http://x/v1/run"))


@pytest.mark.asyncio
async def test_kernel_busy_is_retried_not_fatal(monkeypatch):
    """T-KRN-5：429 之后应该重试，并且最终拿到交付物。"""
    record: list[str] = []
    responses = [_busy(), _sse_ok()]
    monkeypatch.setattr(agent_runtime, "new_local_client", lambda **_kw: _FakeClient(responses, record))
    slept: list[float] = []

    async def _fake_sleep(seconds: float) -> None:
        slept.append(seconds)

    monkeypatch.setattr(agent_runtime.asyncio, "sleep", _fake_sleep)

    events, result = await HttpKernelRuntime().run(_req())

    assert result.status == "completed", result.error
    assert result.result["lessons"]["1.1"]["key"] == "1.1"
    assert slept == [agent_runtime.BUSY_BACKOFF_S[0]], "必须真的等一会儿再试，而不是立刻重试"
    assert len(record) == 2, "第一次 429、第二次成功"


@pytest.mark.asyncio
async def test_kernel_busy_gives_up_after_the_backoff_series(monkeypatch):
    """T-KRN-6：退避用尽才放弃，并且错误码必须是 KERNEL_BUSY（而不是 PROVIDER_UNAVAILABLE）。"""
    record: list[str] = []
    responses = [_busy() for _ in range(20)]
    monkeypatch.setattr(agent_runtime, "new_local_client", lambda **_kw: _FakeClient(responses, record))

    async def _fake_sleep(_seconds: float) -> None:
        return None

    monkeypatch.setattr(agent_runtime.asyncio, "sleep", _fake_sleep)

    events, result = await HttpKernelRuntime().run(_req())

    assert result.status == "failed"
    assert (result.error or {}).get("code") == "KERNEL_BUSY"
    assert len(record) == len(agent_runtime.BUSY_BACKOFF_S) + 1

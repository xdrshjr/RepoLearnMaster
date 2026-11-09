"""N8 必须能通过 **NodeContext 包装对象** 读到熔断原因（T-TTS-6）。

真实现场（2026-11-09 真机）：日志里已经有 `tts_circuit_open`，熔断确实生效了，
但课程 `warnings` 里没有 `TTS_DEGRADED`，`playback_meta.narration` 里也没有
`no_voice_reason` —— 用户仍然只看到"本节无配音"。

根因在接缝：`make_nodes()` 拿到的是 `course_graph.NodeContext` 包装对象，
它只代理方法（run / read_file / synthesize / publish），新加的
`tts_disabled_reason` / `tts_last_error` 字段不在它身上。

本用例刻意调用**产品的装配函数** `handlers.build_node_context()`，而不是照抄一遍
（照抄的话，把 `tts_state` 那行删掉也不会红——实测过）。
"""

from __future__ import annotations

import pytest

from repolearn.jobs import handlers as handlers_mod
from repolearn.providers.base import TtsResult
from repolearn.providers.budget_guard import JobBudget
from repolearn.workflow import nodes as nodes_mod

LESSON = {
    "key": "1.1",
    "steps": [
        {
            "index": 0,
            "title": "step",
            "duration_ms": 3000,
            "segments": [{"id": "s0", "text": "讲一句", "start_ms": 0, "end_ms": 3000}],
        }
    ],
}


class _FailingTts:
    provider = "qwen"
    configured = True

    class cfg:
        voice_type = "Cherry"
        speed_ratio = 1.0

    def __init__(self) -> None:
        self.calls = 0

    async def synthesize(self, text: str) -> TtsResult:  # noqa: ARG002
        self.calls += 1
        return TtsResult(
            ok=False,
            error={"code": "PROVIDER_UNAVAILABLE", "message": "400 url error: /audio/speech 路由不存在"},
        )


def _real_node_ctx():
    tts = _FailingTts()

    async def _emit(_node: str, _payload: dict) -> None:
        return None

    inner = handlers_mod._Ctx(
        job_id="job_test",
        course_id="crs_test",
        resolver=None,
        budget=JobBudget(),
        tts=tts,
        runtime_mode="kernel",
        emit=_emit,
    )
    inner.load_artifact = lambda _key: dict(LESSON)  # noqa: E731
    inner.save_artifact = lambda _n, _k, _p: "artifacts/x.json"  # noqa: E731

    # ← 产品代码本身，不是照抄
    node_ctx = handlers_mod.build_node_context(inner, job_id="job_test", runtime_mode="kernel")
    return node_ctx, tts


@pytest.mark.asyncio
async def test_wrapper_object_still_surfaces_the_tts_reason():
    """T-TTS-6：经由 NodeContext 也要出 TTS_DEGRADED 与 no_voice_reason。"""
    node_ctx, tts = _real_node_ctx()
    made = nodes_mod.make_nodes(node_ctx)

    lessons = {f"l{i}": {"artifact": "a.json"} for i in range(1, 6)}
    update = await made["synthesize_audio"]({"lessons": lessons, "commit": {"sha": "a" * 40}})

    assert tts.calls == handlers_mod.TTS_FAILURE_THRESHOLD
    tts_warnings = [w for w in update["warnings"] if w["code"] == "TTS_DEGRADED"]
    assert len(tts_warnings) == 1, f"应只有一条 TTS_DEGRADED，实际 {update['warnings']}"
    assert "url error" in tts_warnings[0]["message"]
    for key in lessons:
        assert update["narration"][key].get("no_voice_reason"), update["narration"][key]

"""TTS 熔断与原因透出（T-TTS-5）。

真实情况（2026-11-09）：把 TTS 配到一个不能出声的网关后，每个课时的每一步都会去撞
一次合成（内部两条候选路径 → 2 个 HTTP 请求），10 个课时 ≈ 60 次失败请求，生成被
拖慢几十秒，而用户仍然只看到一句"本节无配音"，看不到原因。
"""

from __future__ import annotations

import pytest

from repolearn.jobs import handlers as handlers_mod
from repolearn.jobs.handlers import TTS_FAILURE_THRESHOLD
from repolearn.providers.base import TtsResult
from repolearn.providers.budget_guard import JobBudget
from repolearn.workflow import nodes as nodes_mod

LESSON = {
    "key": "1.1",
    "title": "t",
    "layer": "overview",
    "steps": [
        {
            "index": 0,
            "title": "step",
            "duration_ms": 3000,
            "segments": [{"id": "s0", "text": "讲一句", "start_ms": 0, "end_ms": 3000}],
        }
    ],
    "quiz": [],
}


class _FailingTts:
    """每次都失败的 TTS（模一个 400/500 的网关）。"""

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


def _real_ctx(tts) -> handlers_mod._Ctx:  # noqa: ANN001
    async def _emit(_node: str, _payload: dict) -> None:
        return None

    ctx = handlers_mod._Ctx(
        job_id="job_test",
        course_id="crs_test",
        resolver=None,
        budget=JobBudget(),
        tts=tts,
        runtime_mode="kernel",
        emit=_emit,
    )
    ctx.load_artifact = lambda _key: dict(LESSON)  # noqa: E731
    ctx.save_artifact = lambda _n, _k, _p: "artifacts/x.json"  # noqa: E731
    return ctx


@pytest.mark.asyncio
async def test_circuit_opens_after_threshold_and_reports_reason():
    """T-TTS-5：连续失败到阈值后停止尝试，并且只留一条带原因的警告。"""
    tts = _FailingTts()
    ctx = _real_ctx(tts)
    made = nodes_mod.make_nodes(ctx)

    lessons = {f"l{i}": {"artifact": "a.json"} for i in range(1, 7)}
    update = await made["synthesize_audio"]({"lessons": lessons, "commit": {"sha": "a" * 40}})

    # 熔断生效：调用次数停在阈值，不会对每个课时都打一次
    assert tts.calls == TTS_FAILURE_THRESHOLD, f"应当熔断在 {TTS_FAILURE_THRESHOLD} 次，实际 {tts.calls}"
    assert ctx.tts_disabled_reason and "url error" in ctx.tts_disabled_reason

    # 只报一条，且带真实原因
    tts_warnings = [w for w in update["warnings"] if w["code"] == "TTS_DEGRADED"]
    assert len(tts_warnings) == 1, update["warnings"]
    assert "url error" in tts_warnings[0]["message"]

    # 每个没配音的课时都能查到原因
    for key in lessons:
        assert update["narration"][key]["no_voice_reason"]
        assert update["narration"][key]["timing_source"] == "estimated"
        assert update["narration"][key]["voiced_steps"] == 0


@pytest.mark.asyncio
async def test_no_client_means_plain_subtitles_without_warning():
    """没配 TTS（None）是设计内的正常路径：字幕推进，且不该刷 TTS_DEGRADED。"""
    ctx = _real_ctx(None)
    made = nodes_mod.make_nodes(ctx)

    update = await made["synthesize_audio"]({"lessons": {"l1": {"artifact": "a.json"}}, "commit": {"sha": "a" * 40}})

    assert update["narration"]["l1"]["timing_source"] == "estimated"
    assert [w for w in update["warnings"] if w["code"] == "TTS_DEGRADED"] == []

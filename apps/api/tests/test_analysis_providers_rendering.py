"""静态分析、TTS、渲染与运行时选择（spec §3.4 N4 / §3.8 / §2.3 / §3.5.3）。"""

from __future__ import annotations

import asyncio

from repolearn.analysis import analyze
from repolearn.analysis.callgraph import build_call_graph
from repolearn.analysis.symbols import TS_AVAILABLE, outline
from repolearn.core.errors import AppError
from repolearn.providers.agent_runtime import (
    RuntimeState,
    _parse_sse,
    refresh_state,
    reset_state_for_tests,
)
from repolearn.providers.budget_guard import CallGuard, JobBudget, estimate_tokens, usd_for
from repolearn.providers.compat_map import PROTOCOL_FAMILY, compat_for, default_base_url
from repolearn.providers.llm.model_catalog import capabilities_for, price_known
from repolearn.providers.registry import adapter_for
from repolearn.providers.tts.doubao import estimate_duration_ms, split_sentences, text_hash
from repolearn.rendering.book_layout import blocks_to_html, build_chapters
from repolearn.rendering.mermaid import parse_mermaid, render_svg

SRC = (
    '"""模块说明。"""\n'
    "class Engine:\n"
    "    def run(self):\n"
    "        return helper()\n"
    "\n"
    "def helper():\n"
    "    return Engine()\n"
)


# ---- 分析 -----------------------------------------------------------------


def test_outline_extracts_symbols_with_lines():
    result = outline(SRC, "pkg/mod.py")
    names = [s.name for s in result.symbols]
    assert names == ["Engine", "run", "helper"]
    assert result.symbols[0].line_start == 2


def test_outline_marks_degraded_when_treesitter_missing():
    result = outline(SRC, "pkg/mod.py")
    assert result.degraded is (not TS_AVAILABLE)


def test_call_graph_links_caller_to_callee():
    symbols = outline(SRC, "pkg/mod.py").symbols
    graph = build_call_graph(symbols)
    assert any(edge.callee.endswith("::helper") for edge in graph.edges)
    assert graph.in_degree.get("helper", 0) >= 1


def test_key_chain_is_scored_and_non_empty():
    files = [{"path": "pkg/mod.py", "size": len(SRC), "lang": "python", "is_core": True}]
    result = analyze(files, lambda p: SRC)
    assert result.chains
    assert result.chains[0].score > 0
    assert result.blueprint()["chains"]


def test_analysis_reports_anchor_candidates():
    files = [{"path": "pkg/mod.py", "size": len(SRC), "lang": "python", "is_core": True}]
    result = analyze(files, lambda p: SRC)
    anchors = result.knowledge_graph.anchors()
    assert anchors and all("line_start" in a for a in anchors)


def test_analysis_survives_unreadable_file():
    files = [
        {"path": "a.py", "size": 10, "lang": "python", "is_core": True},
        {"path": "b.py", "size": 10, "lang": "python", "is_core": True},
    ]

    def read(path: str) -> str:
        if path == "a.py":
            raise OSError("boom")
        return SRC

    result = analyze(files, read)
    assert result.knowledge_graph.total_files == 2
    assert result.outlines


def test_mermaid_generation_from_module_graph():
    files = [{"path": "pkg/mod.py", "size": len(SRC), "lang": "python", "is_core": True}]
    result = analyze(files, lambda p: SRC)
    mermaid = result.knowledge_graph.to_mermaid()
    assert mermaid.startswith("flowchart LR")


# ---- TTS ------------------------------------------------------------------


def test_split_sentences_respects_limit():
    text = "第一句。" * 300
    parts = split_sentences(text, limit=100)
    assert all(len(p) <= 100 for p in parts)
    assert "".join(parts) == text


def test_split_sentences_keeps_short_text_whole():
    assert split_sentences("很短") == ["很短"]


def test_estimate_duration_by_bitrate():
    assert estimate_duration_ms(24_000) == 8000


def test_audio_cache_key_is_stable_and_sensitive():
    a = text_hash("doubao", "voice", 1.0, "你好")
    b = text_hash("doubao", "voice", 1.0, "你好")
    c = text_hash("doubao", "other", 1.0, "你好")
    assert a == b != c


# ---- 渲染 -----------------------------------------------------------------


def test_mermaid_render_produces_svg_with_nodes():
    svg = render_svg("flowchart LR\n  a[Agent] --> b[Tool]")
    assert svg.startswith("<svg")
    assert "Agent" in svg
    assert "marker-end" in svg


def test_mermaid_render_escapes_html():
    svg = render_svg('flowchart LR\n  a["<script>alert(1)</script>"]')
    assert "<script>" not in svg


def test_mermaid_falls_back_to_source_block():
    svg = render_svg("")
    assert "diagram-fallback" in svg


def test_parse_mermaid_edges_and_labels():
    diagram = parse_mermaid("flowchart LR\n  a[A] -->|2| b[B]")
    assert diagram.nodes["a"] == "A"
    assert diagram.edges == [("a", "b", "2")]


def test_book_chapters_have_source_refs():
    chapters = build_chapters(
        course_title="课程",
        commit_sha="abc123def456",
        repo_full_name="o/r",
        sections=[{"key": "overview", "title": "第一层", "minutes": 5}],
        lessons=[
            {
                "key": "1.1",
                "title": "走读",
                "section_key": "overview",
                "goal": "看懂",
                "steps": [
                    {
                        "segments": [{"text": "讲解", "focus": {"file": "pkg/mod.py", "line_start": 1, "line_end": 2}}],
                        "code_notes": [{"file": "pkg/mod.py", "line": 3, "text": "注释"}],
                    }
                ],
                "files": [{"path": "pkg/mod.py"}],
            }
        ],
    )
    assert chapters[0]["source_refs"]
    assert chapters[0]["blocks"][0]["type"] == "md"
    assert chapters[0]["word_count"] > 0


def test_book_html_escapes_code():
    html = blocks_to_html([{"type": "code", "text": "<b>x</b>", "caption": "cap"}])
    assert "&lt;b&gt;" in html


# ---- 运行时选择与预算 ------------------------------------------------------


def test_protocols_map_to_the_right_adapter():
    """协议 → 适配器族（Python 侧）。未知协议一律按 OpenAI 兼容兜底。"""
    assert PROTOCOL_FAMILY["anthropic_messages"] == "anthropic"
    assert PROTOCOL_FAMILY["openai_chat"] == "openai"
    assert PROTOCOL_FAMILY["google_generate"] == "google"
    assert PROTOCOL_FAMILY["openai_responses"] == "openai_responses"
    assert adapter_for("anthropic_messages").protocol == "anthropic_messages"
    assert adapter_for("openai_compatible").protocol == "openai_chat"
    assert adapter_for("totally_unknown").protocol == "openai_chat"


def test_compat_map_picks_azure_for_azure_base_url():
    azure = compat_for("openai_chat", "azure", "https://x.openai.azure.com")
    assert azure.deployment_in_path is True
    normal = compat_for("openai_chat", "openai", "https://api.openai.com/v1")
    assert normal.deployment_in_path is False
    assert default_base_url("anthropic_messages").startswith("https://api.anthropic.com")


def test_model_catalog_knows_flagship_prices():
    caps = capabilities_for("anthropic", "claude-sonnet-4-5")
    assert caps.vision is True
    assert caps.price_in > 0
    assert price_known("anthropic", "claude-sonnet-4-5") is True
    # 未收录的模型：价格为 0（PRICE_UNKNOWN 语义），但仍然可用
    unknown = capabilities_for("custom", "my-local-model")
    assert unknown.price_in == 0.0
    assert price_known("custom", "my-local-model") is False


def test_job_budget_trips_on_tokens():
    budget = JobBudget(max_tokens=100)
    budget.charge(80, 50)
    assert budget.exceeded() == "tokens"
    try:
        budget.check()
    except AppError as exc:
        assert exc.code == "BUDGET_EXCEEDED"
        assert exc.details["kind"] == "tokens"
    else:  # pragma: no cover
        raise AssertionError("budget.check() 应该抛错")


def test_call_guard_rejects_oversized_prompt():
    guard = CallGuard(limit_tokens=10)
    guard.check_prompt("short")
    try:
        guard.check_prompt("x" * 1000)
    except AppError as exc:
        assert exc.code == "BUDGET_EXCEEDED"
    else:  # pragma: no cover
        raise AssertionError("超长 prompt 应该被拒绝")


def test_estimate_tokens_matches_kernel_convention():
    assert estimate_tokens("abcd") == 1
    assert estimate_tokens("a" * 400) == 100


def test_usd_for_only_counts_when_priced():
    assert usd_for(1_000_000, 0, 3.0, 15.0) == 3.0
    assert usd_for(1_000_000, 0, 0.0, 0.0) == 0.0


def test_runtime_state_degrades_flag():
    assert RuntimeState(mode="kernel").degraded is False
    assert RuntimeState(mode="template").degraded is True


def test_refresh_state_in_template_mode(monkeypatch):
    """测试环境把 runtime 配成 template：不应尝试 exec（状态 C 的正确行为是直接模板降级）。"""
    reset_state_for_tests()
    state = asyncio.get_event_loop_policy().new_event_loop().run_until_complete(refresh_state(force=True))
    assert state.mode == "template"
    reset_state_for_tests()


def test_parse_sse_frame():
    frame = 'id: 3\nevent: agent.text.delta\ndata: {"type":"agent.text.delta","seq":3,"data":{"delta":"hi"}}'
    event = _parse_sse(frame)
    assert event is not None
    assert event.type == "agent.text.delta"
    assert event.seq == 3
    assert event.data["delta"] == "hi"


def test_parse_sse_ignores_keepalive():
    assert _parse_sse(": keepalive") is None

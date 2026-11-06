"""知识图（spec §3.4 N4）。

N4 的产物要同时服务三件事，而它们的体量需求完全不同：
* **N5（规划课时）** 需要"目录骨架 + 模块划分 + 入口点"，需要**摘要**；
* **N6（写课时）** 需要具体符号的锚点候选集，需要**明细**；
* **前端** 需要可渲染的模块关系图，需要**中间粒度**。

所以 `KnowledgeGraph` 有三层视图，而 state 里只放摘要（spec §3.4 checkpoint ≤ 256KB），
完整结构落 artifact。这不是"优化"，是让图能在 SQLite 上跑起来的前提。
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import PurePosixPath

from repolearn.analysis.callgraph import CallGraph, build_call_graph
from repolearn.analysis.symbols import OutlineResult, Symbol


@dataclass
class Module:
    key: str
    path: str
    file_count: int = 0
    symbols: int = 0
    lines: int = 0
    entry: bool = False


@dataclass
class KnowledgeGraph:
    modules: list[Module] = field(default_factory=list)
    symbols: list[Symbol] = field(default_factory=list)
    call_graph: CallGraph = field(default_factory=CallGraph)
    languages: dict[str, int] = field(default_factory=dict)
    total_files: int = 0
    total_lines: int = 0
    degraded: bool = False
    degradation_reason: str = ""
    warnings: list[dict] = field(default_factory=list)

    # ---- 三层视图 ---------------------------------------------------------
    def summary(self) -> dict:
        """进 state 的摘要。**不含任何 symbol 明细**。"""
        return {
            "node_count": len(self.symbols),
            "edge_count": len(self.call_graph.edges),
            "entrypoints": self.call_graph.entrypoints[:8],
            "modules": [
                {"key": m.key, "path": m.path, "symbols": m.symbols, "lines": m.lines, "entry": m.entry}
                for m in self.modules[:24]
            ],
            "languages": dict(sorted(self.languages.items(), key=lambda kv: kv[1], reverse=True)[:6]),
            "total_files": self.total_files,
            "total_lines": self.total_lines,
            "degraded": self.degraded,
        }

    def anchors(self, limit: int = 400) -> list[dict]:
        """N6 的锚点候选集。按"入度（被调用次数）"排序——讲被调最多的函数最值钱。"""
        in_deg = self.call_graph.in_degree
        ordered = sorted(self.symbols, key=lambda s: (-in_deg.get(s.name, 0), s.file, s.line_start))
        out: list[dict] = []
        for sym in ordered[:limit]:
            anchor = sym.as_anchor()
            anchor["calls"] = in_deg.get(sym.name, 0)
            out.append(anchor)
        return out

    def diagram(self, limit: int = 40) -> dict:
        """前端/PDF 用的模块关系图（Mermaid DSL）。"""
        return {
            "kind": "architecture",
            "mermaid": self.to_mermaid(limit),
            "nodes": [{"id": m.key, "label": m.path, "source": {"file": m.path, "line": 1}} for m in self.modules[:limit]],
        }

    def to_mermaid(self, limit: int = 40) -> str:
        lines = ["flowchart LR"]
        for mod in self.modules[:limit]:
            nid = _nid(mod.key)
            lines.append(f'  {nid}["{mod.path}"]')
        edges = defaultdict(int)
        for edge in self.call_graph.edges:
            a, b = _nid(_module_of(edge.caller_file)), _nid(_module_of(edge.callee_file))
            if a != b:
                edges[(a, b)] += 1
        for (a, b), weight in sorted(edges.items(), key=lambda kv: kv[1], reverse=True)[:40]:
            lines.append(f"  {a} -->|{weight}| {b}")
        return "\n".join(lines)

    def unverified_symbols(self) -> list[str]:
        return [f"{s.file}:{s.line_start}" for s in self.symbols if s.line_end < s.line_start]


def _module_of(path: str) -> str:
    parts = PurePosixPath(path).parts
    if len(parts) <= 1:
        return parts[0] if parts else "root"
    return parts[0] if len(parts) > 2 else "/".join(parts[:2])


def _nid(key: str) -> str:
    return "m_" + "".join(ch if ch.isalnum() else "_" for ch in key)[:28]


def build_knowledge_graph(
    *,
    files: list[dict],
    outlines: list[OutlineResult],
    total_lines: int = 0,
    degraded: bool = False,
    reason: str = "",
) -> KnowledgeGraph:
    all_symbols: list[Symbol] = []
    per_module: dict[str, Module] = {}
    languages: dict[str, int] = defaultdict(int)
    for item in files:
        languages[str(item.get("lang", "text"))] += 1
        key = _module_of(str(item.get("path", "")))
        mod = per_module.get(key) or Module(key=key, path=key)
        mod.file_count += 1
        per_module[key] = mod

    for res in outlines:
        all_symbols.extend(res.symbols)
        key = _module_of(res.file)
        mod = per_module.get(key) or Module(key=key, path=key)
        mod.symbols += len(res.symbols)
        mod.entry = mod.entry or any(h in PurePosixPath(res.file).name.lower() for h in ("main", "cli", "app", "server"))
        per_module[key] = mod

    graph = build_call_graph(all_symbols)
    modules = sorted(per_module.values(), key=lambda m: (-m.symbols, m.path))

    kg = KnowledgeGraph(
        modules=modules,
        symbols=all_symbols,
        call_graph=graph,
        languages=dict(languages),
        total_files=len(files),
        total_lines=total_lines,
        degraded=degraded,
        degradation_reason=reason,
    )
    if degraded:
        kg.warnings.append(
            {
                "code": "ANALYSIS_DEGRADED",
                "message": reason or "语法分析降级为正则抽取，锚点置信度较低",
                "severity": "warning",
                "node": "analyze_repo",
            }
        )
    if not all_symbols:
        kg.warnings.append(
            {
                "code": "NO_SYMBOLS",
                "message": "未能抽取任何符号，课程将退化为文件级走读",
                "severity": "warning",
                "node": "analyze_repo",
            }
        )
    return kg

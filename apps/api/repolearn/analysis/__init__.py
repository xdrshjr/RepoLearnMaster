"""静态分析层（spec §3.4 N4）。

`analyze()` 是唯一入口：给"镜像文件清单 + 读文件函数"，吐出一个 `AnalysisResult`。
把所有步骤（大纲 → 调用图 → 知识图 → 关键链）收在一个函数里，是为了让 N4 节点
只有一行调用，且失败/降级只有一处需要处理。
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from repolearn.analysis.callgraph import CallGraph, build_call_graph
from repolearn.analysis.key_chain import KeyChain, describe_chain, pick_key_chains
from repolearn.analysis.knowledge_graph import KnowledgeGraph, build_knowledge_graph
from repolearn.analysis.symbols import TS_AVAILABLE, OutlineResult, outline
from repolearn.core.logging import get_logger

log = get_logger("analysis")

MAX_ANALYZED_FILES = 400
MAX_FILE_CHARS = 200_000


@dataclass
class AnalysisResult:
    knowledge_graph: KnowledgeGraph
    chains: list[KeyChain] = field(default_factory=list)
    outlines: list[OutlineResult] = field(default_factory=list)
    warnings: list[dict] = field(default_factory=list)

    @property
    def degraded(self) -> bool:
        return self.knowledge_graph.degraded

    def summary(self) -> dict:
        return self.knowledge_graph.summary()

    def blueprint(self) -> dict:
        return {
            "modules": [m.path for m in self.knowledge_graph.modules[:12]],
            "entrypoints": self.knowledge_graph.call_graph.entrypoints[:6],
            "chains": [c.as_dict() for c in self.chains],
            "chain_notes": [describe_chain(c) for c in self.chains],
            "degraded": self.degraded,
        }


def analyze(files: list[dict], read: Callable[[str], str]) -> AnalysisResult:
    """对镜像做静态分析。

    `read` 是注入的读文件函数（而不是直接 `open`），这样测试可以喂内存夹具，
    也不会让分析层依赖 object_store 的路径规则。
    """
    core_files = [f for f in files if f.get("is_core")] or files
    core_files = sorted(core_files, key=lambda f: (-int(f.get("size", 0)), str(f.get("path"))))[:MAX_ANALYZED_FILES]

    outlines: list[OutlineResult] = []
    total_lines = 0
    for item in core_files:
        path = str(item.get("path", ""))
        try:
            text = read(path)[:MAX_FILE_CHARS]
        except Exception as exc:  # noqa: BLE001 - 读不到就跳过，不中断整份分析
            log.warning("analyze_read_failed", path=path, error=str(exc))
            continue
        total_lines += text.count("\n") + 1
        outlines.append(outline(text, path))

    degraded = not TS_AVAILABLE
    reason = "" if TS_AVAILABLE else "tree-sitter-language-pack 不可用，退化为正则抽取"
    kg = build_knowledge_graph(
        files=files,
        outlines=outlines,
        total_lines=total_lines,
        degraded=degraded,
        reason=reason,
    )
    chains = pick_key_chains(kg)
    result = AnalysisResult(knowledge_graph=kg, chains=chains, outlines=outlines)
    result.warnings.extend(kg.warnings)
    log.info(
        "analysis_done",
        files=len(files),
        analyzed=len(core_files),
        symbols=len(kg.symbols),
        edges=len(kg.call_graph.edges),
        chains=len(chains),
        degraded=degraded,
    )
    return result


__all__ = [
    "AnalysisResult",
    "CallGraph",
    "KeyChain",
    "KnowledgeGraph",
    "OutlineResult",
    "analyze",
    "build_call_graph",
    "build_knowledge_graph",
    "describe_chain",
    "outline",
    "pick_key_chains",
]

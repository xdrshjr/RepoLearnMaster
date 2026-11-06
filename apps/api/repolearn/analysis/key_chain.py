"""代表性调用链挑选（spec §3.4 N4 / N7）。

"代表性"是一个可计算的问题，不是凭感觉选一条：候选链按三个因子打分——
* **入度**：被调用越多，越可能是主干；
* **入口可达性**：从 entrypoint 出发能走到，说明它在真实执行路径上；
* **教学价值**：跨文件、跨模块的链路比"同文件三个函数互相调"更值得讲。

打分函数写在这里而不是内联，是因为 N7 的 trace 会引用它选出的链，而
`quality_report` 要用同一口径解释"为什么讲的是这一条"。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from repolearn.analysis.knowledge_graph import KnowledgeGraph


@dataclass
class ChainStep:
    symbol: str
    file: str
    line: int
    layer: int = 0
    confidence: str = "medium"

    def as_dict(self) -> dict:
        return {"symbol": self.symbol, "file": self.file, "line": self.line, "confidence": self.confidence}


@dataclass
class KeyChain:
    id: str
    title: str
    score: float
    steps: list[ChainStep] = field(default_factory=list)
    files: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "id": self.id,
            "title": self.title,
            "score": round(self.score, 3),
            "steps": [s.as_dict() for s in self.steps],
            "files": self.files,
        }


def _adjacency(kg: KnowledgeGraph) -> dict[str, list[tuple[str, str, str]]]:
    """caller(full) → [(callee(full), callee_file, confidence)]"""
    adj: dict[str, list[tuple[str, str, str]]] = {}
    for edge in kg.call_graph.edges:
        adj.setdefault(edge.caller, []).append((edge.callee, edge.callee_file, edge.confidence))
    return adj


def _split(full: str) -> tuple[str, str]:
    file, _, symbol = full.partition("::")
    return file, symbol


def _score(steps: list[ChainStep], kg: KnowledgeGraph, files_spanned: int) -> float:
    if not steps:
        return 0.0
    in_deg = kg.call_graph.in_degree
    heat = sum(in_deg.get(s.symbol, 0) for s in steps) / max(1, len(steps))
    depth = len(steps)
    spread = files_spanned
    conf = sum(1.0 if s.confidence == "high" else 0.6 if s.confidence == "medium" else 0.3 for s in steps) / len(steps)
    # 权重是刻意选的：深度 > 跨文件 > 热度 > 置信度。教学上"能讲 4 步并且跨文件"
    # 比"一个超热的孤立函数"更有价值。
    return depth * 1.6 + spread * 1.1 + min(heat, 20) * 0.35 + conf * 1.5


def pick_key_chains(kg: KnowledgeGraph, limit: int = 3, max_depth: int = 6) -> list[KeyChain]:
    adj = _adjacency(kg)
    line_of = {f"{s.file}::{s.name}": s.line_start for s in kg.symbols}
    starts: list[str] = []
    for entry in kg.call_graph.entrypoints:
        for full in adj:
            if _split(full)[1] == entry:
                starts.append(full)
    if not starts:
        starts = sorted(adj.keys(), key=lambda k: -kg.call_graph.out_degree.get(_split(k)[1], 0))[:5]

    chains: list[KeyChain] = []
    seen_signatures: set[tuple[str, ...]] = set()
    for start in starts[:6]:
        steps: list[ChainStep] = []
        visited: set[str] = set()
        current = start
        while current and len(steps) < max_depth and current not in visited:
            visited.add(current)
            callee_file, callee_symbol = _split(current)
            confidence = "high"
            if steps:
                prev = steps[-1]
                confidence = next(
                    (c for (t, _f, c) in adj.get(prev.file + "::" + prev.symbol, []) if t == current),
                    "medium",
                )
            steps.append(
                ChainStep(
                    symbol=callee_symbol,
                    file=callee_file,
                    line=line_of.get(current, 1),
                    layer=len(steps),
                    confidence=confidence,
                )
            )
            nexts = adj.get(current, [])
            if not nexts:
                break
            nexts.sort(key=lambda t: -kg.call_graph.in_degree.get(_split(t[0])[1], 0))
            current = nexts[0][0]
        signature = tuple(s.symbol for s in steps)
        if len(steps) < 2 or signature in seen_signatures:
            continue
        seen_signatures.add(signature)
        files = sorted({s.file for s in steps})
        score = _score(steps, kg, len(files))
        chains.append(
            KeyChain(
                id=f"chain_{len(chains) + 1}",
                title=" → ".join(s.symbol for s in steps[:4]),
                score=score,
                steps=steps,
                files=files,
            )
        )
    chains.sort(key=lambda c: -c.score)
    return chains[:limit]


def describe_chain(chain: KeyChain) -> str:
    """给人读的一句话说明（进 course_versions.blueprint）。"""
    if not chain.steps:
        return "未找到可讲解的调用链"
    head = chain.steps[0].symbol
    tail = chain.steps[-1].symbol
    return f"从 {head} 出发，经过 {len(chain.steps)} 步到达 {tail}，横跨 {len(chain.files)} 个文件"

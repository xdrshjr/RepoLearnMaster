"""调用图（spec §3.4 N4）。

边来自"符号 A 的函数体里出现了符号 B 的名字"。这**不是**精确的解析（没有类型推导、
没有跨包解析），因此每条边都带 `confidence`：
* `high`  —— B 与 A 同文件；
* `medium`—— B 在另一个文件里唯一存在；
* `low`   —— B 名字在多个文件出现（可能是同名不同物）。

这个区分是必要的：调用链会进课程讲解，如果把 `low` 当 `high` 用，讲解里就会
出现"send 调用了 get"这种在 20 个文件里都能成立的废话。
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

from repolearn.analysis.paths import is_test_path
from repolearn.analysis.symbols import Symbol


@dataclass
class Edge:
    caller: str
    callee: str
    caller_file: str
    callee_file: str
    confidence: str = "medium"


@dataclass
class CallGraph:
    edges: list[Edge] = field(default_factory=list)
    #: symbol → 被调用次数（入度），用于"代表性链路"的评分
    in_degree: dict[str, int] = field(default_factory=dict)
    out_degree: dict[str, int] = field(default_factory=dict)
    symbol_index: dict[str, list[Symbol]] = field(default_factory=dict)
    entrypoints: list[str] = field(default_factory=list)

    def as_summary(self) -> dict:
        return {
            "node_count": len(self.symbol_index),
            "edge_count": len(self.edges),
            "entrypoints": self.entrypoints[:10],
            "hot_symbols": sorted(self.in_degree.items(), key=lambda kv: kv[1], reverse=True)[:15],
        }

    def to_dot(self, limit: int = 60) -> str:
        lines = ["digraph callgraph {", '  rankdir=LR; node [shape=box, fontsize=10];']
        for edge in self.edges[:limit]:
            lines.append(f'  "{edge.caller}" -> "{edge.callee}";')
        lines.append("}")
        return "\n".join(lines)


ENTRY_HINTS = ("main", "__main__", "app", "server", "cli", "handler", "route", "run", "start", "entrypoint")


def build_call_graph(symbols: list[Symbol]) -> CallGraph:
    index: dict[str, list[Symbol]] = defaultdict(list)
    for sym in symbols:
        index[sym.name].append(sym)

    edges: list[Edge] = []
    in_deg: dict[str, int] = defaultdict(int)
    out_deg: dict[str, int] = defaultdict(int)
    seen: set[tuple[str, str]] = set()

    for sym in symbols:
        for called in sym.calls:
            targets = index.get(called, [])
            if not targets:
                continue
            same_file = [t for t in targets if t.file == sym.file]
            target = same_file[0] if same_file else targets[0]
            if target.name == sym.name and target.file == sym.file:
                continue
            key = (f"{sym.file}::{sym.name}", f"{target.file}::{target.name}")
            if key in seen:
                continue
            seen.add(key)
            confidence = "high" if same_file else ("medium" if len(targets) == 1 else "low")
            edges.append(
                Edge(
                    caller=f"{sym.file}::{sym.name}",
                    callee=f"{target.file}::{target.name}",
                    caller_file=sym.file,
                    callee_file=target.file,
                    confidence=confidence,
                )
            )
            out_deg[sym.name] += 1
            in_deg[target.name] += 1

    entrypoints = [
        s.name
        for s in symbols
        if any(h in s.name.lower() for h in ENTRY_HINTS)
        and in_deg.get(s.name, 0) <= 1
        and not is_test_path(s.file)
    ]
    if not entrypoints:
        # 回退时同样要排除测试文件：sherlock 的实测结果是入口点变成了
        # `TestLiveTargets` / `Test_All_Targets`（"被调用最少"的那几个），
        # 于是模板课把测试类当成"这门课的入口"讲给学习者。
        candidates = [s for s in symbols if not is_test_path(s.file)] or symbols
        entrypoints = [s.name for s in sorted(candidates, key=lambda s: in_deg.get(s.name, 0))[:3]]

    return CallGraph(
        edges=edges,
        in_degree=dict(in_deg),
        out_degree=dict(out_deg),
        symbol_index=dict(index),
        entrypoints=entrypoints[:10],
    )

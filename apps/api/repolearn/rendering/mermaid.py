"""Mermaid → SVG（spec §2.3 图表选型）。

**为什么不用 mermaid-cli**：那需要 Puppeteer + Chromium，而 Chromium 已经是
PDF 的可选依赖（Gate 0 G2）。让架构图也依赖它，等于把"能不能画图"绑在"能不能装
浏览器"上——一个本该零依赖的能力变成了外部依赖。

这里实现的是 `flowchart` 子集的服务端 SVG 渲染：节点 + 有向边 + 标签。它对
RepolLearn 的用途（模块关系、调用流）已经足够，而且**确定、可缓存、可比对**。
超出子集的输入不会报错，而是退化成一个"源码可见"的 pre 块——诚实且不崩。
"""

from __future__ import annotations

import hashlib
import html
import re
from dataclasses import dataclass, field

EDGE_ARROW = re.compile(r"-->|---|==>|-.->|===")
#: 一个节点引用：`id` 或 `id[label]` / `id(label)` / `id{label}`（含引号形式）
NODE_TOKEN = re.compile(r'([A-Za-z0-9_]+)\s*(?:\[\s*"?([^"\]]*)"?\s*\]|\(\s*"?([^")]*)"?\s*\)|\{\s*"?([^"}]*)"?\s*\})?')
EDGE_LABEL = re.compile(r"\|([^|]*)\|")

NODE_W = 168
NODE_H = 46
GAP_X = 56
GAP_Y = 34
PER_ROW = 3


@dataclass
class Diagram:
    nodes: dict[str, str] = field(default_factory=dict)
    edges: list[tuple[str, str, str]] = field(default_factory=list)

    @property
    def empty(self) -> bool:
        return not self.nodes


def parse_mermaid(source: str) -> Diagram:
    """解析 flowchart 的一个实用子集。

    为什么不用"逐字符解析器"：输入来自模型，写法在 `a --> b`、`a[A] --> b[B]`、
    `a[A] -->|2| b[B]` 之间随机漂移。用"先取节点 token、再看这一行有没有箭头"
    的两步法，能同时吃下这三种写法，且写错的输入只会退化成 fallback 而不是抛异常。
    """
    diagram = Diagram()
    for raw in (source or "").split("\n"):
        line = raw.strip()
        if not line or line.lower().startswith(("flowchart", "graph", "%%", "subgraph", "end")):
            continue
        has_arrow = bool(EDGE_ARROW.search(line))
        label_match = EDGE_LABEL.search(line)
        inline_label = (label_match.group(1).strip() if label_match else "")
        # 去掉 `|label|`，否则 `|` 会被当成节点名的一部分
        cleaned = EDGE_LABEL.sub(" ", line)
        tokens = [t for t in NODE_TOKEN.finditer(cleaned)]
        if not tokens:
            continue
        for match in tokens:
            node_id, bracket, paren, brace = match.group(1), match.group(2), match.group(3), match.group(4)
            label = (bracket or paren or brace or node_id).strip() or node_id
            existing = diagram.nodes.get(node_id)
            if existing is None or existing == node_id:
                diagram.nodes[node_id] = label
        if has_arrow and len(tokens) >= 2:
            src = tokens[0].group(1)
            dst = tokens[-1].group(1)
            if src != dst or len(tokens) > 2:
                diagram.edges.append((src, dst, inline_label))
    return diagram


def _layout(diagram: Diagram) -> dict[str, tuple[float, float]]:
    positions: dict[str, tuple[float, float]] = {}
    for idx, name in enumerate(diagram.nodes):
        row, col = divmod(idx, PER_ROW)
        positions[name] = (24 + col * (NODE_W + GAP_X), 24 + row * (NODE_H + GAP_Y))
    return positions


def render_svg(source: str, *, title: str = "") -> str:
    """把 Mermaid 子集渲染成内联 SVG（无外部依赖，可进页面也可进 PDF）。"""
    diagram = parse_mermaid(source)
    if diagram.empty:
        return (
            "<div class='diagram-fallback'>"
            f"<pre>{html.escape(source or '（无图表内容）')}</pre></div>"
        )
    positions = _layout(diagram)
    width = 24 * 2 + PER_ROW * NODE_W + (PER_ROW - 1) * GAP_X
    rows = (len(diagram.nodes) + PER_ROW - 1) // PER_ROW
    height = 24 * 2 + rows * NODE_H + (rows - 1) * GAP_Y

    parts = [
        f"<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 {width} {height}' role='img' "
        f"aria-label='{html.escape(title or '架构图')}' class='diagram-svg'>",
        "<defs><marker id='arrow' viewBox='0 0 10 10' refX='9' refY='5' markerWidth='7' markerHeight='7' "
        "orient='auto-start-reverse'><path d='M 0 0 L 10 5 L 0 10 z' fill='#3A4642'/></marker></defs>",
        "<style>.n{fill:#161D1B;stroke:#2A3330;rx:10}.t{fill:#E6EDEA;font:12px Inter,system-ui}"
        ".e{stroke:#3A4642;stroke-width:1.4;fill:none}.l{fill:#9FB0AA;font:10px Inter,system-ui}</style>",
    ]
    for src, dst, label in diagram.edges:
        if src not in positions or dst not in positions:
            continue
        x1, y1 = positions[src]
        x2, y2 = positions[dst]
        sx, sy = x1 + NODE_W / 2, y1 + NODE_H
        ex, ey = x2 + NODE_W / 2, y2
        if abs(y2 - y1) < 1:
            sx, sy = x1 + NODE_W, y1 + NODE_H / 2
            ex, ey = x2, y2 + NODE_H / 2
        mid_x, mid_y = (sx + ex) / 2, (sy + ey) / 2
        parts.append(
            f"<path class='e' d='M {sx:.0f} {sy:.0f} C {mid_x:.0f} {sy:.0f}, {mid_x:.0f} {ey:.0f}, {ex:.0f} {ey:.0f}' "
            "marker-end='url(#arrow)'/>"
        )
        if label:
            parts.append(f"<text class='l' x='{mid_x:.0f}' y='{mid_y:.0f}' text-anchor='middle'>{html.escape(label)}</text>")
    for name, (x, y) in positions.items():
        label = diagram.nodes[name]
        parts.append(f"<rect class='n' x='{x:.0f}' y='{y:.0f}' width='{NODE_W}' height='{NODE_H}' rx='10'/>")
        display = label if len(label) <= 22 else label[:21] + "…"
        parts.append(
            f"<text class='t' x='{x + NODE_W / 2:.0f}' y='{y + NODE_H / 2 + 4:.0f}' text-anchor='middle'>"
            f"{html.escape(display)}</text>"
        )
    parts.append("</svg>")
    return "".join(parts)


def cache_key(source: str) -> str:
    return "diagrams/" + hashlib.sha256(source.encode("utf-8")).hexdigest()[:32] + ".svg"


def render_and_store(source: str, *, title: str = "", course_id: str = "") -> str:
    """渲染并落盘，返回可对外使用的同源 URL（`/api/objects/diagrams/...`）。"""
    from repolearn.services import object_store

    svg = render_svg(source, title=title)
    prefix = f"{course_id}/" if course_id else ""
    key = prefix + cache_key(source).split("/", 1)[1]
    object_store.put("diagrams", key, svg)
    return object_store.public_url("diagrams", key)

"""模板降级生成（spec §3.5.4 状态 C）。

当 `@aragon-agent/core` 不可用（Gate 0 G1 失败）时，课程**仍然要能生成**，
但产出规则必须写死，否则"简化版课程"会变成无意义的占位文本。

规则（与 spec 一致，不自由发挥）：
* N5：按目录深度与入度选出 4 章节 12 课时的确定性骨架；
* N6：从每课时的代表文件里抽"文件头注释 + 顶层符号签名 + 被调用次数最高的 3 个函数"，
  用固定话术模板串成讲解与板书；
* N7：只输出 `static_inference`，不编造 `source_fact`；
* `quality_report.degraded=true` 且 `anchor_confidence="low"`。

这段代码是"稳健可靠"的底线：它必须在**没有 AI 服务**的机器上也能产出可学的内容，
因此不允许依赖任何模型调用。
"""

from __future__ import annotations

import re
from typing import Any

from repolearn.analysis.knowledge_graph import KnowledgeGraph
from repolearn.analysis.paths import is_test_path

SECTION_TITLES = {
    "overview": "第一层 · 宏观架构",
    "walkthrough": "第二层 · 全局走读",
    "deep_dive": "第三层 · 深入源码",
    "recap": "课程总结",
}

#: 每章节的课时配额（合计 12）
SECTION_QUOTA = {"overview": 3, "walkthrough": 3, "deep_dive": 5, "recap": 1}

_CHARS_PER_SECOND = 4.2


def seconds_for(text: str) -> int:
    """中文语速按 4.2 字/秒折算（与前端字幕推进口径一致）。"""
    return max(3, int(len(text) / _CHARS_PER_SECOND))


def _representative_files(kg: KnowledgeGraph) -> list[str]:
    """按"这个文件值不值得讲"排序出代表文件。

    回退链是刻意的：没有符号时用模块里出现过的任何文件，再没有才用模块 key
    （`README.md` 这类单文件模块的 key 恰好就是文件名）。

    **为什么不能只按"模块内符号数"排**（旧实现就是这样）：`tests/` 往往符号最多，
    于是 sherlock 的 12 个课时里有 10 个在讲 `test_probes.py` / `conftest.py`，
    而 `sherlock.py`（真正的入口）排在最后。学习者要的是产品代码，不是测试夹具。

    现在的排序键（越大越靠前）：
    * 产品代码优先（测试/夹具/示例/文档/第三方目录排到最后，而不是删掉——镜像很小
      的仓库可能"只有"这些文件，删掉会让模板课无内容可讲）；
    * 入度高的符号所在的文件优先（被调用得多，说明它在这门课里更重要）；
    * 文件名/目录名像入口的（main/cli/app/server）加分；
    * 最后用路径做确定性 tie-break（同一仓库两次生成必须得到同一门课）。
    """
    in_deg = kg.call_graph.in_degree
    per_file: dict[str, list] = {}
    for sym in kg.symbols:
        per_file.setdefault(sym.file, []).append(sym)

    def rank(path: str) -> tuple:
        """越小越靠前：产品代码、像入口的、入度高、符号多、路径字典序。"""
        symbols = per_file.get(path, [])
        calls = sum(in_deg.get(s.name, 0) for s in symbols)
        name = path.rsplit("/", 1)[-1].lower()
        looks_entry = any(h in name for h in ("main", "cli", "app", "server", "entrypoint"))
        return (
            1 if is_test_path(path) else 0,
            0 if looks_entry else 1,
            -calls,
            -len(symbols),
            path,
        )

    ordered = sorted(per_file, key=rank)

    for mod in kg.modules:
        if "." in mod.path and mod.path not in ordered:
            ordered.append(mod.path)
    return ordered


def file_header_comment(text: str, limit: int = 6) -> str:
    lines: list[str] = []
    for line in (text or "").split("\n")[:40]:
        stripped = line.strip()
        if not stripped:
            if lines:
                break
            continue
        if stripped.startswith(("#", "//", "/*", "*", '"""', "'''")):
            cleaned = re.sub(r'^[#/*"\'\s]+', "", stripped).strip()
            if cleaned:
                lines.append(cleaned)
            continue
        if lines:
            break
    return " ".join(lines)[:300]


def top_symbols(kg: KnowledgeGraph, path: str, limit: int = 3) -> list[dict]:
    in_deg = kg.call_graph.in_degree
    candidates = [s for s in kg.symbols if s.file == path]
    candidates.sort(key=lambda s: (-in_deg.get(s.name, 0), s.line_start))
    return [
        {"name": s.name, "kind": s.kind, "line_start": s.line_start, "line_end": s.line_end, "calls": in_deg.get(s.name, 0)}
        for s in candidates[:limit]
    ]


def build_template_curriculum(repo: dict, kg: KnowledgeGraph, read: Any) -> dict:
    """确定性骨架：章节配额固定，课时取自"符号最多的文件"。

    注意：这里必须用**真实文件路径**，不能用 `Module.path`。`Module.path` 是模块 key
    （多级目录下是 `pkg/sub` 这样的前缀，不是文件），拿它当锚点的 `file` 会让发布前
    校验报"锚点文件不存在"，整门课程回滚。这条 bug 只在多级目录的仓库上出现，
    单目录夹具测不出来——所以模板路径也必须用多级目录的夹具覆盖。
    """
    files = _representative_files(kg)
    if not files:
        files = [m.path for m in kg.modules] or ["README.md"]

    ordered_files = files[:12]

    sections: list[dict] = []
    cursor = 0
    for index, (section_key, quota) in enumerate(SECTION_QUOTA.items(), start=1):
        lessons: list[dict] = []
        for i in range(quota):
            path = ordered_files[(cursor + i) % len(ordered_files)]
            line = 1
            for sym in kg.symbols:
                if sym.file == path:
                    line = sym.line_start
                    break
            lessons.append(
                {
                    "key": f"{index}.{i + 1}",
                    "title": f"{path.split('/')[-1]} 走读（{i + 1}）" if quota > 1 else f"{path.split('/')[-1]} 总览",
                    "goal": f"能说出 {path} 里定义了哪些关键符号、它们之间的调用关系",
                    "minutes": 5,
                    "anchors": [{"file": path, "line_start": line, "line_end": line, "kind": "definition"}],
                }
            )
        cursor += quota
        sections.append({"key": section_key, "title": SECTION_TITLES[section_key], "minutes": 5 * quota, "lessons": lessons})

    return {
        "title": f"{repo.get('full_name', '仓库')} 带读课程（简化版）",
        "subtitle": "由静态分析生成 · 未启用 AI 生成",
        "summary_md": (
            f"这是一门为 `{repo.get('full_name', '')}` 自动生成的简化版课程。\n\n"
            "系统检测到 Agent 内核不可用，因此课程内容来自静态分析（符号、调用边、文件头注释），"
            "而不是模型讲解。它仍然可以带你走完整的三层结构，但讲解深度有限。\n\n"
            "配置好 AI 服务后，可以在课程页点「重新生成」获得完整版本。"
        ),
        "chain_id": "template_chain",
        "sections": sections,
    }


def build_template_lesson(
    *,
    lesson_plan: dict,
    kg: KnowledgeGraph,
    read: Any,
    trace_key: str | None = None,
) -> dict:
    """固定话术串讲：文件头注释 → 顶层符号签名 → 被调用最多的函数。"""
    anchors = [a for a in (lesson_plan.get("anchors") or []) if isinstance(a, dict)]
    path = str(anchors[0].get("file", "")) if anchors else ""
    try:
        text = read(path) if path else ""
    except Exception:  # noqa: BLE001 - 模板降级路径绝不允许因读失败而中断
        text = ""

    header = file_header_comment(text)
    symbols = top_symbols(kg, path, limit=3)
    name = path.split("/")[-1] if path else "这个文件"

    segments: list[dict] = []
    cursor = 0
    script: list[tuple[str, int | None]] = []

    intro = f"这一课时我们看 {name}。"
    if header:
        intro += f"文件开头的说明是：{header}"
    script.append((intro, 1))
    for sym in symbols:
        script.append(
            (
                f"从第 {sym['line_start']} 行开始定义了 {sym['kind']} {sym['name']}，"
                f"它在整个仓库里被引用 {sym['calls']} 次。",
                int(sym["line_start"]),
            )
        )
    if not symbols:
        script.append(("这个文件里没有抽取到可讲解的符号，我们只做文件级走读。", 1))
    script.append(("以上内容来自静态分析，不是模型的推断结论；完整讲解需要配置 AI 服务后重新生成。", None))

    for idx, (content, line) in enumerate(script):
        duration = seconds_for(content) * 1000
        segment: dict[str, Any] = {
            "id": f"s{idx}",
            "text": content,
            "start_ms": cursor,
            "end_ms": cursor + duration,
        }
        if line is not None and path:
            # 行区间必须落在文件内：模板用的是"符号起始行"，而它可能就在文件末尾，
            # `+2` 会越界。发布前校验会因此整门课程回滚（ANCHOR_STALE）——
            # 修在生成侧，而不是放宽校验：锚点越界是"可追溯"承诺的真实破裂。
            total_lines = max(1, str(text).count("\n") + (0 if str(text).endswith("\n") else 1))
            end_line = min(line + 2, total_lines)
            segment["focus"] = {"file": path, "line_start": min(line, total_lines), "line_end": end_line}
        segments.append(segment)
        cursor += duration

    quiz = []
    if symbols:
        correct = symbols[0]
        choices = [{"id": "a", "text": correct["name"]}]
        for j, other in enumerate([s for s in kg.symbols if s.name != correct["name"]][:2], start=1):
            choices.append({"id": chr(97 + j), "text": other.name})
        if len(choices) >= 2:
            quiz.append(
                {
                    "id": f"qz_{lesson_plan.get('key', '0')}",
                    "stem": f"下面哪个符号定义在 {name} 里？",
                    "choices": choices,
                    "answer_id": "a",
                    "explanation_md": f"`{correct['name']}` 定义在 `{path}` 第 {correct['line_start']} 行。",
                    "evidence": [
                        {
                            "file": path,
                            "line_start": correct["line_start"],
                            "line_end": correct["line_end"],
                            "kind": "definition",
                        }
                    ],
                    "difficulty": 1,
                    "kind": "recall",
                }
            )

    return {
        "key": str(lesson_plan.get("key", "1.1")),
        "title": str(lesson_plan.get("title", name)),
        "layer": str(lesson_plan.get("layer", "overview")),
        "minutes": int(lesson_plan.get("minutes", 5) or 5),
        "goal": lesson_plan.get("goal"),
        "steps": [
            {
                "index": 0,
                "title": f"{name} 静态走读",
                "duration_ms": max(3000, cursor),
                "timing_source": "estimated",
                "segments": segments,
                "board": {
                    "kind": "architecture",
                    "mermaid": kg.to_mermaid(12),
                    "nodes": [{"id": m.key, "label": m.path, "source": {"file": m.path, "line": 1}} for m in kg.modules[:8]],
                },
                "code_notes": [
                    {"file": path, "line": s["line_start"], "text": f"{s['kind']} {s['name']}"} for s in symbols
                ]
                if path
                else [],
            }
        ],
        "files": [{"path": path}] if path else [],
        "trace_key": trace_key,
        "quiz": quiz,
    }

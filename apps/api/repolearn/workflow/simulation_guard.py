"""Trace 校验与降级（spec §3.4 N7 / §6.4 / T-TRACE-1）。

这是"诚信"承诺的执行点。规则只有三条，但每条都必须真跑：

1. `source_fact` 必须带 evidence，且 evidence 能在镜像里定位到对应行——
   **不能定位就降级为 `teaching_simulation`，而不是删掉 evidence 蒙混过去**；
2. `teaching_simulation` 的变量必须带 `note:"示例值，非真实运行结果"`；
3. `source_fact` 占比 < 40% → `trace_quality="weak"`（不是失败，而是标注）。

选择"降级"而不是"删除该步"：删掉一步会让讲解出现逻辑跳跃（"然后呢？"），
而明确标注"这一步是推演"既保留可讲性，又不撒谎。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from repolearn.core.logging import get_logger

log = get_logger("simulation_guard")

SIMULATION_NOTE = "示例值，非真实运行结果"
WEAK_SOURCE_FACT_RATIO = 0.4


@dataclass
class TraceCheckResult:
    steps: list[dict] = field(default_factory=list)
    downgraded: int = 0
    dropped: int = 0
    warnings: list[dict] = field(default_factory=list)
    summary: dict = field(default_factory=dict)

    @property
    def quality(self) -> str:
        return str(self.summary.get("quality", "unknown"))


def _locate(read_lines: Callable[[str], int], anchor: dict) -> bool:
    """evidence 的每一行是否真实存在于镜像文件的合法行号范围内。"""
    path = str(anchor.get("file", ""))
    if not path:
        return False
    total = read_lines(path)
    if total <= 0:
        return False
    start = int(anchor.get("line_start", 0) or 0)
    end = int(anchor.get("line_end", start) or start)
    return 1 <= start <= end <= total


def guard_trace(
    trace: dict,
    read_lines: Callable[[str], int],
    *,
    lesson_key: str = "",
) -> TraceCheckResult:
    steps: list[dict] = []
    downgraded = 0
    dropped = 0
    warnings: list[dict] = []

    for step in trace.get("steps") or []:
        if not isinstance(step, dict):
            continue
        item = dict(step)
        certainty = str(item.get("certainty", "teaching_simulation"))
        evidence = [e for e in (item.get("evidence") or []) if isinstance(e, dict)]

        if certainty == "source_fact":
            verified = [e for e in evidence if _locate(read_lines, e)]
            if not verified:
                # 无法定位 → 降级。**不删步**，因为删步会让讲解出现跳跃。
                item["certainty"] = "static_inference" if evidence else "teaching_simulation"
                item["note"] = "原标注为源码事实，但无法在镜像中定位到对应行，已降级"
                downgraded += 1
                warnings.append(
                    {
                        "code": "CERTAINTY_DOWNGRADED",
                        "message": f"课时 {lesson_key} 的步骤「{item.get('title', '')}」证据无法定位，已降级",
                        "severity": "warning",
                        "node": "simulate_trace",
                    }
                )
            else:
                item["evidence"] = verified

        if item.get("certainty") == "teaching_simulation":
            variables = []
            for var in item.get("variables") or []:
                if not isinstance(var, dict):
                    continue
                v = dict(var)
                # 变量值必须自带"这是示例"的标注；模型常常忘，所以我们补上。
                if not str(v.get("note", "")).strip():
                    v["note"] = SIMULATION_NOTE
                variables.append(v)
            item["variables"] = variables

        if not str(item.get("title", "")).strip():
            dropped += 1
            continue
        steps.append(item)

    summary = summarize(steps)
    if not steps:
        warnings.append(
            {
                "code": "TRACE_EMPTY",
                "message": f"课时 {lesson_key} 的执行轨迹在校验后为空",
                "severity": "warning",
                "node": "simulate_trace",
            }
        )
    elif summary["quality"] == "weak":
        warnings.append(
            {
                "code": "TRACE_WEAK",
                "message": f"课时 {lesson_key} 的执行链以推演为主（源码事实占比 {summary['source_fact_ratio']:.0%}）",
                "severity": "info",
                "node": "simulate_trace",
            }
        )

    return TraceCheckResult(steps=steps, downgraded=downgraded, dropped=dropped, warnings=warnings, summary=summary)


def summarize(steps: list[dict]) -> dict:
    counts = {"source_fact": 0, "static_inference": 0, "teaching_simulation": 0}
    for step in steps:
        key = str(step.get("certainty", "teaching_simulation"))
        counts[key if key in counts else "teaching_simulation"] += 1
    total = max(1, len(steps))
    ratio = counts["source_fact"] / total
    return {
        "total": len(steps),
        "counts": counts,
        "source_fact_ratio": round(ratio, 3),
        "quality": "ok" if ratio >= WEAK_SOURCE_FACT_RATIO else "weak",
    }


def template_trace(chain: dict, lesson_key: str) -> dict:
    """模板降级时的轨迹（spec §3.5.4 状态 C）。

    **只输出 `static_inference`**，不编造 `source_fact`。这条规则如果不写死，
    "简化版课程"会变成"看起来有证据、其实全是编的课程"——那比没有课程更糟。
    """
    steps: list[dict] = []
    for idx, step in enumerate(chain.get("steps") or []):
        if not isinstance(step, dict):
            continue
        evidence = []
        if step.get("file") and step.get("line"):
            evidence.append(
                {
                    "file": step["file"],
                    "line_start": int(step["line"]),
                    "line_end": int(step["line"]),
                    "symbol": step.get("symbol", ""),
                    "kind": "call_site",
                }
            )
        steps.append(
            {
                "index": idx,
                "title": f"{step.get('symbol', '调用')}",
                "certainty": "static_inference",
                "detail": f"从静态调用图推断：{step.get('symbol', '')} 位于 {step.get('file', '')} 第 {step.get('line', 0)} 行",
                "evidence": evidence,
                "variables": [],
            }
        )
    return {
        "key": f"trace_{lesson_key}",
        "title": f"调用链：{chain.get('title', '')}",
        "steps": steps,
    }

"""产出修复（spec §3.4 N5/N6 的"修复提示重试 2 次"）。

修复策略是**有限次、有理由、有兜底**的：
* 最多 2 次。第 3 次几乎不会成功，而每次都是真金白银；
* 每次只把**具体错误**回灌（不复述整份 schema）——复述会把上下文吃满，
  反而挤掉真正需要的代码片段；
* 修不好就退到确定性模板（N5）或进 `failed_lessons`（N6），**绝不静默发布**
  一份不合规的内容：那会让"可追溯"变成假承诺。
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from repolearn.core.logging import get_logger
from repolearn.workflow.parsing import parse_and_validate

log = get_logger("repair")

MAX_REPAIR_ATTEMPTS = 2

#: 调用一次模型：`(system, prompt) -> (text, usage)`
RunFn = Callable[[str, str], Awaitable[tuple[str, dict]]]


@dataclass
class RepairOutcome:
    ok: bool
    data: dict[str, Any] = field(default_factory=dict)
    attempts: int = 0
    errors: list[str] = field(default_factory=list)
    usage: dict[str, int] = field(default_factory=dict)


async def produce_validated(
    *,
    run: RunFn,
    system: str,
    prompt: str,
    schema_name: str,
    extra_checks: Callable[[dict], list[str]] | None = None,
    on_retry: Callable[[int, list[str]], None] | None = None,
    max_attempts: int = MAX_REPAIR_ATTEMPTS,
) -> RepairOutcome:
    """调用模型 → 校验 → 带错误重试，直到合法或用尽次数。"""
    from repolearn.workflow.prompts import repair_prompt

    errors: list[str] = []
    total = {"tokens_in": 0, "tokens_out": 0, "turns": 0}
    current_prompt = prompt
    previous = ""
    for attempt in range(1, max_attempts + 2):
        text, usage = await run(system, current_prompt)
        total["tokens_in"] += int(usage.get("tokens_in", 0) or 0)
        total["tokens_out"] += int(usage.get("tokens_out", 0) or 0)
        total["turns"] += 1
        previous = text
        parsed = parse_and_validate(text, schema_name)
        errors = parsed.errors
        if parsed.ok:
            if extra_checks is not None:
                errors = extra_checks(parsed.data)
                if not errors:
                    return RepairOutcome(ok=True, data=parsed.data, attempts=attempt, usage=total)
            else:
                return RepairOutcome(ok=True, data=parsed.data, attempts=attempt, usage=total)
        log.warning("output_invalid", schema=schema_name, attempt=attempt, errors=errors[:5])
        if attempt > max_attempts:
            break
        if on_retry is not None:
            on_retry(attempt, errors)
        current_prompt = f"{prompt}\n\n{repair_prompt(errors, previous)}"
    return RepairOutcome(ok=False, attempts=max_attempts + 1, errors=errors, usage=total)


def strip_json_noise(text: str) -> str:
    """把常见的"半 JSON"噪声去掉（供日志与模板兜底使用，不用于校验）。"""
    out = text.strip()
    for fence in ("```json", "```"):
        if out.startswith(fence):
            out = out[len(fence) :]
    if out.endswith("```"):
        out = out[:-3]
    return out.strip()

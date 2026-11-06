"""结构化产出的解析与二次校验（spec §3.5.2 / §4.3）。

**一处定义、两侧校验**：JSON Schema 在 `packages/contracts/schemas/*.json`，
Kernel 用 zod 从同一份定义生成，Python 用 `jsonschema` 校验同一份文件。
模型输出漂移因此会在两个地方同时暴露，而不是某一侧静默通过。

⚠️ 这里**故意不用 Pydantic 做第二套定义**：两套定义必然缓慢分叉，而分叉的表现是
"Kernel 说合法、Python 说非法"，排查成本极高。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

import jsonschema

from repolearn.core.config import REPO_ROOT
from repolearn.core.logging import get_logger

log = get_logger("parsing")

SCHEMA_DIR = REPO_ROOT / "packages" / "contracts" / "schemas"
_cache: dict[str, dict] = {}

_FENCE = re.compile(r"```(?:json)?\s*(.+?)```", re.DOTALL)


@dataclass
class ParseResult:
    ok: bool
    data: dict[str, Any] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    raw: str = ""


def load_schema(name: str) -> dict | None:
    if name in _cache:
        return _cache[name]
    path = SCHEMA_DIR / f"{name}.json"
    if not path.is_file():
        return None
    try:
        schema = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        log.error("schema_load_failed", name=name, error=str(exc))
        return None
    _cache[name] = schema
    return schema


def validate(name: str, payload: Any) -> list[str]:
    """返回人类可读的错误列表（空 = 合法）。错误要能直接回灌给模型。"""
    schema = load_schema(name)
    if schema is None:
        return [f"找不到 schema: {name}"]
    validator = jsonschema.Draft7Validator(schema)
    errors: list[str] = []
    for err in sorted(validator.iter_errors(payload), key=lambda e: list(e.absolute_path)):
        path = ".".join(str(p) for p in err.absolute_path) or "<root>"
        errors.append(f"{path}: {err.message}")
    return errors[:20]


def extract_json(text: str) -> str | None:
    """从模型输出里取出 JSON 文本。

    三类必现失败都要兜住：markdown 代码围栏、前后夹叙夹议、尾逗号。
    **不修 JSON 结构**（不改引号、不补括号）——猜错的修复比直接报错更危险。
    """
    if not text:
        return None
    fenced = _FENCE.search(text)
    candidates: list[str] = []
    if fenced:
        candidates.append(fenced.group(1))
    candidates.append(text)
    for candidate in candidates:
        start_obj = candidate.find("{")
        start_arr = candidate.find("[")
        starts = [s for s in (start_obj, start_arr) if s >= 0]
        if not starts:
            continue
        start = min(starts)
        end = max(candidate.rfind("}"), candidate.rfind("]"))
        if end <= start:
            continue
        snippet = candidate[start : end + 1]
        try:
            json.loads(snippet)
            return snippet
        except json.JSONDecodeError:
            cleaned = re.sub(r",\s*([}\]])", r"\1", snippet)
            try:
                json.loads(cleaned)
                return cleaned
            except json.JSONDecodeError:
                continue
    return None


def parse_and_validate(text: str, schema_name: str) -> ParseResult:
    snippet = extract_json(text)
    if snippet is None:
        return ParseResult(ok=False, errors=["没有找到可解析的 JSON 产出"], raw=text[:2000])
    try:
        payload = json.loads(snippet)
    except json.JSONDecodeError as exc:
        return ParseResult(ok=False, errors=[f"JSON 解析失败：{exc}"], raw=text[:2000])
    errors = validate(schema_name, payload)
    return ParseResult(ok=not errors, data=payload if not errors else {}, errors=errors, raw=text[:2000])


# --------------------------------------------------------------------------- #
# 课程领域的一致性校验（schema 管形状，这里管语义）                            #
# --------------------------------------------------------------------------- #


def check_curriculum(curriculum: dict) -> list[str]:
    """4 章节齐全、课时数 10–12、每课时有 goal。

    schema 只能约束"有 sections"，而"是否覆盖四层"是产品语义，必须单独查。
    """
    errors: list[str] = []
    sections = curriculum.get("sections") or []
    keys = {s.get("key") for s in sections if isinstance(s, dict)}
    required = {"overview", "walkthrough", "deep_dive", "recap"}
    missing = required - keys
    if missing:
        errors.append(f"缺少章节：{', '.join(sorted(missing))}")
    lessons = [item for s in sections if isinstance(s, dict) for item in (s.get("lessons") or [])]
    if len(lessons) < 10:
        errors.append(f"课时数量 {len(lessons)} 少于 10")
    if len(lessons) > 12:
        errors.append(f"课时数量 {len(lessons)} 多于 12")
    seen: set[str] = set()
    for lesson in lessons:
        key = str(lesson.get("key", ""))
        if not key:
            errors.append("存在没有 key 的课时")
            continue
        if key in seen:
            errors.append(f"课时 key 重复：{key}")
        seen.add(key)
        if not str(lesson.get("goal", "")).strip():
            errors.append(f"课时 {key} 缺少 goal")
    return errors


def check_segments(steps: list[dict]) -> list[str]:
    """`segments` 必须连续覆盖 `[0, duration_ms]` 且不重叠（spec §5.3 / §6.3）。

    这条校验如果不做，播放器的表现是"字幕在 0.8 秒时闪一下再跳回开头"——
    用户会以为是性能问题，实际是数据错。
    """
    errors: list[str] = []
    for step in steps:
        duration = int(step.get("duration_ms", 0) or 0)
        segments = step.get("segments") or []
        if not segments:
            errors.append(f"step {step.get('index')} 没有 segments")
            continue
        ordered = sorted(segments, key=lambda s: int(s.get("start_ms", 0) or 0))
        if int(ordered[0].get("start_ms", 0) or 0) != 0:
            errors.append(f"step {step.get('index')} 的首段未从 0 开始")
        cursor = 0
        for seg in ordered:
            start = int(seg.get("start_ms", 0) or 0)
            end = int(seg.get("end_ms", 0) or 0)
            if end <= start:
                errors.append(f"step {step.get('index')} 段 {seg.get('id')} 的 end_ms <= start_ms")
            if start > cursor:
                errors.append(f"step {step.get('index')} 在 {cursor}–{start} ms 之间有空洞")
            cursor = max(cursor, end)
        if duration and abs(cursor - duration) > max(500, int(duration * 0.02)):
            errors.append(f"step {step.get('index')} 的段总长 {cursor} 与 duration_ms {duration} 不匹配")
    return errors


def check_quiz(quiz: list[dict]) -> list[str]:
    errors: list[str] = []
    for item in quiz:
        choices = {c.get("id") for c in (item.get("choices") or []) if isinstance(c, dict)}
        answer = item.get("answer_id")
        if answer not in choices:
            errors.append(f"题目 {item.get('id')} 的 answer_id 不在选项里")
        if not item.get("evidence"):
            errors.append(f"题目 {item.get('id')} 缺少 evidence")
    return errors


def check_anchors(anchors: list[dict], file_lines: dict[str, int]) -> list[str]:
    """锚点存在性校验（spec §6.2 / T-ANCHOR-1）。这是"可追溯"承诺的唯一执行点。"""
    errors: list[str] = []
    for anchor in anchors:
        path = str(anchor.get("file", ""))
        if path not in file_lines:
            errors.append(f"锚点文件不存在：{path}")
            continue
        total = file_lines[path]
        start = int(anchor.get("line_start", 0) or 0)
        end = int(anchor.get("line_end", 0) or 0)
        if start < 1 or end < start:
            errors.append(f"锚点行号非法：{path}:{start}-{end}")
        elif total and end > total:
            errors.append(f"锚点越界：{path}:{end} 超出文件行数 {total}")
    return errors

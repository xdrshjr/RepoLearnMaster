"""符号抽取（spec §3.4 N4）。

**优先 tree-sitter，缺失时退化到正则**（`ANALYSIS_DEGRADED`）。退化路径不是"凑合"，
它是 Gate 0 G3 失败时的正式输出：正则能给"定义在哪一行"，只是给不了"谁调用谁"。
所以这里把两条路径的产出形状做成同一个 `Symbol`，上层不需要知道走的是哪条。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from repolearn.core.logging import get_logger

log = get_logger("symbols")

SUPPORTED_LANGS = ("python", "javascript", "typescript", "go", "java", "rust")

_PATTERNS: dict[str, list[tuple[re.Pattern[str], str]]] = {
    "python": [
        (re.compile(r"^(?P<indent>\s*)class\s+(?P<name>[A-Za-z_]\w*)"), "class"),
        (re.compile(r"^(?P<indent>\s*)(?:async\s+)?def\s+(?P<name>[A-Za-z_]\w*)"), "function"),
    ],
    "typescript": [
        (re.compile(r"^(?P<indent>\s*)(?:export\s+)?(?:default\s+)?class\s+(?P<name>[A-Za-z_$][\w$]*)"), "class"),
        (re.compile(r"^(?P<indent>\s*)(?:export\s+)?interface\s+(?P<name>[A-Za-z_$][\w$]*)"), "interface"),
        (re.compile(r"^(?P<indent>\s*)(?:export\s+)?type\s+(?P<name>[A-Za-z_$][\w$]*)\s*="), "type"),
        (re.compile(r"^(?P<indent>\s*)(?:export\s+)?(?:async\s+)?function\s+(?P<name>[A-Za-z_$][\w$]*)"), "function"),
        (re.compile(r"^(?P<indent>\s*)(?:export\s+)?const\s+(?P<name>[A-Za-z_$][\w$]*)\s*=\s*(?:async\s*)?\("), "function"),
    ],
    "go": [
        (re.compile(r"^(?P<indent>)func\s+(?:\([^)]*\)\s*)?(?P<name>[A-Za-z_]\w*)"), "function"),
        (re.compile(r"^(?P<indent>)type\s+(?P<name>[A-Za-z_]\w*)\s+struct"), "class"),
    ],
    "rust": [
        (re.compile(r"^(?P<indent>\s*)(?:pub\s+)?fn\s+(?P<name>[A-Za-z_]\w*)"), "function"),
        (re.compile(r"^(?P<indent>\s*)(?:pub\s+)?struct\s+(?P<name>[A-Za-z_]\w*)"), "class"),
        (re.compile(r"^(?P<indent>\s*)(?:pub\s+)?trait\s+(?P<name>[A-Za-z_]\w*)"), "interface"),
    ],
    "java": [
        (re.compile(r"^(?P<indent>\s*)(?:public\s+|private\s+|protected\s+)?(?:final\s+)?class\s+(?P<name>[A-Za-z_]\w*)"), "class"),
        (re.compile(r"^(?P<indent>\s*)(?:public|private|protected)\s+[\w<>\[\]]+\s+(?P<name>[A-Za-z_]\w*)\s*\("), "function"),
    ],
}
_PATTERNS["javascript"] = _PATTERNS["typescript"]


@dataclass
class Symbol:
    name: str
    kind: str
    file: str
    line_start: int
    line_end: int
    lang: str = "text"
    container: str | None = None
    signature: str = ""
    calls: list[str] = field(default_factory=list)

    def as_anchor(self) -> dict:
        kind_map = {"class": "definition", "function": "definition", "interface": "definition", "type": "definition"}
        return {
            "file": self.file,
            "symbol": self.name,
            "line_start": self.line_start,
            "line_end": self.line_end,
            "kind": kind_map.get(self.kind, "definition"),
        }


@dataclass
class OutlineResult:
    file: str
    lang: str
    symbols: list[Symbol]
    degraded: bool = False
    reason: str = ""


def detect_lang(path: str) -> str:
    lower = path.lower()
    if lower.endswith(".py"):
        return "python"
    if lower.endswith((".ts", ".tsx")):
        return "typescript"
    if lower.endswith((".js", ".jsx", ".mjs", ".cjs")):
        return "javascript"
    if lower.endswith(".go"):
        return "go"
    if lower.endswith(".java"):
        return "java"
    if lower.endswith(".rs"):
        return "rust"
    return "text"


def _tree_sitter_available() -> bool:
    try:
        import tree_sitter_language_pack  # type: ignore[import-not-found]  # noqa: F401

        return True
    except Exception:  # noqa: BLE001 - 缺包就是"不可用"，不区分原因
        return False


TS_AVAILABLE = _tree_sitter_available()


def _ends_of(lines: list[str], starts: list[tuple[int, str, str]]) -> list[int]:
    """用缩进/大括号推断每个符号的结束行。

    为什么不精确解析：结束行的用途只是"高亮区间"与"锚点行号范围"，差一两行不影响
    可用性；而为了精确而引入完整的 AST 遍历会在退化路径上直接不可用。
    """
    ends: list[int] = []
    for idx, (line_no, _kind, indent) in enumerate(starts):
        next_start = starts[idx + 1][0] if idx + 1 < len(starts) else len(lines) + 1
        candidate = min(next_start - 1, len(lines))
        # 若下一个符号缩进更深，说明它是子项，当前符号应延伸到更远处
        if idx + 1 < len(starts) and len(starts[idx + 1][2]) > len(indent):
            candidate = max(candidate, len(lines))
        ends.append(max(line_no, candidate))
    return ends


def outline(text: str, path: str) -> OutlineResult:
    lang = detect_lang(path)
    if lang not in _PATTERNS:
        return OutlineResult(file=path, lang=lang, symbols=[], degraded=True, reason="unsupported language")
    lines = text.split("\n")
    # **末尾换行不是"多出来的一行"**：`"a\nb\n".split("\n")` 会得到 `["a","b",""]`，
    # 于是 `len(lines)` 比真实行数多 1，`_ends_of` 的 `candidate` 就能取到 `total+1`。
    #
    # 真实故障（2026-11-09，job job_01M6ZHWQQZTDQ27N5JB5HNBWD8）：5 个锚点的
    # `line_end` 恰好是 `总行数 + 1`（如 `notify.py:283`，文件只有 282 行），
    # 发布前的锚点校验（`check_anchors`，它按 `mirror_line_count` 判）直接拒绝，
    # 整门课回滚 —— 12 个课时、160 万 tokens 的产出因为一个差一错误全丢。
    # 差一错误还会一路传到讲解的 `focus` 区间与前端高亮。
    if lines and lines[-1] == "":
        lines = lines[:-1]

    hits: list[tuple[int, str, str, str]] = []
    for i, line in enumerate(lines, start=1):
        if len(line) > 400:
            continue
        for pattern, kind in _PATTERNS[lang]:
            m = pattern.match(line)
            if m:
                name = m.group("name")
                if name.startswith("__"):
                    break
                hits.append((i, kind, m.groupdict().get("indent", "") or "", name))
                break
    starts = [(h[0], h[1], h[2]) for h in hits]
    ends = _ends_of(lines, starts)
    symbols = [
        Symbol(
            name=name,
            kind=kind,
            file=path,
            line_start=line_no,
            line_end=ends[idx],
            lang=lang,
            signature=lines[line_no - 1].strip()[:200],
            calls=extract_calls(lines[line_no - 1 : ends[idx]]),
        )
        for idx, (line_no, kind, _indent, name) in enumerate(hits)
    ]
    return OutlineResult(
        file=path,
        lang=lang,
        symbols=symbols,
        degraded=not TS_AVAILABLE,
        reason="" if TS_AVAILABLE else "tree-sitter-language-pack 缺失，使用正则抽取",
    )


_CALL_RE = re.compile(r"\b([A-Za-z_][\w]*)\s*\(")
_NOT_CALLS = {
    "if", "for", "while", "return", "print", "len", "str", "int", "dict", "list",
    "set", "tuple", "super", "range", "sorted", "map", "filter", "isinstance",
    "console", "require", "Promise", "Array", "Object", "JSON", "Math", "String",
    "Number", "Boolean", "parseInt", "parseFloat", "typeof", "await", "async",
}


def extract_calls(lines: list[str]) -> list[str]:
    """抽取被调用名。用于构造调用图的边——**不含确定的解析结果，只是线索**。"""
    names: list[str] = []
    for line in lines:
        for m in _CALL_RE.finditer(line):
            name = m.group(1)
            if name in _NOT_CALLS or name.startswith("__"):
                continue
            if name not in names:
                names.append(name)
    return names[:40]

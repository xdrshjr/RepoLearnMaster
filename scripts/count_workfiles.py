"""解析 spec §4 的七张工作量表格并统计数据（`T-DOC-2` 的执行体）。

用法：

    python scripts/count_workfiles.py docs/plans/repo-learn-hardening/spec.md
    python scripts/count_workfiles.py docs/plans/repo-learn-hardening/spec.md --json

默认输出**一行**，字段名固定（`T-DOC-2` 逐字比对的就是这一行）：

    rows=86 unique=81 新=39 改=43 生成=4

口径（与 spec §4.6 末行"规模"段的算式 `39+43+4 = 86`、`86 − 5 = 81` 一致）：

* 只统计 `### 4.x` 标题之后、下一个标题之前的 markdown 表格（§4.1–§4.6 六张）；
* 一行 = 一个数据行，判据是第一列是纯数字编号（`| 12 | ... |`），表头与
  `|---|` 分隔行自然被排除；
* 文件路径取第二列的反引号内容；类型取第三列（`新` / `改` / `生成`）；
* `unique` 按**路径归一化**后去重：去反引号、反斜杠统一成正斜杠、去掉 `./` 前缀、
  折叠重复斜杠、去掉首尾斜杠。大小写**不动**：仓库里没有同名不同大小写的
  文件，而擅自小写化会在大小写敏感的文件系统上把两个不同文件算成一个。

为什么必须有这个脚本（评审 P2-1）：v1 的"75 行 / 68 唯一 / 33+32+3"三个口径
互相打架，靠人工改数字改不出可信的清单。这里给出唯一算法，由 `T-DOC-2` 在门禁里
跑同一条命令比对 spec 自己的数字——任何一次"加了文件忘了改数字"当场红。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

#: 类型列的合法取值。出现第四种一律失败：静默丢弃会让 `rows` 与三数之和不再自洽。
KINDS = ("新", "改", "生成")

#: 六张小节的标题：`### 4.1` … `### 4.6`（`#### 5.1.1` 之类的子标题会关掉状态）。
SECTION_RE = re.compile(r"^### 4\.\d+")
NUMBER_RE = re.compile(r"^\d+$")
TICK_RE = re.compile(r"`([^`]+)`")
#: 拆表格列；`\|` 是单元格内的转义竖线，不拆。
CELL_SPLIT_RE = re.compile(r"(?<!\\)\|")

DEFAULT_SPEC = "docs/plans/repo-learn-hardening/spec.md"
EXPECTED_SECTIONS = 7


def normalize_path(raw: str) -> str:
    """把表格里的路径单元格归一化成唯一性比较用的形状。"""
    text = raw.strip()
    if len(text) >= 2 and text.startswith("`") and text.endswith("`"):
        text = text[1:-1]
    text = text.replace("\\", "/")
    while "//" in text:
        text = text.replace("//", "/")
    while text.startswith("./"):
        text = text[2:]
    return text.strip().strip("/")


def parse_rows(text: str) -> list[tuple[str, str, str]]:
    """返回 `(编号, 归一化路径, 类型)` 列表；只认 §4.x 小节里的数据行。"""
    rows: list[tuple[str, str, str]] = []
    in_section = False
    for line in text.splitlines():
        if line.startswith("#"):
            in_section = bool(SECTION_RE.match(line))
            continue
        if not in_section or not line.lstrip().startswith("|"):
            continue
        cells = [cell.strip() for cell in CELL_SPLIT_RE.split(line.strip().strip("|"))]
        if len(cells) != 4:
            continue
        number, path_cell, kind = cells[0], cells[1], cells[2]
        if not NUMBER_RE.match(number):
            continue
        ticked = TICK_RE.search(path_cell)
        path = normalize_path(ticked.group(1) if ticked else path_cell)
        if not path:
            continue
        rows.append((number, path, kind))
    return rows


def count_sections(text: str) -> int:
    return sum(1 for line in text.splitlines() if SECTION_RE.match(line))


def summarize(rows: list[tuple[str, str, str]]) -> dict[str, object]:
    files = [path for _, path, _ in rows]
    kinds: dict[str, int] = {}
    for _, _, kind in rows:
        kinds[kind] = kinds.get(kind, 0) + 1
    unknown = sorted(k for k in kinds if k not in KINDS)
    if unknown:
        raise SystemExit(
            f"类型列出现未识别的取值：{unknown}。合法取值只有 {'/'.join(KINDS)}；"
            "请先改表格再跑本脚本，不要让它被静默忽略。"
        )
    seen: set[str] = set()
    dups: list[str] = []
    for path in files:
        if path in seen and path not in dups:
            dups.append(path)
        seen.add(path)
    summary: dict[str, object] = {
        "rows": len(rows),
        "unique": len(seen),
        "新": kinds.get("新", 0),
        "改": kinds.get("改", 0),
        "生成": kinds.get("生成", 0),
    }
    summary["dups"] = sorted(dups)
    return summary


def _utf8_stdout() -> None:
    """管道/重定向时把 stdout 钉成 UTF-8。

    字段名里有 `新` / `改` / `生成`，而 Windows 的管道默认用系统 ANSI 代码页
    （cp936）编码——那会让 `T-DOC-2` 的子进程按 UTF-8 解码时直接拿到乱码。
    交互式终端保持原样：Python 写控制台走的是宽字符 API，中文本来就显示得对。
    """
    if sys.stdout.isatty():
        return
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    except (AttributeError, ValueError):  # 老解释器或被替换过的 stdout
        pass


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="统计 spec §4 六张工作量表格的行数 / 唯一文件数 / 类型分布",
    )
    parser.add_argument("spec", nargs="?", default=DEFAULT_SPEC, help=f"spec 文件路径（默认 {DEFAULT_SPEC}）")
    parser.add_argument("--json", action="store_true", help="输出 JSON 而不是单行 key=value")
    args = parser.parse_args(argv)

    _utf8_stdout()

    path = Path(args.spec)
    if not path.is_file():
        print(f"找不到 spec 文件：{path}", file=sys.stderr)
        return 2

    text = path.read_text(encoding="utf-8")
    rows = parse_rows(text)
    if not rows:
        print(f"在 {path} 里没解析到任何 §4.x 表格数据行", file=sys.stderr)
        return 2

    sections = count_sections(text)
    if sections != EXPECTED_SECTIONS:
        # 不退出：小节数变了不代表统计错，但读者应当知道口径被改过。
        print(f"警告：找到 {sections} 个 §4.x 小节（预期 {EXPECTED_SECTIONS}）", file=sys.stderr)

    summary = summarize(rows)
    if args.json:
        print(json.dumps(summary, ensure_ascii=False, sort_keys=False))
    else:
        line = (
            f"rows={summary['rows']} unique={summary['unique']} "
            f"新={summary['新']} 改={summary['改']} 生成={summary['生成']}"
        )
        print(line)

    total = int(summary["新"]) + int(summary["改"]) + int(summary["生成"])  # type: ignore[arg-type]
    if total != summary["rows"]:
        print(
            f"警告：类型合计 {total} ≠ 行数 {summary['rows']}（表格里有多余类型或漏行）",
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

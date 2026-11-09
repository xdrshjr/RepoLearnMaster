"""`outline()` 的行号必须落在文件内（T-ANCHOR-2）。

真实现场（2026-11-09，job `job_01M6ZHWQQZTDQ27N5JB5HNBWD8`）：

    sherlock_project/notify.py      只有 282 行，锚点写 268–283
    sherlock_project/sites.py       只有 258 行，锚点写 224–259
    sherlock_project/result.py      只有  88 行，锚点写  30–89
    tests/test_probes.py            只有 105 行，锚点写  98–106
    tests/test_validate_targets.py  只有 100 行，锚点写  76–101

**全部恰好多 1 行**。根因在 `analysis/symbols.py::outline`：

    lines = text.split("\\n")      # "a\\nb\\n" → ["a", "b", ""] ← 多出一个空元素

于是 `len(lines)` 比真实行数多 1，`_ends_of` 的 `candidate = min(..., len(lines))`
就能取到 `总行数 + 1`。这个差一错误有两个后果：

1. 锚点候选集里带着越界的 `line_end`，模型照抄进 `focus`；
2. 发布前 `check_anchors`（按 `mirror_line_count` 判）拒绝整门课 —— 12 个课时、
   160 万 tokens 的产出因为 1 行作废。

正常维护这段代码的人只会看到"最后一门课又被回滚了"，看不出是分析层的差一错误。
"""

from __future__ import annotations

from repolearn.analysis.symbols import outline

SOURCE = """import os


def alpha():
    return 1


class Beta:
    def gamma(self):
        return 2
"""

#: `SOURCE` 的真实行数：`len(SOURCE.splitlines())`
TOTAL_LINES = len(SOURCE.splitlines())


def test_line_end_never_exceeds_the_file_length():
    """结尾带换行的源码不能让 `line_end` 越界。"""
    result = outline(SOURCE, "pkg/mod.py")
    assert result.symbols, "至少要抽出两个符号"
    assert SOURCE.endswith("\n")
    for symbol in result.symbols:
        assert symbol.line_end <= TOTAL_LINES, f"{symbol.name} 的结束行 {symbol.line_end} 越界（共 {TOTAL_LINES} 行）"
        assert 1 <= symbol.line_start <= symbol.line_end


def test_last_symbol_of_a_file_ends_on_the_last_line():
    """最后一个符号延伸到文件末尾时，结束行必须是**最后一行**，不是它后面那行。"""
    result = outline(SOURCE, "pkg/mod.py")
    last = max(result.symbols, key=lambda s: s.line_start)
    assert last.line_end == TOTAL_LINES


def test_file_without_trailing_newline_behaves_the_same():
    text = SOURCE.rstrip("\n")
    result = outline(text, "pkg/mod.py")
    total = len(text.splitlines())
    for symbol in result.symbols:
        assert symbol.line_end <= total


def test_single_line_file_does_not_crash():
    result = outline("x = 1\n", "pkg/one.py")
    assert result.symbols == []

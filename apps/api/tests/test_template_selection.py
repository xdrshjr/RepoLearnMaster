"""模板降级课的**选材**：不要把测试夹具当成"这门课的主线"（T-QLT-1/T-QLT-2）。

真实现场（sherlock-project/sherlock @ c588d7c8，模板降级轮，浏览器实测）：

    第一层·宏观架构   test_probes.py / sherlock_interactives.py / test_validate_targets.py
    第二层·全局走读   conftest.py / test_unicode.py / few_test_basic.py
    第三层·深入源码   test_manifest.py / test_ux.py / test_version.py / notify.py / sherlock.py
    完课总结          result.py
    知识图入口点      ["TestLiveTargets", "Test_All_Targets", "summarize_junit_xml"]

也就是说：12 个课时里 9 个在讲 `tests/`，真正的入口 `sherlock.py` 排在第三层倒数第二，
而"这门课的入口"被宣布为两个测试类。根因是排序键只有"模块内符号数"——`tests/`
符号最多，于是它永远赢。

这不是"深度不够"（那是降级本来就承认的），而是**讲错了地方**。
"""

from __future__ import annotations

import pytest

from repolearn.analysis.callgraph import build_call_graph
from repolearn.analysis.knowledge_graph import build_knowledge_graph
from repolearn.analysis.paths import is_test_path
from repolearn.analysis.symbols import OutlineResult, Symbol
from repolearn.workflow.template import build_template_curriculum

# --------------------------------------------------------------------------- #
# 夹具：照抄 sherlock 的真实形状（产品代码 4 个文件 + tests/ 8 个文件）
# --------------------------------------------------------------------------- #


def _sym(name: str, file: str, line: int, calls: list[str] | None = None) -> Symbol:
    return Symbol(
        name=name,
        kind="function",
        file=file,
        line_start=line,
        line_end=line + 20,
        calls=calls or [],
    )


SHERLOCK_SYMBOLS = [
    # 产品代码：被调用多，但文件少
    _sym("sherlock", "sherlock_project/sherlock.py", 172, ["query_site", "QueryNotify"]),
    _sym("main", "sherlock_project/sherlock.py", 40, ["sherlock"]),
    _sym("query_site", "sherlock_project/sherlock.py", 300, ["QueryResult"]),
    _sym("QueryNotify", "sherlock_project/notify.py", 14, ["QueryResult"]),
    _sym("QueryResult", "sherlock_project/result.py", 10, []),
    _sym("load_sites", "sherlock_project/sites.py", 30, []),
    # tests/：文件多、符号多、几乎不被调用
    _sym("simple_query", "tests/test_probes.py", 11, []),
    _sym("TestLiveTargets", "tests/test_probes.py", 23, []),
    _sym("test_known_positives", "tests/test_probes.py", 40, []),
    _sym("sites_info", "tests/conftest.py", 8, []),
    _sym("test_utf8", "tests/test_unicode.py", 5, []),
    _sym("test_ux_output", "tests/test_ux.py", 7, []),
    _sym("test_manifest", "tests/test_manifest.py", 6, []),
    _sym("validate_target", "tests/test_validate_targets.py", 9, []),
    _sym("few_test_basic", "tests/few_test_basic.py", 3, []),
]


def _kg():
    files = [
        {"path": "sherlock_project/sherlock.py", "lang": "python", "size": 30000},
        {"path": "sherlock_project/notify.py", "lang": "python", "size": 9000},
        {"path": "sherlock_project/result.py", "lang": "python", "size": 3000},
        {"path": "sherlock_project/sites.py", "lang": "python", "size": 20000},
        {"path": "tests/test_probes.py", "lang": "python", "size": 5000},
        {"path": "tests/conftest.py", "lang": "python", "size": 2000},
    ]
    by_file: dict[str, list[Symbol]] = {}
    for sym in SHERLOCK_SYMBOLS:
        by_file.setdefault(sym.file, []).append(sym)
    outlines = [OutlineResult(file=path, lang="python", symbols=syms) for path, syms in by_file.items()]
    return build_knowledge_graph(files=files, outlines=outlines, total_lines=1000)


# --------------------------------------------------------------------------- #
# T-QLT-1  入口点不能是测试
# --------------------------------------------------------------------------- #
def test_entrypoints_never_include_test_symbols():
    kg = _kg()
    entrypoints = kg.call_graph.entrypoints
    assert entrypoints, "至少要给出一个入口点"
    offenders = [
        name
        for name in entrypoints
        for sym in kg.symbols
        if sym.name == name and is_test_path(sym.file)
    ]
    assert not offenders, f"入口点里出现了测试符号：{offenders}"


def test_entrypoint_fallback_prefers_product_code():
    """没有任何名字像入口时，回退也**不能**落到测试文件上。"""
    symbols = [
        _sym("alpha", "pkg/core.py", 1),
        _sym("beta", "pkg/util.py", 5),
        _sym("TestThing", "tests/test_thing.py", 9),
    ]
    graph = build_call_graph(symbols)
    assert graph.entrypoints, "回退必须仍然给出入口点"
    assert all(name in {"alpha", "beta"} for name in graph.entrypoints), graph.entrypoints


# --------------------------------------------------------------------------- #
# T-QLT-2  模板骨架的前几个课时必须落在产品代码上
# --------------------------------------------------------------------------- #
def test_template_curriculum_teaches_product_code_first():
    kg = _kg()
    curriculum = build_template_curriculum({"full_name": "sherlock-project/sherlock"}, kg, lambda p: "x = 1\n")

    lesson_files = [
        lesson["anchors"][0]["file"]
        for section in curriculum["sections"]
        for lesson in section["lessons"]
    ]
    assert lesson_files, "骨架不能为空"
    first_four = lesson_files[:4]
    assert all(not is_test_path(path) for path in first_four), (
        f"前四个课时必须讲产品代码，实际是 {first_four}——"
        "旧实现按'模块内符号数'排序，tests/ 永远排第一"
    )
    # 产品代码里真正的入口 sherlock.py 必须出现在**前一半**课时里
    assert any(path.endswith("sherlock.py") for path in lesson_files[: len(lesson_files) // 2]), lesson_files


def test_template_curriculum_is_deterministic():
    """同一个仓库两次生成必须是同一门课（模板路径也要可复现）。"""
    kg = _kg()
    read = lambda p: "x = 1\n"  # noqa: E731
    first = build_template_curriculum({"full_name": "r"}, kg, read)
    second = build_template_curriculum({"full_name": "r"}, kg, read)
    assert first == second


@pytest.mark.parametrize(
    "path, expected",
    [
        ("tests/test_probes.py", True),
        ("tests/conftest.py", True),
        ("src/pkg/core_test.py", True),
        ("web/src/x.test.ts", True),
        ("examples/demo_app.py", True),
        ("vendor/lib/thing.py", True),
        ("docs/guide.md", True),
        ("sherlock_project/sherlock.py", False),
        ("sherlock_project/sites.py", False),
        ("apps/api/repolearn/jobs/handlers.py", False),
        ("contest/entry.py", False),  # 别把 "contest" 当成 "test"
    ],
)
def test_is_test_path(path: str, expected: bool):
    assert is_test_path(path) is expected

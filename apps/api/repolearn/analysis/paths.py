"""路径分类（spec §3.4 N4/N5 的"哪些文件值得讲"）。

为什么需要单独一处：**"这是不是测试/示例/文档"这个问题在三个地方都要问**
（入口点识别、模板骨架选文件、置信度打分），而每处各写一份正则的结果是
三处慢慢漂移，最后出现"模板课把 8 个课时里的 7 个讲成了 tests/ 下的测试"。

真实故障（sherlock@c588d7c8，模板降级轮）：
`_representative_files` 只按"模块内符号数"排序，而 `tests/` 里符号最多，
于是 12 课时里 10 个课时讲 `test_probes.py` / `conftest.py` / `test_ux.py`，
真正的 `sherlock.py`、`sites.py`、`notify.py` 反而排在最后。
"""

from __future__ import annotations

#: 目录级：出现在路径**任意一段**里就认为是"不是产品代码"。
TEST_DIRS = frozenset(
    {
        "test",
        "tests",
        "__tests__",
        "spec",
        "specs",
        "testing",
        "fixtures",
        "fixture",
        "__fixtures__",
        "examples",
        "example",
        "samples",
        "docs",
        "doc",
        "vendor",
        "third_party",
        "node_modules",
    }
)

#: 文件名级：这些前缀/后缀说明它是测试或夹具。
TEST_FILE_PREFIXES = ("test_", "conftest", "fixtures_", "sample_")
TEST_FILE_SUFFIXES = ("_test.py", "_test.go", ".test.ts", ".test.tsx", ".spec.ts", ".spec.tsx", "_spec.rb")


def path_parts(path: str) -> list[str]:
    return [part for part in str(path or "").replace("\\", "/").split("/") if part]


def is_test_path(path: str) -> bool:
    """测试、夹具、示例、文档、第三方目录里的文件都算"非产品代码"。

    宁可多算：把这些文件当产品代码讲，比漏掉它们对学习者伤害大得多
    （"这门课的入口在 test_probes.py 里"是**错的**，不只是"不够深"）。
    """
    parts = path_parts(path)
    if not parts:
        return False
    for part in parts[:-1]:
        if part.lower() in TEST_DIRS:
            return True
    name = parts[-1].lower()
    if any(name.startswith(prefix) for prefix in TEST_FILE_PREFIXES):
        return True
    return any(name.endswith(suffix) for suffix in TEST_FILE_SUFFIXES)


def is_doc_path(path: str) -> bool:
    return parts_endswith(path, (".md", ".rst", ".txt", ".adoc"))


def parts_endswith(path: str, suffixes: tuple[str, ...]) -> bool:
    lowest = str(path or "").lower()
    return any(lowest.endswith(suffix) for suffix in suffixes)


__all__ = [
    "TEST_DIRS",
    "TEST_FILE_PREFIXES",
    "TEST_FILE_SUFFIXES",
    "is_doc_path",
    "is_test_path",
    "path_parts",
]

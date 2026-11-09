"""N5 预算耗尽必须**退化**而不是让整门课失败（本次"生成失败"的直接修复）。

真实故障（var/logs/api.log，job_01M6Z6GDK7JGRMH1THMNP18CD0）：

    {"code": "BUDGET_EXCEEDED",
     "message": "budget exceeded: tokens used=213725 limit=200000"}

而 `nodes.py` 的 N5 **早就有**模板兜底分支（`if not outcome.ok: build_template_curriculum`）。
问题是预算耗尽走的是另一条路：`ctx.run` 抛 `AppError`，异常直接穿过
`produce_validated`，绕过兜底，被 runner 记成 `failed_budget` —— 整门课作废。

这组用例守的就是"两条失败路径必须走同一个出口"。
"""

from __future__ import annotations

import pytest

from repolearn.core.errors import AppError
from repolearn.workflow import nodes as nodes_mod


class _Ctx:
    """最小的节点上下文：只实现 N5 用到的几个方法。"""

    def __init__(self, *, budget_exceeded: bool = False) -> None:
        self.runtime_mode = "kernel"
        self.calls = 0
        self.budget_exceeded = budget_exceeded

    async def emit_progress(self, node: str, percent: int = 0) -> None:
        return None

    async def run(self, role: str, system: str, prompt: str, **kwargs):  # noqa: ANN003
        self.calls += 1
        if self.budget_exceeded:
            raise AppError(
                "BUDGET_EXCEEDED",
                "budget exceeded: tokens used=213725 limit=200000",
                details={"kind": "tokens"},
            )
        return "{}", {"tokens_in": 10, "tokens_out": 5}

    def save_artifact(self, node: str, key: str, payload):  # noqa: ANN001
        return f"artifacts/{key}"

    def load_artifact(self, key):  # noqa: ANN001
        return {}


def _state() -> dict:
    return {
        "repo": {"full_name": "fixture/agentchat", "default_branch": "main", "description": "d"},
        "commit": {"sha": "a" * 40},
        "knowledge_graph": {
            "artifact": "artifacts/knowledge_graph.json",
            "modules": ["autogen/agentchat"],
            "symbols": 3,
            "total_files": 3,
        },
    }


@pytest.mark.asyncio
async def test_budget_exceeded_on_plan_falls_back_to_template(monkeypatch):
    """T-BUD-1：N5 预算耗尽 → 模板课程 + 警告，**不抛异常**。

    这条用例红，就意味着"预算用光"会把一份本来可以交付的简化版课程变成
    "生成失败"——用户拿不到任何内容，哪怕静态分析早就把符号和行号算好了。
    """
    ctx = _Ctx(budget_exceeded=True)
    made = nodes_mod.make_nodes(ctx)

    # 模板兜底需要 KG 摘要还原 + 文件读取；这里把它们钉成确定值。
    monkeypatch.setattr(nodes_mod, "_rehydrate_kg", lambda state, sha, ctx: _FakeKg())
    monkeypatch.setattr(nodes_mod, "read_file", lambda sha, path: "class A:\n    pass\n")
    monkeypatch.setattr(
        nodes_mod,
        "build_template_curriculum",
        lambda repo, kg, read: {"title": "t", "sections": [{"title": "s", "lessons": [{"key": "1.1"}]}]},
    )

    update = await made["plan_curriculum"](_state())

    assert update["runtime"] == "template", update
    assert update["curriculum"]["title"] == "t"
    codes = [w["code"] for w in update["warnings"]]
    assert "CURRICULUM_FALLBACK" in codes
    assert "预算耗尽" in update["warnings"][0]["message"]
    # 预算耗尽不该触发修复重试（每次重试都是真金白银，而且注定再超）
    assert ctx.calls == 1


@pytest.mark.asyncio
async def test_other_app_errors_still_propagate(monkeypatch):
    """T-BUD-2：只兜 `BUDGET_EXCEEDED`。别的 AppError 必须原样抛出。"""

    class _Boom(_Ctx):
        async def run(self, role, system, prompt, **kwargs):  # noqa: ANN001, ANN003
            raise AppError("PROVIDER_UNAVAILABLE", "模型服务挂了", retryable=True)

    made = nodes_mod.make_nodes(_Boom())
    with pytest.raises(AppError) as exc:
        await made["plan_curriculum"](_state())
    assert exc.value.code == "PROVIDER_UNAVAILABLE"


class _FakeKg:
    modules: list = []
    symbols: list = []
    total_files = 0

    def anchors(self, limit: int = 0) -> list:  # noqa: ANN001
        return []

    def to_mermaid(self, limit: int = 0) -> str:  # noqa: ANN001
        return "graph TD"

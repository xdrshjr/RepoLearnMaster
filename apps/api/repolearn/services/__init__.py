"""领域服务层（spec §3.2）。

分层规则（评审时要检查的硬约束）：
* `routers/` 只调用 `services/`，不直接操作领域状态；
* `services/` 不得导入 `routers/`；可被 worker 与 CLI 复用；
* 所有对外 JSON 由 `schemas/` 定义，字段变更必须先改 schema 再改实现。

**这里刻意不做 `from . import xxx` 的批量再导出。** 服务之间存在真实的相互依赖
（`course_service` 用 `ingest.mirror`，`ingest.mirror` 用 `object_store`，
而 `book_service` 用 `course_service`）。在包级 `__init__` 里提前导入它们，会让
"先 import 谁"取决于导入顺序——表现就是 `cannot import name ... from partially
initialized module`。让调用方显式 `from repolearn.services import course_service`
是零成本且不会随依赖图变化而崩的做法。
"""

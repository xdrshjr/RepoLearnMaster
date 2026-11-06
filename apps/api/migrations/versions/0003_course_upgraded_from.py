"""0003_course_upgraded_from —— `course_versions.upgraded_from_id`（spec §6.1 / §6.5）。

**这份迁移是整个方案里最危险的一处。** `migrations/env.py` 已全局开了
`render_as_batch=True`，而 SQLite 的 batch 语义是**重建表**（建临时表 → 拷数据 →
DROP 原表 → 改名）。DROP 原表会连带删掉 `0002` 建在 `course_versions` 上的 4 个
FTS 触发器（实测：`sqlite_master` 里该表的触发器归零）。后果不是"迁移失败"
（那还好，至少你会知道），而是**迁移成功、`/healthz.ok` 为真、搜索从此不再更新**：
新生成的课程永远搜不到，改了标题的课程搜到的还是旧词。

所以这里的做法是"两步都做"：

1. **upgrade 走原生 `ALTER TABLE ADD COLUMN`**（SQLite ≥ 3.2 就支持，不重建表，
   因此根本不碰触发器）。代价是**不能带 FK 约束**——SQLite 无法在不重建表的前提下
   新增外键，而重建表正是我们要避开的动作。取值语义由应用层保证（只有
   `services/upgrade_service` 会写这一列，且写的是刚查出来的旧版本 id），
   ORM 模型上的 `ForeignKey` 声明保留给 PG 与文档用途。
2. **downgrade 只能走 batch**（SQLite 的 `DROP COLUMN` 在 batch 里就是重建表），
   因此 downgrade 末尾**必须重放** `search_ddl.TRIGGERS_SQL`，否则
   "先 downgrade 0003、再 downgrade 0002" 中间那段窗口里搜索已经完全失效。
3. **收尾自检**：`upgrade` 与 `downgrade` 都以"触发器数量可解释"结束——期望 4，
   索引表不存在时期望 0；其他数量直接抛异常。宁可迁移红，也不要静默生效一半。
"""

from __future__ import annotations

import logging

import sqlalchemy as sa
from alembic import op

from repolearn.services import search_ddl

revision = "0003_course_upgraded_from"
down_revision = "0002_course_search_fts"
branch_labels = None
depends_on = None

log = logging.getLogger("alembic.0003")

INDEX_NAME = "ix_course_versions_upgraded_from"


def _index_table_exists(conn) -> bool:
    return bool(int(conn.exec_driver_sql(search_ddl.TABLE_EXISTS_SQL).scalar() or 0))


def _trigger_count(conn) -> int:
    return int(conn.exec_driver_sql(search_ddl.COUNT_TRIGGERS_SQL).scalar() or 0)


def ensure_triggers(conn) -> int:
    """索引表在就重放触发器（幂等），返回最终触发器数量。

    重放而不是"只数一数"：`0002` 的触发器可能已经被某次 batch 重建删光了，
    而"数出来是 0 就抛异常"会让 downgrade 变成单程票。重放之后仍然对不上，
    才是真的有问题（例如 DDL 与索引表名不一致）。
    """
    if not _index_table_exists(conn):
        return _trigger_count(conn)
    for ddl in search_ddl.trigger_ddl():
        conn.exec_driver_sql(ddl)
    return _trigger_count(conn)


def _assert_triggers(conn, *, phase: str) -> None:
    count = ensure_triggers(conn)
    expected = search_ddl.TRIGGER_COUNT if _index_table_exists(conn) else 0
    if count != expected:
        raise RuntimeError(
            f"{phase} 之后 FTS 触发器数量为 {count}，期望 {expected}："
            "搜索会从此不再更新（迁移绿、健康检查绿，但结果集是旧的）。"
            "修法：运行 `python -m repolearn.cli reindex-search` 重建，并检查 "
            "`services/search_ddl.py::TRIGGERS_SQL` 是否被绕过。"
        )


def upgrade() -> None:
    conn = op.get_bind()
    # 原生 ADD COLUMN：不重建表 → 不删触发器 → 不产生"搜索悄悄失效"的窗口。
    op.add_column("course_versions", sa.Column("upgraded_from_id", sa.String(40), nullable=True))
    op.create_index(INDEX_NAME, "course_versions", ["upgraded_from_id"])
    _assert_triggers(conn, phase="0003 upgrade")
    log.info("upgraded_from_id_ready triggers=%s", _trigger_count(conn))


def downgrade() -> None:
    conn = op.get_bind()
    op.drop_index(INDEX_NAME, table_name="course_versions")
    # 删列在 SQLite 上只能重建表，因此这里必须用 batch。而 batch 重建的过程是
    # "建 `_alembic_tmp_course_versions` → 拷数据 → DROP 原表 → 把临时表改名"，
    # 中间那一瞬间 `course_versions` 是不存在的——此时任何引用它的触发器都会让
    # 改名语句直接失败：`error in trigger trg_repo_search_au: no such table`。
    # 因此重建**之前**必须先把 4 个 FTS 触发器全部删掉，重建之后再用同一份 DDL
    # 重放。少做前半步，downgrade 本身就是一条抛异常的单程票（实测踩到过）。
    for stmt in search_ddl.DROP_TRIGGERS_SQL:
        conn.exec_driver_sql(stmt)
    with op.batch_alter_table("course_versions") as batch:
        batch.drop_column("upgraded_from_id")
    _assert_triggers(conn, phase="0003 downgrade")
    log.info("upgraded_from_id_dropped triggers=%s", _trigger_count(conn))

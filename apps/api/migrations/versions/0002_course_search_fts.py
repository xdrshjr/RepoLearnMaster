"""0002_course_search_fts —— FTS5 trigram 索引（hardening spec §3.4.2 / §6.1）。

**Alembic autogenerate 看不到虚拟表**，所以这份迁移是手写的；DDL 本身不写在这里，
而是引用 `repolearn.services.search_ddl`（与 `0003` 的 downgrade、`cli reindex-search`
共用同一份）——理由见那个模块的文档字符串：手抄的 DDL 迟早漂移，而漂移的表现
是"迁移绿、健康检查绿、搜索悄悄不再更新"。

**P0-2：先探测能力，再决定建不建。** `trigram` 是 FTS5 的可选能力：SQLite < 3.34
或编译期未带它时，`CREATE VIRTUAL TABLE ... tokenize='trigram'` 会抛
`no such tokenizer: trigram`。而 `tests/conftest.py` 在**模块导入期**就跑
`alembic upgrade head`——这里一抛异常，整仓 pytest 一条都跑不了，`start.ps1` 的
迁移步骤也会中止。这与"降级可见、不得静默换路径"的方向正好相反（不是静默降级，
是直接爆炸）。因此：不支持时**不建表、不建触发器、不抛异常**，只记一行 warning，
`alembic_version` 照常前进（迁移算"已执行"，只是能力不具备）；查询侧由
`services/search.py::fts_capability()` 看 `sqlite_master` 判定并回落 `scan`。
"""

from __future__ import annotations

import logging

from alembic import op

from repolearn.services import search_ddl

revision = "0002_course_search_fts"
down_revision = "0001_initial"
branch_labels = None
depends_on = None

log = logging.getLogger("alembic.0002")


def trigram_ok(conn) -> bool:
    """能不能真的建一张 trigram 表？**试一次**比查版本号可靠。

    版本号只说明 SQLite 够新，不说明这次编译带了 FTS5、更不说明带了 trigram。
    用临时表试建一次，失败就当作"不支持"——`except Exception` 是刻意的：任何
    失败在这个问题上都等价于"不支持"，而把异常类型列全只会漏掉某一种。
    """
    from repolearn.services.search import sqlite_supports_trigram

    if not sqlite_supports_trigram():
        return False
    try:
        conn.exec_driver_sql("CREATE VIRTUAL TABLE temp.__probe USING fts5(x, tokenize='trigram')")
        conn.exec_driver_sql("DROP TABLE temp.__probe")
        return True
    except Exception:  # noqa: BLE001 - 任何失败都等价于"不支持"
        return False


def build_index(conn, *, rebuild: bool = False) -> int:
    """建表 + 回填 + 4 个触发器，返回回填行数。

    `rebuild=True` 时先清空再灌（`reindex-search` 用它做幂等重建）。
    """
    if rebuild:
        conn.exec_driver_sql(search_ddl.TRUNCATE_SQL)
    conn.exec_driver_sql(search_ddl.CREATE_TABLE_SQL)
    conn.exec_driver_sql(search_ddl.TRUNCATE_SQL)
    conn.exec_driver_sql(search_ddl.BACKFILL_SQL)
    for ddl in search_ddl.trigger_ddl():
        conn.exec_driver_sql(ddl)
    rows = conn.exec_driver_sql(f"SELECT count(*) FROM {search_ddl.FTSTable}").scalar() or 0
    return int(rows)


def upgrade() -> None:
    conn = op.get_bind()
    if not trigram_ok(conn):
        # 不建表、不建触发器、不抛异常：老机器上"功能少一半"可以接受，
        # "整仓 pytest 起不来"不可以。
        try:
            version = conn.exec_driver_sql("SELECT sqlite_version()").scalar()
        except Exception:  # noqa: BLE001 - 探测失败也要让迁移过
            version = "unknown"
        log.warning("fts_unavailable sqlite=%s reason=no_trigram_tokenizer", version)
        return
    indexed = build_index(conn)
    log.info("course_search_ready rows=%s triggers=%s", indexed, search_ddl.TRIGGER_COUNT)


def downgrade() -> None:
    conn = op.get_bind()
    # 顺序不可反：先删表会让触发器指向不存在的表，之后任何 `course_versions`
    # 写入都会报 `no such table: course_search`。
    for stmt in search_ddl.DROP_TRIGGERS_SQL:
        conn.exec_driver_sql(stmt)
    conn.exec_driver_sql(f"DROP TABLE IF EXISTS {search_ddl.FTSTable}")

"""FTS5 搜索索引的**唯一** DDL 来源（hardening spec §3.4.2，评审 P0-1）。

为什么要把它抽成一个常量，而不是在迁移里直接写 SQL：这套方案里最容易发生的
静默失效，是"迁移成功、健康检查全绿、搜索从此不再更新"。它的成因有三条，而
三条都指向同一件事——同一段 DDL 被抄在了多个地方：

1. `migrations/env.py` 全局开了 `render_as_batch=True`，而 SQLite 的 batch 语义
   是**重建表**（建临时表 → 拷数据 → DROP 原表 → 改名）。DROP 原表会连带删掉
   建在它上面的触发器，而 Alembic 不会替我们重建。
2. `reindex-search` 是"后悔药"，它必须重建出与迁移**一模一样**的触发器，否则
   吃完药之后的行为与迁移之后的行为不一致。
3. 未来任何一次对 `course_versions` 的结构变更都可能再走一次 batch。

因此表与 4 个触发器只有一份定义，`0002` 的 upgrade、`0003` 的 downgrade、
`cli reindex-search` 三处共用。`T-SEARCH-9` 用 `sqlite_master` 断言"恰好 4 个"，
`T-SEARCH-6/7` 用行为断言"改了标题/仓库名之后立刻能搜到新词"。
"""

from __future__ import annotations

#: 索引表名。查询侧用 `text()` 拼 SQL 时**必须写表名而不是别名**——
#: SQLite 的 `MATCH` 与 `bm25()` 只认表名，写别名会得到 `no such column: s`。
FTSTable = "course_search"

#: `summary` 只索引前 512 字符（R4）。中文 trigram 的索引体积约为原文 3 倍，
#: 而课程摘要前 512 字已覆盖用户会搜到的所有术语；全量索引换来的是磁盘占用。
SUMMARY_INDEX_CHARS = 512

#: 建表（幂等）。`course_version_id` 用 `UNINDEXED`：它是回查 join 的键，
#: trigram 索引只该覆盖真正要匹配的文本列。
CREATE_TABLE_SQL = f"""
CREATE VIRTUAL TABLE IF NOT EXISTS {FTSTable} USING fts5(
    course_version_id UNINDEXED,
    title,
    summary,
    repo_full_name,
    tokenize = 'trigram'
)
"""

#: 回填（幂等：先清空再灌，避免重复行）。`COALESCE` 不是洁癖——`NULL` 进 FTS 行
#: 会让 `bm25` 出现 `NULL` 排序键，排序结果变成随机的。
BACKFILL_SQL = f"""
INSERT INTO {FTSTable} (course_version_id, title, summary, repo_full_name)
SELECT c.id,
       COALESCE(c.title, ''),
       substr(COALESCE(c.summary_md, ''), 1, {SUMMARY_INDEX_CHARS}),
       COALESCE(r.full_name, '')
FROM course_versions c
JOIN repositories r ON r.id = c.repository_id
"""

TRUNCATE_SQL = f"DELETE FROM {FTSTable}"

#: 4 个触发器。**每一份都幂等**（`IF NOT EXISTS`）：迁移往返后重放不会抛错。
#: FTS5 的内容列不支持 `UPDATE`，所以更新一律"先删行再插行"。
TRIGGERS_SQL: tuple[str, ...] = (
    f"""
    CREATE TRIGGER IF NOT EXISTS trg_course_search_ai AFTER INSERT ON course_versions BEGIN
      INSERT INTO {FTSTable} (course_version_id, title, summary, repo_full_name)
      SELECT NEW.id, COALESCE(NEW.title, ''),
             substr(COALESCE(NEW.summary_md, ''), 1, {SUMMARY_INDEX_CHARS}),
             COALESCE((SELECT full_name FROM repositories WHERE id = NEW.repository_id), '');
    END
    """,
    f"""
    CREATE TRIGGER IF NOT EXISTS trg_course_search_au
    AFTER UPDATE OF title, summary_md ON course_versions BEGIN
      DELETE FROM {FTSTable} WHERE course_version_id = NEW.id;
      INSERT INTO {FTSTable} (course_version_id, title, summary, repo_full_name)
      SELECT NEW.id, COALESCE(NEW.title, ''),
             substr(COALESCE(NEW.summary_md, ''), 1, {SUMMARY_INDEX_CHARS}),
             COALESCE((SELECT full_name FROM repositories WHERE id = NEW.repository_id), '');
    END
    """,
    f"""
    CREATE TRIGGER IF NOT EXISTS trg_course_search_ad AFTER DELETE ON course_versions BEGIN
      DELETE FROM {FTSTable} WHERE course_version_id = OLD.id;
    END
    """,
    # 仓库改名（罕见但要覆盖）：`repo_full_name` 也是可搜索列，漏掉它会让
    # "改过名的仓库搜不到自己的新名字"。
    f"""
    CREATE TRIGGER IF NOT EXISTS trg_repo_search_au AFTER UPDATE OF full_name ON repositories BEGIN
      DELETE FROM {FTSTable} WHERE course_version_id IN
        (SELECT id FROM course_versions WHERE repository_id = NEW.id);
      INSERT INTO {FTSTable} (course_version_id, title, summary, repo_full_name)
      SELECT c.id, COALESCE(c.title, ''),
             substr(COALESCE(c.summary_md, ''), 1, {SUMMARY_INDEX_CHARS}),
             COALESCE(NEW.full_name, '')
      FROM course_versions c WHERE c.repository_id = NEW.id;
    END
    """,
)

#: 4 个触发器的名字。集中成常量，供计数与 `DROP` 共用（名字写错一处就会
#: 出现"删了 3 个、剩 1 个"这种只有回滚时才发现的坑）。
TRIGGER_NAMES: tuple[str, ...] = (
    "trg_course_search_ai",
    "trg_course_search_au",
    "trg_course_search_ad",
    "trg_repo_search_au",
)

#: 删触发器的**顺序无关**，但每一条都必须带 `IF EXISTS`：先回滚 `0003`（它会
#: 重放触发器）再回滚 `0002` 时，某些触发器可能已经被删过；没有 `IF EXISTS`
#: 的 `DROP TRIGGER` 会抛 `no such trigger`，让"降级"这条逃生通道本身不可用。
DROP_TRIGGERS_SQL: tuple[str, ...] = tuple(f"DROP TRIGGER IF EXISTS {name}" for name in TRIGGER_NAMES)

#: 触发器计数。**按名字数，而不是按 `tbl_name='course_versions'` 数**：4 个触发器里
#: `trg_repo_search_au` 建在 `repositories` 上（仓库改名要同步索引），所以
#: "tbl_name='course_versions'" 永远只能数出 3 个——若照文档里的那条 SQL 断言
#: "恰好 4"，迁移会在第一次跑就直接红。
COUNT_TRIGGERS_SQL = (
    "SELECT count(*) FROM sqlite_master WHERE type='trigger' AND name IN ("
    + ", ".join(f"'{name}'" for name in TRIGGER_NAMES)
    + ")"
)
TABLE_EXISTS_SQL = (
    "SELECT count(*) FROM sqlite_master WHERE type='table' AND name='" + FTSTable + "'"
)

#: 期望的触发器数量。任何一处断言都引用这个常量，不写字面量 4。
TRIGGER_COUNT = len(TRIGGERS_SQL)


def trigger_ddl() -> tuple[str, ...]:
    """按顺序返回 4 条触发器 DDL（供 `exec_driver_sql` 逐条执行）。"""
    return TRIGGERS_SQL


__all__ = [
    "BACKFILL_SQL",
    "COUNT_TRIGGERS_SQL",
    "CREATE_TABLE_SQL",
    "DROP_TRIGGERS_SQL",
    "FTSTable",
    "SUMMARY_INDEX_CHARS",
    "TABLE_EXISTS_SQL",
    "TRIGGERS_SQL",
    "TRIGGER_COUNT",
    "TRIGGER_NAMES",
    "TRUNCATE_SQL",
    "trigger_ddl",
]

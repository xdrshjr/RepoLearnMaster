"""Alembic 环境（spec §6.5）。

两点与默认模板不同：
1. **URL 来自 `repolearn.core.config.settings`**，而不是 `alembic.ini`。两处配置
   一定会分叉，而"迁移跑到了另一个库"是最难发现的一类事故。
2. **`render_as_batch=True`**：SQLite 不支持大部分 `ALTER TABLE`，batch 模式让
   "以后加约束/改类型"这类迁移在 SQLite 上依然可执行（T-DB-1 的往返靠它）。
"""

from __future__ import annotations

import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import engine_from_config, pool

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT / "apps" / "api") not in sys.path:
    sys.path.insert(0, str(ROOT / "apps" / "api"))

from repolearn.core.config import get_settings  # noqa: E402
from repolearn.core.db import Base  # noqa: E402
from repolearn.models import ALL_MODELS  # noqa: E402,F401  —— 必须导入以注册全部表

config = context.config

if config.config_file_name is not None:
    try:
        fileConfig(config.config_file_name)
    except Exception:  # noqa: BLE001 - CLI 内嵌运行时允许没有 logging 配置
        pass

target_metadata = Base.metadata


def _sync_url() -> str:
    """把 async URL 转成同步 URL：Alembic 的 engine 是同步的。

    **每次都现取**（`get_settings()`）而不是在模块级缓存：测试与 CI 会在同一进程里
    对多个库跑迁移（往返测试、临时库），模块级单例会让第二次迁移悄悄作用在上一个库上
    ——"迁移跑了，但改动不在你以为的那个文件里"是极难查的一类问题。
    """
    url = get_settings().resolved_database_url
    return url.replace("+aiosqlite", "").replace("+asyncpg", "+psycopg2")


def run_migrations_offline() -> None:
    context.configure(
        url=_sync_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    section = config.get_section(config.config_ini_section) or {}
    section["sqlalchemy.url"] = _sync_url()
    connectable = engine_from_config(section, prefix="sqlalchemy.", poolclass=pool.NullPool)
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=True,
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()

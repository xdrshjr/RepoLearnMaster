"""数据库引擎与会话。

SQLite 必做的三件事（spec §3.11.4 / §6.7）：
1. `journal_mode=WAL` —— 让读不被写阻塞；
2. `busy_timeout=5000` —— 让并发写在锁上排队而不是立刻报错；
3. `foreign_keys=ON` —— SQLite 默认**不**校验外键，不打开就等于没有级联删除。

`get_session` 是 FastAPI 依赖；`session_scope()` 给 Job Runner / CLI 用，
两者共用同一个 sessionmaker，避免"后台任务和请求看到不同的事务语义"。
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy import MetaData, event, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from repolearn.core.config import settings

#: 约束命名约定。
#:
#: 不设约定时 SQLAlchemy 生成**匿名**约束，而 Alembic 的 `batch_alter_table`
#: （SQLite 唯一可用的改表方式）需要靠名字在重建表时把约束带回去。没有名字，
#: "以后想删/改一个唯一约束"这件事在 SQLite 上直接做不到。
NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "ux_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    """全部 ORM 模型的公共基类。"""

    metadata = MetaData(naming_convention=NAMING_CONVENTION)


def _make_engine():
    url = settings.resolved_database_url
    kwargs: dict = {"echo": False, "future": True}
    if "sqlite" in url:
        kwargs["connect_args"] = {"timeout": 30}
    return create_async_engine(url, **kwargs)


engine = _make_engine()
SessionMaker = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


if "sqlite" in settings.resolved_database_url:

    @event.listens_for(engine.sync_engine, "connect")
    def _sqlite_pragmas(dbapi_conn, _record):  # noqa: ANN001
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA busy_timeout=5000")
        cur.execute("PRAGMA foreign_keys=ON")
        cur.execute("PRAGMA synchronous=NORMAL")
        cur.close()


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI 依赖。

    **必须在这里提交**，而不是在 router 里逐个 `commit()`：
    `async with SessionMaker()` 退出时只关闭连接、回滚未提交的事务。少了这一步，
    所有写接口都会返回 200 但数据全部丢失——而且测试不查库的话根本发现不了。
    """
    async with SessionMaker() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


@asynccontextmanager
async def session_scope() -> AsyncIterator[AsyncSession]:
    """后台任务与 CLI 用的事务边界。"""
    async with SessionMaker() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def check_db() -> bool:
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return True
    except Exception:  # noqa: BLE001
        return False


async def dispose_engine() -> None:
    await engine.dispose()

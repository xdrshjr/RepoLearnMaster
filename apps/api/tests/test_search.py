"""搜索门禁（hardening spec §7.4：T-SEARCH-1..10、T-CONTR-1）。

这套用例守的是**一个开关名不副实**的产品缺陷：`REPOLEARN_SEARCH=fts` 被接受、
Doctor 回显 `ok / detail: fts`，而 `list_courses` 里只有 `LIKE` 分支。用户配了
开关，却什么变化都没有——而且系统告诉他"已生效"。

因此这里的断言都设计成"会失败"的形态：不是"返回了 200"，而是"2 字查询**命中数
大于 0**"、"改了标题之后**立刻**能搜到新词"、"触发器**恰好** 4 个"。
"""

from __future__ import annotations

import os
import sqlite3
import subprocess
import sys

import pytest
from sqlalchemy import select, text

from repolearn.core.clock import utcnow
from repolearn.core.config import REPO_ROOT, settings
from repolearn.core.ids import new_id
from repolearn.models import CourseVersion, Repository
from repolearn.services import search as search_mod
from repolearn.services import search_ddl
from repolearn.services.course_service import list_courses


async def _add_course(
    session, *, title: str, summary: str = "", repo: str = "o/r", sha: str = "a" * 64, created_at=None
) -> str:
    """造一门可搜索的课程（触发器会把行同步进 FTS 索引）。

    `created_at` 可显式传入：列表排序是 `(created_at DESC, id DESC)`，而
    `utcnow()` 每次调用都不同——两次插入若落在同一毫秒，ULID 的随机段与
    `created_at` 的微秒差会互相打架，"按排序键算期望"的断言就时红时绿
    （本机实测：全量跑红、单跑绿）。想做"同时间戳下由 id 兜底"的断言，
    就必须把时间戳钉死。
    """
    stamp = created_at or utcnow()
    repository = (
        await session.execute(select(Repository).where(Repository.full_name == repo))
    ).scalar_one_or_none()
    if repository is None:
        repository = Repository(
            id=new_id("repository"),
            full_name=repo,
            owner=repo.split("/")[0],
            name=repo.split("/")[1],
            description="fixture",
            stars=1,
            license_spdx="MIT",
            primary_language="Python",
            default_branch="main",
            html_url=f"https://github.com/{repo}",
            is_public=True,
            created_at=stamp,
            updated_at=stamp,
        )
        session.add(repository)
        await session.flush()
    course_id = new_id("course_version")
    session.add(
        CourseVersion(
            id=course_id,
            repository_id=repository.id,
            commit_sha=sha,
            cache_key=f"{repo}-{title}-{sha[:8]}",
            policy_version="1",
            language="zh",
            title=title,
            summary_md=summary,
            status="ready",
            sections=[{"key": "overview", "title": "第一层", "minutes": 5, "lessons": []}],
            quality_report={},
            warnings=[],
            blueprint={},
            lesson_count=0,
            total_minutes=5,
            visibility="public",
            created_at=stamp,
            updated_at=stamp,
            published_at=stamp,
        )
    )
    await session.flush()
    return course_id


@pytest.fixture()
def fts_on(monkeypatch):
    monkeypatch.setattr(settings, "search", "fts")
    return settings


async def _count_index(session) -> int:
    return int((await session.execute(text(f"SELECT count(*) FROM {search_ddl.FTSTable}"))).scalar() or 0)


# --------------------------------------------------------------------------- #
# T-SEARCH-1 / 2 / 3                                                          #
# --------------------------------------------------------------------------- #


async def test_search_1_index_matches_versions(session):
    """T-SEARCH-1：迁移后索引行数 = `course_versions` 行数；reindex 后不变。

    回填漏行是"搜索结果比预期少"的最常见原因，而它不会报错。
    """
    await _add_course(session, title="缓存策略带读", summary="讲讲缓存", sha="1" * 64)
    await _add_course(session, title="异步入口", summary="讲讲 async", sha="2" * 64)
    await session.flush()
    versions = int((await session.execute(text("SELECT count(*) FROM course_versions"))).scalar() or 0)
    assert await _count_index(session) == versions == 2


async def test_search_2_trigram_chinese_substring(session, fts_on):
    """T-SEARCH-2：3 字中文命中，2 字中文回落但**仍有结果**。

    这两条必须一起断言：只测 3 字会让"2 字静默空结果"这个真实缺陷藏起来。
    """
    await _add_course(session, title="缓存策略带读", summary="命中缓存的三层设计", sha="3" * 64)
    await _add_course(session, title="异步入口", summary="async 与 await", sha="4" * 64)

    long_result = await list_courses(session, q="缓存策", mode="auto")
    assert long_result.mode == "fts", long_result.mode
    assert [item.title for item in long_result.items] == ["缓存策略带读"]
    assert long_result.items[0].highlights is not None
    assert any(seg.marked for seg in long_result.items[0].highlights.title or [])


async def test_search_3_short_query_falls_back_with_results(session, fts_on):
    """T-SEARCH-3：2 字查询在 `mode=fts` 下回落 scan，`mode`/`fallback_reason` 可见。"""
    await _add_course(session, title="缓存策略带读", summary="命中缓存", sha="5" * 64)
    result = await list_courses(session, q="缓存", mode="auto")
    assert result.mode == "scan"
    assert result.fallback_reason == "query_too_short"
    assert len(result.items) == 1


async def test_search_4_expression_injection_is_literal(session, fts_on):
    """T-SEARCH-4：FTS 表达式语法不泄漏。`a*b`、`NEAR(`、`"` 都必须按字面量处理。

    `MATCH` 是表达式语言（`-` 是 NOT、`*` 是前缀、`NEAR()` 是邻接）。直接拼接
    用户输入，轻则结果错，重则一个语法错 500。
    """
    await _add_course(session, title="前缀 a*b 的语义", summary='包含引号 " 的说明', sha="6" * 64)
    await _add_course(session, title="NEAR(a b) 的语法说明", summary="", sha="9" * 64)
    # 这些输入一个都不该抛异常
    for query in ["a*b", '"', 'NEAR("a" "b")', "a -b"]:
        result = await list_courses(session, q=query, mode="auto")
        assert result.mode in {"fts", "scan"}
    # `a*b` 走 fts 且按**字面量**匹配（若是前缀通配，会命中别的课程）
    literal = await list_courses(session, q="a*b", mode="auto")
    assert literal.mode == "fts"
    assert [item.title for item in literal.items] == ["前缀 a*b 的语义"]


# --------------------------------------------------------------------------- #
# T-SEARCH-5 / 6 / 7                                                          #
# --------------------------------------------------------------------------- #


async def test_search_5_scan_mode_keeps_legacy_semantics(session, monkeypatch):
    """T-SEARCH-5：`scan` 的 id 序列与旧实现一致。

    **只比 id 和顺序键**（spec P2-5）：本轮 `CourseListItem` 新增了 `highlights`，
    逐字段快照会在实现当天就过期，然后被人用"更新快照"糊过去——那条断言就永久
    失效了。
    """
    monkeypatch.setattr(settings, "search", "scan")
    # 时间戳钉死：排序是 `(created_at DESC, id DESC)`，只有 created_at 完全相同时
    # 才是"由 id 兜底"这条规则在起作用。否则两次 `utcnow()` 的微秒差会主导排序，
    # 断言就时红时绿（本机实测：全量跑红、单跑绿）。
    stamp = utcnow()
    ids = []
    for index, title in enumerate(["缓存 A", "缓存 B", "无关 C"]):
        ids.append(
            await _add_course(session, title=title, summary="", sha=str(index + 7) * 64, created_at=stamp)
        )
    result = await list_courses(session, q="缓存", mode="scan")
    assert result.mode == "scan"
    # 同一 created_at → 顺序由 `id DESC` 兜底。ULID 同毫秒内的随机段**不保证**
    # 与插入顺序一致，所以这里按"排序键"算期望，而不是按插入顺序倒排。
    assert [item.id for item in result.items] == sorted(ids[:2], reverse=True)


async def test_search_6_triggers_update_index(session, fts_on):
    """T-SEARCH-6：直接 UPDATE 标题后立刻能搜到新词、旧词不再命中。

    有触发器但没被触发，是这类设计最隐蔽的失效形态：迁移绿、索引存在、结果过期。
    """
    course_id = await _add_course(session, title="旧的缓存标题", summary="", sha="d" * 64)
    await session.flush()
    before = await list_courses(session, q="旧的缓存", mode="auto")
    assert [item.id for item in before.items] == [course_id]

    await session.execute(
        text("UPDATE course_versions SET title = :title WHERE id = :id"),
        {"title": "全新的异步标题", "id": course_id},
    )
    await session.flush()
    after_new = await list_courses(session, q="全新的异步", mode="auto")
    assert [item.id for item in after_new.items] == [course_id]
    after_old = await list_courses(session, q="旧的缓存", mode="auto")
    assert after_old.items == []


async def test_search_7_repo_rename_updates_index(session, fts_on):
    """T-SEARCH-7：仓库改名后按新 `full_name` 可搜到（第 4 个触发器）。"""
    await _add_course(session, title="普通课程", summary="", repo="old/name", sha="e" * 64)
    await session.flush()
    await session.execute(text("UPDATE repositories SET full_name = :name WHERE full_name = :old"), {"name": "new/name", "old": "old/name"})
    await session.flush()
    result = await list_courses(session, q="new/name", mode="auto")
    assert len(result.items) == 1


# --------------------------------------------------------------------------- #
# T-SEARCH-9 / 10                                                             #
# --------------------------------------------------------------------------- #


async def test_search_9_trigger_count_is_four(session):
    """T-SEARCH-9：迁移后触发器**恰好** 4 个（含 `repositories` 上的那一个）。

    spec 里写的判据是 `tbl_name='course_versions'`，但 4 个触发器里有 1 个建在
    `repositories` 上（仓库改名要同步索引），按那个条件永远只能数出 3。因此这里
    按**名字**数——判据的形状可以改，"恰好 4 个"这个事实不能改。
    """
    count = int((await session.execute(text(search_ddl.COUNT_TRIGGERS_SQL))).scalar() or 0)
    assert count == search_ddl.TRIGGER_COUNT == 4
    names = {
        row[0]
        for row in (
            await session.execute(
                text("SELECT name FROM sqlite_master WHERE type='trigger' AND name LIKE 'trg_%search%'")
            )
        ).all()
    }
    assert names == set(search_ddl.TRIGGER_NAMES)


async def test_search_10_capability_degrades_without_trigram(monkeypatch):
    """T-SEARCH-10：SQLite 不支持 trigram 时**迁移不炸**，查询回落且 Doctor 为 degraded。

    用独立临时库 + monkeypatch 逃过 conftest 已经跑过的那次迁移：这条断言要的
    正是"第一次就在老机器上跑"的那条路径。
    """
    from alembic import command
    from alembic.config import Config

    from repolearn.core.config import get_settings

    tmp_db = os.path.join(os.environ.get("TEMP", "."), "repolearn-fts10.db")
    if os.path.exists(tmp_db):
        os.remove(tmp_db)

    monkeypatch.setattr(search_mod, "sqlite_supports_trigram", lambda: False)
    old_env = os.environ["REPOLEARN_DATABASE_URL"]
    os.environ["REPOLEARN_DATABASE_URL"] = f"sqlite+aiosqlite:///{tmp_db.replace(os.sep, '/')}"
    get_settings.cache_clear()
    cfg = Config(str(REPO_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(REPO_ROOT / "apps" / "api" / "migrations"))
    try:
        command.upgrade(cfg, "head")  # 不抛异常即为通过
        con = sqlite3.connect(tmp_db)
        try:
            tables = {
                row[0]
                for row in con.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
            }
            version = con.execute("SELECT version_num FROM alembic_version").fetchone()[0]
        finally:
            con.close()
        assert search_ddl.FTSTable not in tables, "能力不具备时不该建表"
        assert version == "0003_course_upgraded_from", version

        plan = search_mod.plan_search("缓存策", configured="fts", sqlite_version="3.31.1")
        assert plan.mode == "scan"
        assert plan.fallback_reason == "sqlite_too_old"

        # reindex-search 在不支持的运行时必须 exit 0（维护命令不该在"本来就没有"时红）
        env = {**os.environ, "REPOLEARN_DATABASE_URL": f"sqlite+aiosqlite:///{tmp_db.replace(os.sep, '/')}"}
        done = subprocess.run(
            [
                sys.executable,
                "-c",
                "import sys;sys.path.insert(0,'apps/api');"
                "import repolearn.services.search as s;"
                "s.sqlite_supports_trigram=lambda: False;"
                "from repolearn.cli import main;sys.exit(main(['reindex-search']))",
            ],
            cwd=str(REPO_ROOT),
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=120,
        )
        assert done.returncode == 0, done.stderr[-800:]
        assert "nothing to do" in f"{done.stdout}{done.stderr}"
    finally:
        os.environ["REPOLEARN_DATABASE_URL"] = old_env
        get_settings.cache_clear()
        if os.path.exists(tmp_db):
            try:
                os.remove(tmp_db)
            except OSError:
                pass


# --------------------------------------------------------------------------- #
# T-CONTR-1                                                                   #
# --------------------------------------------------------------------------- #


async def test_contr_1_offset_on_scan_is_validation_failed(client, ready_course):
    """T-CONTR-1：`offset` 与 `scan` 组合必须是 **422 + VALIDATION_FAILED + 不可重试**。

    这条断言同时守住两件事：契约里真有这个码，以及"未知码静默变 500"那条逃生通道
    已经被堵上。
    """
    resp = await client.get("/v1/courses", params={"mode": "scan", "offset": 5})
    assert resp.status_code == 422
    body = resp.json()["error"]
    assert body["code"] == "VALIDATION_FAILED"
    assert body["retryable"] is False
    assert "offset" in (body.get("hint") or "")


async def test_contr_1_param_validation_uses_error_envelope(client, ready_course):
    """T-CONTR-1：FastAPI 自己的 `Query` 校验失败也必须落在 `VALIDATION_FAILED` 上。

    v1 只注册了 `AppError` 与 `Exception` 两个 handler，于是 `offset=999` 走的是
    FastAPI 默认的 `{"detail": [...]}`：响应体里没有 `error.code`，前端
    `client.ts` 读不到就回落成 `INTERNAL`，用户看到的仍然是"服务内部错误"。
    P0-4 点名的正是这个场景——它只是从 500 挪到了 422，谎言没变。
    """
    cases = [{"offset": 999}, {"q": "长" * 121}, {"mode": "bogus"}, {"limit": "abc"}]
    for params in cases:
        resp = await client.get("/v1/courses", params=params)
        assert resp.status_code == 422, (params, resp.text)
        body = resp.json()["error"]
        assert body["code"] == "VALIDATION_FAILED", (params, body)
        assert body["retryable"] is False
        assert body["details"]["fields"], body


async def test_contr_1_offset_allowed_when_auto_lands_on_fts(client, session, fts_on):
    """`mode=auto` 实际走 fts 时必须允许 `offset`（前端发的就是 `mode=auto`）。

    v1 只在 `mode=="fts"` 时放行，而前端 `useCourseSearch` 恒发 `auto`——于是
    fts 的 offset 分页在默认路径上**永远用不了**，服务端还会签发一个自己拒绝
    接收的 `next_offset`。
    """
    for index in range(3):
        await _add_course(session, title=f"缓存策略 {index}", summary="缓存", sha=f"{index}" * 64)
    await session.commit()
    resp = await client.get("/v1/courses", params={"q": "缓存策略", "mode": "auto", "offset": 1, "limit": 1})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["mode"] == "fts", body
    assert len(body["items"]) == 1


async def test_contr_1_contract_fields_present(client, ready_course):
    """`mode`/`fallback_reason`/`next_offset`/`total`/`highlights` 必须在响应里。"""
    resp = await client.get("/v1/courses")
    assert resp.status_code == 200
    body = resp.json()
    for field in ("mode", "fallback_reason", "next_offset", "total"):
        assert field in body, field
    assert body["mode"] == "none"
    assert "highlights" in body["items"][0]

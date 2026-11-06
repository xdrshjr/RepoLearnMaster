"""数据模型与错误码的门禁（T-DB-1 前半段、§6.2 表数量、§8.1 错误码数量）。"""

from __future__ import annotations

from repolearn.core.db import Base
from repolearn.core.errors import ERRORS, ERROR_CODE_COUNT, AppError
from repolearn.models import ALL_MODELS, SPEC_TABLE_COUNT, missing_tables, table_names


def test_table_count_matches_spec():
    """26 张表是定稿数字（§6.2）。多一张少一张都意味着 §4.4 与 §6.2 分叉了。"""
    assert len(table_names()) == SPEC_TABLE_COUNT == 26


def test_no_model_missing_from_metadata():
    assert missing_tables() == []
    assert len(ALL_MODELS) == 26


def test_model_files_one_per_table():
    """一表一文件（§4.4）：模型类名去重后数量必须与表数一致。"""
    names = [m.__tablename__ for m in ALL_MODELS]
    assert len(set(names)) == len(names)


def test_error_code_count_is_19():
    """§5.6 定稿 19 个错误码；§8.1 的门禁表述依赖这个数字。"""
    assert len(ERRORS) == ERROR_CODE_COUNT == 19


def test_every_error_code_has_message_and_http():
    for code, spec in ERRORS.items():
        assert spec.http >= 400, code
        assert spec.message, code


def test_app_error_body_shape():
    err = AppError("COURSE_NOT_READY", details={"status": "generating"})
    body = err.to_body("req_1")
    assert set(body) == {"error"}
    error = body["error"]
    assert error["code"] == "COURSE_NOT_READY"
    assert error["retryable"] is False
    assert error["req_id"] == "req_1"
    assert error["details"]["status"] == "generating"
    assert error["hint"]


def test_unknown_code_falls_back_to_internal():
    err = AppError("NOPE_NOT_A_CODE")
    assert err.code == "INTERNAL"
    assert err.status == 500


def test_retryable_defaults_by_status():
    assert AppError("RATE_LIMITED").retryable is True
    assert AppError("REPO_NOT_FOUND").retryable is False


def test_partial_unique_index_exists():
    """`llm_profiles.active` 的部分唯一索引必须真的建出来了（T-DB-3 的前提）。"""
    from sqlalchemy import text

    import asyncio

    from repolearn.core.db import engine

    async def read() -> list:
        async with engine.connect() as conn:
            rows = await conn.execute(
                text("SELECT sql FROM sqlite_master WHERE type='index' AND name='ux_llm_profiles_active'")
            )
            return [r[0] for r in rows]

    rows = asyncio.get_event_loop_policy().new_event_loop().run_until_complete(read())
    assert rows and "WHERE active = 1" in rows[0]


def test_all_tables_created():
    names = set(table_names())
    assert "quiz_attempts" in names
    assert "pdf_exports" in names
    assert "idempotency_keys" in names
    assert set(Base.metadata.tables) == names

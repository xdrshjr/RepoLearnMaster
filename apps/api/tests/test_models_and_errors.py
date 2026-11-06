"""数据模型与错误码的门禁（T-DB-1 前半段、§6.2 表数量、§8.1 错误码数量）。"""

from __future__ import annotations

from repolearn.core.db import Base
from repolearn.core.errors import ERROR_CODE_COUNT, ERRORS, AppError, strict_code_env
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


def test_error_code_count_is_20():
    """§5.6 定稿 20 个错误码（v2 加了 `VALIDATION_FAILED`，见 hardening spec P0-4）。
    §8.1 的门禁表述依赖这个数字：改码表就必须改这里。"""
    assert len(ERRORS) == ERROR_CODE_COUNT == 20


def test_validation_failed_code_shape():
    """P0-4 的落点：这个码必须真的存在，且是 422 + 不可重试。

    它以前根本不存在，而 `AppError` 对未知码静默降级成 `INTERNAL(500, 可重试)`，
    于是"offset 填成 999"会被说成"服务内部错误，请重试"——一个确定性的参数
    错误被伪装成可恢复的服务故障，用户会一直点重试。
    """
    spec = ERRORS["VALIDATION_FAILED"]
    assert spec.http == 422
    assert spec.retryable is False
    assert spec.hint and "offset" in spec.hint
    err = AppError("VALIDATION_FAILED", details={"offset": 999})
    assert err.code == "VALIDATION_FAILED"
    assert err.status == 422
    assert err.retryable is False


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


def test_unknown_code_asserts_in_test_env():
    """未知码在 `test`/`dev`/`development` 下必须**当场断言**，不许静默变 500。

    这条断言本身就是"码表是定稿"这件事的门禁：任何一处 `AppError("TYPO")`
    都会在第一个跑到它的用例里炸，而不是在生产上变成可重试的 500。
    """
    import pytest

    from repolearn.core.config import settings

    assert strict_code_env() is True, f"REPOLEARN_ENV={settings.env!r} 不是严格环境"
    with pytest.raises(AssertionError, match="未知错误码"):
        AppError("NOPE_NOT_A_CODE")


def test_unknown_code_still_degrades_outside_strict_env(monkeypatch):
    """生产环境仍然降级为 `INTERNAL`：线上宁可丢语义，也不要丢整个响应。"""
    from repolearn.core import errors as errors_mod

    monkeypatch.setattr(errors_mod, "strict_code_env", lambda: False)
    err = AppError("NOPE_NOT_A_CODE")
    assert err.code == "INTERNAL"
    assert err.status == 500
    assert err.retryable is True


def test_retryable_defaults_by_status():
    assert AppError("RATE_LIMITED").retryable is True
    assert AppError("REPO_NOT_FOUND").retryable is False


def test_partial_unique_index_exists():
    """`llm_profiles.active` 的部分唯一索引必须真的建出来了（T-DB-3 的前提）。"""
    import asyncio

    from sqlalchemy import text

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

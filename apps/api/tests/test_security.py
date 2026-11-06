"""安全门禁：日志脱敏、CSRF、内部门令、路径守卫（T-SEC-1/2/6）。"""

from __future__ import annotations

import pytest

from repolearn.core.logging import redact
from repolearn.core.security import (
    csrf_matches,
    decrypt_secret,
    encrypt_secret,
    mask_key,
    verify_internal_token,
)
from repolearn.ingest.guard import check_path, should_keep


def test_redact_masks_openai_style_keys():
    text = "failed with key sk-abcdef1234567890 in request"
    assert "sk-abcdef" not in redact(text)
    assert "sk-***" in redact(text)


def test_redact_masks_bearer_tokens():
    assert "Bearer eyJhbGciOi" not in redact("Authorization: Bearer eyJhbGciOiJIUzI1NiJ9")


def test_redact_masks_long_base64():
    """Fernet key 形态（44 字符 urlsafe base64）也必须被脱敏。"""
    key = "dGVzdC1rZXktMzItYnl0ZXMtbG9uZy1mb3ItcmVwb2xlYXJuISE="
    assert key not in redact(f"secret_key={key}")


def test_redact_keeps_normal_text():
    assert redact("课时 3.1 生成完成") == "课时 3.1 生成完成"


def test_mask_key_only_keeps_last4():
    masked = mask_key("sk-abcdefghijklmnop1234")
    assert masked.endswith("1234")
    assert "abcdefghij" not in masked


def test_encrypt_decrypt_roundtrip():
    blob = encrypt_secret("sk-secret", "prf_1")
    assert b"sk-secret" not in blob
    assert decrypt_secret(blob, "prf_1") == "sk-secret"


def test_aead_binds_profile_id():
    """AAD 绑定 profile_id：把 A 行的密文贴到 B 行必须解密失败（防跨行搬运）。"""
    blob = encrypt_secret("sk-secret", "prf_1")
    assert decrypt_secret(blob, "prf_2") == ""


def test_csrf_requires_both_sides():
    assert csrf_matches(None, "x") is False
    assert csrf_matches("x", None) is False
    assert csrf_matches("x", "y") is False
    assert csrf_matches("x", "x") is True


def test_internal_token_check():
    assert verify_internal_token("test-internal-token") is True
    assert verify_internal_token("wrong") is False
    assert verify_internal_token(None) is False


@pytest.mark.parametrize(
    "path",
    [
        "../../etc/passwd",
        "/etc/passwd",
        "C:/Windows/win.ini",
        "pkg/CON",
        "pkg/nul.txt",
        ".git/config",
        "node_modules/x/index.js",
    ],
)
def test_guard_blocks_dangerous_paths(path):
    assert check_path(path).ok is False


@pytest.mark.parametrize("path", ["pkg/mod.py", "README.md", "src/app/main.ts"])
def test_guard_allows_normal_paths(path):
    assert check_path(path).ok is True


def test_guard_sanitizes_non_ascii_names():
    decision = check_path("文档/说明.md")
    assert decision.ok is True
    assert decision.rel_path.isascii()


def test_guard_rejects_binary_and_big_files():
    assert should_keep("logo.png", 100).ok is False
    assert should_keep("artifact.exe", 100).ok is False
    assert should_keep("big.py", 5 * 1024 * 1024).ok is False
    assert should_keep("ok.py", 1000).ok is True


def test_guard_rejects_too_long_path():
    assert check_path("a" * 200 + ".py").ok is False

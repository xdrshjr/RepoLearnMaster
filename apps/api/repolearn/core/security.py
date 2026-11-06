"""密钥与 CSRF（spec §3.6.3 / §3.12）。

三个决定值得解释：

1. **不用 Fernet 而用 AES-GCM**：Fernet 是"能直接用"的方案，但它的 AAD 是空的，
   而我们需要把 `profile_id` 绑进密文（防跨行搬运）。用 AESGCM 手工拼
   `nonce || ciphertext` 只有 8 行，换来的是"把 A 行的密文贴到 B 行会解密失败"。
2. **`mask_key` 只留 last4**：出站 API 永不回传明文，last4 是唯一能让用户
   "确认自己填的是哪把 Key"的信息量下限。
3. **CSRF 双提交**：`rl_csrf` 是可读 cookie（非 HttpOnly），前端从 cookie 里读出来
   放进 `X-CSRF-Token` 头；服务端比对二者。这套机制**只在同源下成立**，这也是
   为什么 spec 把"浏览器只经 BFF"定为硬约束而不是风格选择。
"""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from repolearn.core.config import settings

_NONCE_BYTES = 12
_TAG_BYTES = 16

CSRF_COOKIE = "rl_csrf"
CSRF_HEADER = "X-CSRF-Token"
SESSION_COOKIE = "rl_session"
SETUP_COOKIE = "rl_setup"
INTERNAL_HEADER = "X-Internal-Token"
REQUEST_ID_HEADER = "X-Request-Id"


def _aad(profile_id: str) -> bytes:
    return f"llm_profile:{profile_id}".encode()


def encrypt_secret(plaintext: str, profile_id: str, key: bytes | None = None) -> bytes:
    """加密一个密钥。返回 `nonce || ciphertext(+tag)`。"""
    if not plaintext:
        return b""
    aes = AESGCM(key or settings.fernet_key)
    nonce = os.urandom(_NONCE_BYTES)
    ct = aes.encrypt(nonce, plaintext.encode("utf-8"), _aad(profile_id))
    return nonce + ct


def decrypt_secret(blob: bytes | None, profile_id: str, key: bytes | None = None) -> str:
    """解密。密钥轮换期间会用旧 key 再试一次（`REPOLEARN_SECRET_KEY_PREVIOUS`）。"""
    if not blob:
        return ""
    if len(blob) < _NONCE_BYTES + _TAG_BYTES:
        return ""
    nonce, ct = blob[:_NONCE_BYTES], blob[_NONCE_BYTES:]
    candidates = [key or settings.fernet_key]
    prev = (settings.secret_key_previous or "").strip()
    if prev and key is None:
        candidates.append(hashlib.sha256(prev.encode("utf-8")).digest())
    for k in candidates:
        try:
            return AESGCM(k).decrypt(nonce, ct, _aad(profile_id)).decode("utf-8")
        except Exception:  # noqa: BLE001 - 换 key 再试，全失败才算失败
            continue
    return ""


def last4(plaintext: str) -> str:
    return plaintext[-4:] if len(plaintext) >= 4 else "···"


def mask_key(plaintext: str | None) -> str:
    """对外展示用。永远不返回完整密钥，也不返回可被暴力还原的片段。"""
    if not plaintext:
        return ""
    if len(plaintext) <= 8:
        return "····"
    return f"···{plaintext[-4:]}"


def new_csrf_token() -> str:
    return secrets.token_urlsafe(24)


def csrf_matches(cookie_value: str | None, header_value: str | None) -> bool:
    """常量时间比较；任一缺失即失败（fail-closed）。"""
    if not cookie_value or not header_value:
        return False
    return hmac.compare_digest(cookie_value, header_value)


def verify_internal_token(header_value: str | None) -> bool:
    """BFF → API 的内部令牌校验（spec §3.12）。

    未配置令牌时（本地单跑 CLI / 冒烟测试）放行，否则一律拒绝。这个"放行"
    是显式的：它只在 `REPOLEARN_INTERNAL_TOKEN` 为空时发生，而 `start.ps1`
    首次运行一定会生成它。
    """
    expected = (settings.internal_token or "").strip()
    if not expected:
        return True
    if not header_value:
        return False
    return hmac.compare_digest(expected, header_value)


def hash_body(body: bytes) -> str:
    """幂等键的请求体指纹（规范化由调用方负责，这里只做 sha256）。"""
    return hashlib.sha256(body).hexdigest()

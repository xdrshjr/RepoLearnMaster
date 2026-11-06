"""Router 公共依赖与安全中间件（spec §5.1 / §3.12）。

三个依赖决定了整个 API 的安全姿态：

* `require_internal_token` —— 只接受经 BFF 的请求（`X-Internal-Token`）。这使
  "用户在同一台机器上另开标签页直接打 `:8000`"也不成立。未配置令牌时放行
  （仅本地 CLI / 冒烟测试），而 `start.ps1` 首次运行一定会生成它。
* `require_csrf` —— 写操作要求双提交 cookie。**同源是这套机制成立的前提**：
  跨源时 `SameSite=Lax` 的 cookie 根本不会被带上，校验会 100% 失败。
* `request_id` —— 全链路透传，前端报错弹窗带上它就能在日志里定位。
"""

from __future__ import annotations

import hashlib
import json
from typing import Annotated, Any

from fastapi import Depends, Header, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from repolearn.core.db import get_session
from repolearn.core.errors import AppError
from repolearn.core.logging import current_request_id
from repolearn.core.security import (
    CSRF_COOKIE,
    CSRF_HEADER,
    INTERNAL_HEADER,
    verify_internal_token,
)

SessionDep = Annotated[AsyncSession, Depends(get_session)]


async def require_internal_token(
    x_internal_token: Annotated[str | None, Header(alias=INTERNAL_HEADER)] = None,
) -> None:
    if not verify_internal_token(x_internal_token):
        raise AppError("INTERNAL", "缺少或错误的内部门令", status=401, details={"header": INTERNAL_HEADER})


async def require_csrf(request: Request) -> None:
    """写操作的 CSRF 双提交校验。"""
    cookie = request.cookies.get(CSRF_COOKIE)
    header = request.headers.get(CSRF_HEADER)
    if not cookie or not header:
        raise AppError(
            "INTERNAL",
            "缺少 CSRF 令牌",
            status=403,
            hint="浏览器会通过 BFF 自动带上；如果你在手工调用 API，请先 GET /v1/healthz 获取 cookie",
        )
    if cookie != header:
        raise AppError("INTERNAL", "CSRF 令牌不匹配", status=403)


def body_hash(payload: Any) -> str:
    """幂等键的请求体指纹。key 排序后再序列化，保证"同内容不同键序"算同一个请求。"""
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def req_id() -> str:
    return current_request_id()


__all__ = [
    "SessionDep",
    "body_hash",
    "req_id",
    "require_csrf",
    "require_internal_token",
    "HTTPException",
]

"""结构化日志与脱敏（spec §3.13 / P1-14）。

**请求体不落日志**是本文件存在的主要理由。配置引导的请求体里带明文 API Key，
`logger.info("request", body=body)` 这类"临时调试"是这类系统最常见的事故形态。

因此这里做两件事，而不是"记得别打 body"：
1. 中间件只记录**元数据**（method/path/status/duration/req_id/body_bytes）；
2. `redact()` 对任何字符串里出现的 `sk-`/`Bearer` 形状做替换——它是最后一道网，
   挡的是"某人在别处不小心把消息拼进日志"。
"""

from __future__ import annotations

import logging
import re
import sys
import time
from collections.abc import Awaitable, Callable

import structlog
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from repolearn.core.config import settings
from repolearn.core.security import REQUEST_ID_HEADER

_SECRET_PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9_\-]{8,}"),
    re.compile(r"Bearer\s+[A-Za-z0-9._\-]{8,}", re.IGNORECASE),
    re.compile(r"(?i)(api[_-]?key\"?\s*[:=]\s*\")([^\"']{6,})"),
    re.compile(r"[A-Za-z0-9+/]{40,}={0,2}"),  # 长 base64（Fernet key 形态）
]


def redact(value: str) -> str:
    if not value:
        return value
    out = value
    out = _SECRET_PATTERNS[0].sub("sk-***", out)
    out = _SECRET_PATTERNS[1].sub("Bearer ***", out)
    out = _SECRET_PATTERNS[2].sub(r"\1***", out)
    out = _SECRET_PATTERNS[3].sub("***", out)
    return out


def _redact_processor(_logger, _name, event_dict):  # noqa: ANN001
    for key, value in list(event_dict.items()):
        if isinstance(value, str):
            event_dict[key] = redact(value)
    return event_dict


_configured = False


def configure_logging() -> None:
    global _configured
    if _configured:
        return
    settings.log_dir.mkdir(parents=True, exist_ok=True)
    handlers: list[logging.Handler] = []
    file_handler = logging.FileHandler(settings.log_dir / "api.log", encoding="utf-8")
    handlers.append(file_handler)
    if settings.env != "production":
        handlers.append(logging.StreamHandler(sys.stdout))
    logging.basicConfig(format="%(message)s", level=logging.INFO, handlers=handlers, force=True)
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            _redact_processor,
            structlog.processors.JSONRenderer(ensure_ascii=False),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )
    _configured = True


def get_logger(name: str = "repolearn"):
    configure_logging()
    return structlog.get_logger(name)


class RequestContextMiddleware(BaseHTTPMiddleware):
    """只记元数据 + 绑定 req_id 到 structlog contextvars。

    注意这里**从不读取 `request.body()`**：一旦读了，就有人会顺手把它放进日志。
    """

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        req_id = request.headers.get(REQUEST_ID_HEADER) or f"req_{int(time.time() * 1000):x}"
        structlog.contextvars.bind_contextvars(req_id=req_id, path=request.url.path)
        started = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception as exc:  # noqa: BLE001 - 记完再抛，交给异常处理器
            duration = (time.perf_counter() - started) * 1000
            get_logger("http").error(
                "request_failed",
                method=request.method,
                path=request.url.path,
                duration_ms=round(duration, 2),
                error=redact(str(exc))[:400],
            )
            raise
        finally:
            structlog.contextvars.unbind_contextvars("path")
        duration = (time.perf_counter() - started) * 1000
        content_length = response.headers.get("content-length")
        get_logger("http").info(
            "request",
            method=request.method,
            path=request.url.path,
            status=response.status_code,
            duration_ms=round(duration, 2),
            body_bytes=int(content_length) if content_length and content_length.isdigit() else None,
            req_id=req_id,
        )
        response.headers[REQUEST_ID_HEADER] = req_id
        structlog.contextvars.unbind_contextvars("req_id")
        return response


def current_request_id() -> str:
    ctx = structlog.contextvars.get_contextvars()
    return str(ctx.get("req_id", "-"))

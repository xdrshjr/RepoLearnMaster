"""FastAPI 应用工厂（spec §3.2 / §5.1）。

lifespan 里做四件事，顺序是有讲究的：
1. **Gate 0 汇总**（读 `.run/preflight.json`）→ 打印一行一条，让"装了什么、降级到
   什么程度"在启动输出里就能看见，而不是等用户点"生成课程"才发现没有配音。
2. **迁移检查**：表不存在就报错并给出 `alembic upgrade head` 的明确指令，
   而不是让第一个请求 500。
3. **Job Runner 启动**：必须在 DB 与迁移就绪之后。
4. **reaper 首跑**：启动时立即回收僵尸 `generating` 版本（P1-13）。

`CORS 全关`（§3.12）：同源设计下不需要 CORS，保留白名单只会给未来留一个错误开关。
"""

from __future__ import annotations

import contextlib

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from repolearn import __version__
from repolearn.core.config import settings
from repolearn.core.db import dispose_engine
from repolearn.core.errors import ERRORS, AppError
from repolearn.core.logging import RequestContextMiddleware, configure_logging, get_logger
from repolearn.core.security import CSRF_COOKIE, new_csrf_token
from repolearn.routers import ALL_ROUTERS
from repolearn.routers.health import _gates

log = get_logger("app")


def _print_gates() -> None:
    gates = _gates()
    line = " ".join(f"{k.upper()} {v}" for k, v in sorted(gates.items()))
    log.info("gate0", summary=line or "G1 unknown G2 unknown G3 unknown")


async def _check_migration() -> bool:
    from sqlalchemy import text

    from repolearn.core.db import session_scope

    try:
        async with session_scope() as session:
            await session.execute(text("SELECT version_num FROM alembic_version LIMIT 1"))
        return True
    except Exception:  # noqa: BLE001 - 表不存在 = 没迁移
        return False


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()
    settings.ensure_dirs()
    _print_gates()
    migrated = await _check_migration()
    if not migrated:
        log.error("migration_missing", hint="运行 `python -m repolearn.cli migrate` 或 `alembic upgrade head`")
    from repolearn.jobs.runner import reap_orphaned_generations, requeue_stale_jobs, start_runner, stop_runner

    # 凭据发现要跑子进程（gh / git credential），启动时做一次而不是让第一个导入
    # 去等它；失败只记一条日志，不影响启动（最坏情况是回到未认证 60 次/小时）。
    try:
        from repolearn.ingest.github_auth import warm_up_token

        auth = await warm_up_token()
        if auth.configured:
            log.info("github_auth_ready", source=auth.source)
        else:
            log.warning("github_auth_missing", detail=auth.skipped_reason or ", ".join(auth.tried))
    except Exception as exc:  # noqa: BLE001 - 凭据发现失败不该让 API 起不来
        log.warning("github_auth_probe_failed", error=str(exc)[:200])

    try:
        await reap_orphaned_generations()
        await requeue_stale_jobs()
    except Exception as exc:  # noqa: BLE001 - 启动自检失败不应该让 API 起不来
        log.warning("startup_housekeeping_failed", error=str(exc))
    runner = await start_runner()
    log.info("api_started", version=__version__, env=settings.env, worker=runner.__class__.__name__)
    try:
        yield
    finally:
        await stop_runner()
        await dispose_engine()
        log.info("api_stopped")


def create_app() -> FastAPI:
    app = FastAPI(
        title="RepoLearn API",
        version=__version__,
        description="输入 GitHub 仓库，生成三层 AI 带读课程。浏览器只经 BFF 访问本服务（同源约束）。",
        lifespan=lifespan,
        docs_url="/docs" if settings.env != "production" else None,
        redoc_url=None,
        openapi_url="/openapi.json",
    )

    app.add_middleware(RequestContextMiddleware)

    for router in ALL_ROUTERS:
        app.include_router(router)

    @app.middleware("http")
    async def _csrf_bootstrap(request: Request, call_next):  # noqa: ANN001
        """给每个响应补一个 CSRF cookie（双提交的"读"侧）。

        为什么在这里而不是某个端点：BFF 与浏览器都可能先请求任意一个 GET
        才开始写操作，cookie 必须在那之前就存在。
        """
        response = await call_next(request)
        if CSRF_COOKIE not in request.cookies:
            response.set_cookie(
                CSRF_COOKIE,
                new_csrf_token(),
                httponly=False,  # 必须可被前端 JS 读取（双提交）
                samesite="lax",
                secure=settings.env == "production",
                path="/",
            )
        return response

    @app.exception_handler(AppError)
    async def _app_error_handler(request: Request, exc: AppError) -> JSONResponse:
        from repolearn.core.logging import current_request_id

        req_id = current_request_id()
        log.info("app_error", code=exc.code, status=exc.status, path=request.url.path, req_id=req_id)
        return JSONResponse(status_code=exc.status, content=exc.to_body(req_id))

    @app.exception_handler(RequestValidationError)
    async def _request_validation_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
        """参数校验失败 → **契约里的错误信封**，不是 FastAPI 的 `{"detail": [...]}`。

        为什么非改不可：`Query(ge=0, le=200)` 这类声明由 FastAPI 在进入处理函数
        之前拦下，默认响应体里没有 `error.code`。前端 `client.ts` 读不到 `code`
        就会回落成 `INTERNAL`，于是"offset 填了 999"在用户眼里仍然是"服务内部
        错误"——这正是 spec P0-4 要消灭的那类谎言，只是从 500 挪到了 422。
        统一转成第 20 个码之后，`retryable=false`、可定位到具体字段，前端文案表
        也能命中。
        """
        from repolearn.core.logging import current_request_id

        req_id = current_request_id()
        fields = [
            {
                "field": ".".join(str(part) for part in err.get("loc", ()) if part != "body"),
                "message": str(err.get("msg", "")),
            }
            for err in exc.errors()[:5]
        ]
        failure = AppError(
            "VALIDATION_FAILED",
            "请求参数不符合契约",
            hint="检查参数名与取值范围（如 offset ≤ 200、q 长度 ≤ 120、mode ∈ auto|scan|fts）",
            details={"fields": fields},
        )
        log.info("validation_error", path=request.url.path, fields=fields, req_id=req_id)
        return JSONResponse(status_code=failure.status, content=failure.to_body(req_id))

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
        from repolearn.core.logging import current_request_id, redact

        req_id = current_request_id()
        log.error("unhandled_error", path=request.url.path, error=redact(str(exc))[:400], req_id=req_id)
        fallback = AppError("INTERNAL", "服务内部错误")
        return JSONResponse(status_code=500, content=fallback.to_body(req_id))

    @app.get("/v1/errors", include_in_schema=False)
    async def list_error_codes() -> dict:
        """把错误码表暴露给前端调试用（也是 20 个码的单一真源）。"""
        return {
            "count": len(ERRORS),
            "codes": [
                {"code": code, "http": spec.http, "message": spec.message, "hint": spec.hint}
                for code, spec in sorted(ERRORS.items())
            ],
        }

    return app


app = create_app()

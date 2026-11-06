"""健康检查（spec §5.2 `/healthz`）。

`/healthz` 必须回答三件事，而不是只回 200：
1. 数据库可用吗？
2. Kernel 可用吗（A/B/C 哪一条）？
3. 迁移到 head 了吗？Gate 0 三态是什么？

因为 `start.ps1` 就是靠它判断"能不能打开浏览器"，而"启动成功但功能静默缺失"
是本项目明确拒绝的一种失败形态（spec §2.4）。
"""

from __future__ import annotations

import json

from fastapi import APIRouter
from sqlalchemy import text

from repolearn import __version__
from repolearn.core.config import settings
from repolearn.core.db import check_db
from repolearn.providers.agent_runtime import refresh_state
from repolearn.routers.deps import SessionDep
from repolearn.schemas.job import HealthResponse

router = APIRouter(tags=["system"])


def _gates() -> dict[str, str]:
    path = settings.run_path / "preflight.json"
    if not path.is_file():
        return {"g1": "unknown", "g2": "unknown", "g3": "unknown"}
    try:
        # utf-8-sig：PowerShell 的 -Encoding UTF8 会写 BOM
        data = json.loads(path.read_text(encoding="utf-8-sig"))
        return {k: str(v) for k, v in (data.get("gates") or {}).items()}
    except Exception:  # noqa: BLE001
        return {"g1": "unknown", "g2": "unknown", "g3": "unknown"}


async def _migration_ok(session) -> bool:
    try:
        rows = (await session.execute(text("SELECT version_num FROM alembic_version"))).scalars().all()
        return bool(rows)
    except Exception:  # noqa: BLE001 - 表不存在 = 没迁移
        return False


@router.get("/healthz", response_model=HealthResponse)
async def healthz(session: SessionDep) -> HealthResponse:
    db_ok = await check_db()
    state = await refresh_state()
    migration_ok = await _migration_ok(session)
    return HealthResponse(
        ok=db_ok and migration_ok,
        db=db_ok,
        kernel=state.kernel_ok,
        migration=migration_ok,
        version=__version__,
        gates=_gates(),
    )


@router.get("/v1/metrics")
async def metrics(session: SessionDep):
    from repolearn.services.job_service import metrics as build_metrics

    return await build_metrics(session)

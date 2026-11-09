"""配置引导与设置服务（spec §3.6 / §3.7 / §5.2 第一组）。

密钥处理的三条硬规则都在这里落地：
* 落库只存 `api_key_ciphertext`（AES-GCM，AAD 绑定 profile_id，防跨行搬运）；
* 出站只回 `api_key_last4` / `has_key`，**永不回传明文**；
* `settings_revisions.payload` 不含任何密文——回滚只回滚"引用与分配"，
  不会把已被轮换掉的旧密钥复活（P2-2）。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from repolearn.core.clock import utcnow
from repolearn.core.config import settings
from repolearn.core.errors import AppError
from repolearn.core.ids import new_id
from repolearn.core.logging import get_logger
from repolearn.core.security import decrypt_secret, encrypt_secret, last4
from repolearn.models import LlmProfile, ModelCatalog, SettingRevision
from repolearn.providers.agent_runtime import refresh_state
from repolearn.providers.base import LlmConfig
from repolearn.providers.registry import ROLES, adapter_for
from repolearn.schemas.setup import (
    ActiveProfile,
    Gates,
    KernelState,
    LlmProbeRequest,
    LlmProbeResponse,
    ModelCapability,
    ModelItem,
    ProbeError,
    RoleAssignment,
    SetupCommitRequest,
    SetupStateResponse,
    TtsProbeRequest,
    TtsProbeResponse,
)

log = get_logger("setup")

#: 只有确实"不再工作"的供应商才要求重探；这里保持简单：探测结果 7 天有效。
PROBE_TTL_DAYS = 7


# --------------------------------------------------------------------------- #
# 读取                                                                         #
# --------------------------------------------------------------------------- #


async def active_profile(session) -> LlmProfile | None:
    """取唯一 active profile。

    部分唯一索引保证最多一行；但历史数据里可能有 0 行（首启）或多行（约束加之前
    写入的），因此这里按 `created_at desc` 取一行并记录异常，而不是 `scalar_one()` 抛错。
    """
    rows = (
        await session.execute(select(LlmProfile).where(LlmProfile.active.is_(True)).order_by(LlmProfile.created_at.desc()))
    ).scalars().all()
    if len(rows) > 1:
        log.error("multiple_active_profiles", count=len(rows))
    return rows[0] if rows else None


def profile_llm_configs(profile: LlmProfile) -> tuple[dict[str, LlmConfig], dict[str, str]]:
    """把 profile 拆成 `{model_id: LlmConfig}` 与 `{role: model_id}`。"""
    api_key = decrypt_secret(profile.api_key_ciphertext, profile.id)
    roles: dict[str, str] = dict(profile.roles or {})
    model_ids = {v for v in roles.values() if v}
    configs = {
        model_id: LlmConfig(
            protocol=profile.protocol,
            api_key=api_key,
            base_url=profile.base_url,
            org=profile.org,
            model_id=model_id,
            provider=profile.provider,
        )
        for model_id in model_ids
    }
    return configs, {role: (roles.get(role) or "") for role in ROLES}


async def setup_state(session) -> SetupStateResponse:
    profile = await active_profile(session)
    state = await refresh_state()
    gates = _read_preflight()
    last_probe = dict(profile.last_probe or {}) if profile else {}
    required = profile is None or not bool(last_probe.get("ok", False))
    steps_done: list[int] = []
    if profile is not None:
        steps_done.append(1)
        if last_probe:
            steps_done.append(2)
        if last_probe.get("tts"):
            steps_done.append(3)
        if (profile.roles or {}).get("planner"):
            steps_done.append(4)
        if not required:
            steps_done.append(5)
    return SetupStateResponse(
        required=required,
        next_step=(max(steps_done) + 1) if steps_done and max(steps_done) < 5 else (1 if required else 5),
        steps_done=sorted(set(steps_done)),
        active_profile=(
            ActiveProfile(
                id=profile.id,
                provider=profile.provider,
                protocol=profile.protocol,
                models=[m for m in (profile.roles or {}).values() if m],
            )
            if profile
            else None
        ),
        kernel=KernelState(ok=state.kernel_ok, runtime=state.mode),
        gates=Gates(g1=gates.get("g1", "unknown"), g2=gates.get("g2", "unknown"), g3=gates.get("g3", "unknown")),
        roles={k: str(v or "") for k, v in (profile.roles or {}).items()} if profile else {},
    )


def _read_preflight() -> dict[str, str]:
    import json

    path = settings.run_path / "preflight.json"
    if not path.is_file():
        return {}
    try:
        # utf-8-sig: PowerShell 的 -Encoding UTF8 会写 BOM，普通 utf-8 读会失败 → gates 全 unknown
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:  # noqa: BLE001
        return {}
    return {k: str(v) for k, v in (data.get("gates") or {}).items()}


# --------------------------------------------------------------------------- #
# 探测                                                                         #
# --------------------------------------------------------------------------- #


async def probe_llm(req: LlmProbeRequest) -> LlmProbeResponse:
    """`probe` 是**测量接口**：失败也是 200 + `ok=false`（spec §5.2 P2-1）。

    这不是"懒得处理异常"——被测量的对象失败本身就是它的正常返回。但 `error`
    仍用 `{code,message,hint,retryable}` 同一形状，前端的错误渲染逻辑不需要分叉。
    """
    adapter = adapter_for(req.protocol)
    config = LlmConfig(
        protocol=req.protocol,
        api_key=req.api_key,
        base_url=req.base_url,
        org=req.org,
        model_id=req.model_id or "",
        provider=req.provider,
    )
    try:
        result = await adapter.probe(config)
    except Exception as exc:  # noqa: BLE001 - 任何异常都转成"测量结果"
        return LlmProbeResponse(
            ok=False,
            error=ProbeError(code="PROVIDER_UNAVAILABLE", message=str(exc)[:300], retryable=True),
        )
    if not result.ok:
        err = result.error or {}
        return LlmProbeResponse(
            ok=False,
            latency_ms=result.latency_ms,
            error=ProbeError(
                code=str(err.get("code", "PROVIDER_UNAVAILABLE")),
                message=str(err.get("message", "连接失败")),
                hint=err.get("hint"),
                retryable=bool(err.get("retryable", True)),
            ),
        )
    return LlmProbeResponse(
        ok=True,
        latency_ms=result.latency_ms,
        models=[
            ModelItem(
                id=m.id,
                display_name=m.display_name or m.id,
                capabilities=ModelCapability(**m.capabilities.as_dict()),
                context_window=m.context_window or m.capabilities.context_window,
                price=m.price,
            )
            for m in result.models[:80]
        ],
    )


async def probe_tts(req: TtsProbeRequest) -> TtsProbeResponse:
    from repolearn.providers.tts.doubao import DoubaoTts, TtsConfigIn

    cfg = TtsConfigIn(
        app_id=req.app_id,
        access_token=req.access_token,
        cluster=req.cluster,
        voice_type=req.voice_type or settings.doubao_voice_type,
    )
    client = DoubaoTts(cfg)
    result = await client.probe(req.text)
    if not result.ok:
        err = result.error or {}
        return TtsProbeResponse(
            ok=False,
            latency_ms=result.latency_ms,
            error=ProbeError(
                code=str(err.get("code", "PROVIDER_UNAVAILABLE")),
                message=str(err.get("message", "合成失败")),
                hint=err.get("hint") or "确认 appid/cluster/access_token 来自火山引擎语音合成服务",
                retryable=bool(err.get("retryable", True)),
            ),
        )
    from repolearn.services import object_store

    key = object_store.put_content_addressed("audio", result.audio_bytes, ".mp3")
    return TtsProbeResponse(
        ok=True,
        latency_ms=result.latency_ms,
        sample_audio_url=object_store.public_url("audio", key),
        duration_ms=result.duration_ms,
    )


# --------------------------------------------------------------------------- #
# 提交                                                                         #
# --------------------------------------------------------------------------- #


async def commit_setup(session, req: SetupCommitRequest) -> tuple[LlmProfile, int, list[str]]:
    warnings: list[str] = []
    profile_id = new_id("profile")
    roles = req.roles.model_dump() if isinstance(req.roles, RoleAssignment) else dict(req.roles)
    for role in ("planner", "writer", "critic"):
        if not str(roles.get(role) or "").strip():
            raise AppError("NO_MODEL_FOR_ROLE", f"角色 {role} 必须指定模型", details={"role": role})
    if not str(roles.get("vision") or "").strip():
        warnings.append("未配置 vision 角色：README 图片理解会跳过（VISION_SKIPPED）")

    cipher = encrypt_secret(req.llm.api_key, profile_id) if req.llm.api_key else b""
    profile = LlmProfile(
        id=profile_id,
        label=req.llm.label or f"{req.llm.provider} · {req.llm.protocol}",
        provider=req.llm.provider,
        protocol=req.llm.protocol,
        base_url=req.llm.base_url,
        api_key_ciphertext=cipher,
        api_key_last4=last4(req.llm.api_key) if req.llm.api_key else "",
        org=req.llm.org,
        active=False,
        last_probe={"ok": True, "tts": bool(req.tts), "at": utcnow().isoformat(), "model_id": req.llm.model_id},
        roles=roles,
        created_at=utcnow(),
    )
    session.add(profile)
    await session.flush()

    revision, _ = await _activate(session, profile)
    await _upsert_catalog(session, req.llm.provider, roles)
    log.info("setup_committed", profile_id=profile_id, revision=revision)
    return profile, revision, warnings


async def _activate(session, profile: LlmProfile) -> tuple[int, list[str]]:
    """在同一事务内先全部置 0 再置目标 1。

    靠部分唯一索引在并发下把一个事务拒掉（→ `PROFILE_CONFLICT`），
    而不是留下两个 active 行。
    """
    rows = (await session.execute(select(LlmProfile).where(LlmProfile.active.is_(True)))).scalars().all()
    for row in rows:
        row.active = False
    await session.flush()
    profile.active = True
    try:
        await session.flush()
    except IntegrityError as exc:
        await session.rollback()
        raise AppError("PROFILE_CONFLICT") from exc
    return await _write_revision(session, profile, summary=f"激活配置 {profile.label}")


async def _write_revision(session, profile: LlmProfile, *, summary: str, changes: list[str] | None = None) -> tuple[int, list[str]]:
    last = (await session.execute(select(SettingRevision).order_by(SettingRevision.rev.desc()).limit(1))).scalar_one_or_none()
    rev = (last.rev if last else 0) + 1
    payload = {
        "profile_id": profile.id,
        "provider": profile.provider,
        "protocol": profile.protocol,
        "base_url": profile.base_url,
        "model_id": (profile.last_probe or {}).get("model_id"),
        "roles": dict(profile.roles or {}),
    }
    if last is not None:
        last.is_active = False
    session.add(
        SettingRevision(
            id=new_id("revision"),
            rev=rev,
            summary=summary,
            changes=changes or ["profile", "roles"],
            payload=payload,
            author="local",
            is_active=True,
            created_at=utcnow(),
        )
    )
    await session.flush()
    return rev, []


async def _upsert_catalog(session, provider: str, roles: dict[str, str]) -> None:
    from repolearn.providers.llm import model_catalog

    for model_id in {v for v in roles.values() if v}:
        existing = (
            await session.execute(
                select(ModelCatalog).where(ModelCatalog.provider == provider, ModelCatalog.model_id == model_id)
            )
        ).scalar_one_or_none()
        caps = model_catalog.capabilities_for(provider, model_id)
        if existing is None:
            session.add(
                ModelCatalog(
                    id=new_id("profile"),
                    provider=provider,
                    model_id=model_id,
                    display_name=model_id,
                    capabilities=caps.as_dict(),
                    context_window=caps.context_window,
                    price_in=caps.price_in,
                    price_out=caps.price_out,
                    probed_at=utcnow(),
                    created_at=utcnow(),
                )
            )
        else:
            existing.capabilities = caps.as_dict()
            existing.context_window = caps.context_window
            existing.price_in = caps.price_in
            existing.price_out = caps.price_out
            existing.probed_at = utcnow()
    await session.flush()


# --------------------------------------------------------------------------- #
# 设置页用                                                                     #
# --------------------------------------------------------------------------- #


async def list_profiles(session) -> list[dict[str, Any]]:
    rows = (await session.execute(select(LlmProfile).order_by(LlmProfile.created_at.desc()))).scalars().all()
    out: list[dict[str, Any]] = []
    for row in rows:
        out.append(
            {
                "id": row.id,
                "label": row.label,
                "provider": row.provider,
                "protocol": row.protocol,
                "base_url": row.base_url,
                "model_count": len([v for v in (row.roles or {}).values() if v]),
                "api_key_last4": row.api_key_last4,
                "active": bool(row.active),
                "last_probe": dict(row.last_probe or {}),
                "created_at": row.created_at.isoformat() if row.created_at else None,
            }
        )
    return out


async def activate_profile(session, profile_id: str) -> int:
    profile = await session.get(LlmProfile, profile_id)
    if profile is None:
        raise AppError("INTERNAL", "配置不存在", status=404)
    revision, _ = await _activate(session, profile)
    return revision


async def patch_roles(session, roles: dict[str, str]) -> int:
    profile = await active_profile(session)
    if profile is None:
        raise AppError("SETUP_REQUIRED")
    merged = dict(profile.roles or {})
    for role, model in roles.items():
        if role not in ROLES:
            continue
        merged[role] = model
    profile.roles = merged
    await session.flush()
    revision, _ = await _write_revision(session, profile, summary="更新角色分配", changes=[f"roles.{r}" for r in roles])
    return revision


async def list_revisions(session, limit: int = 20) -> list[dict[str, Any]]:
    rows = (
        await session.execute(select(SettingRevision).order_by(SettingRevision.rev.desc()).limit(limit))
    ).scalars().all()
    return [
        {
            "id": row.id,
            "rev": row.rev,
            "created_at": row.created_at.isoformat() if row.created_at else None,
            "author": row.author,
            "summary": row.summary,
            "changes": list(row.changes or []),
        }
        for row in rows
    ]


async def rollback(session, rev: int) -> int:
    """回滚 = 读旧 payload 并**插入新 revision**。

    不修改旧行：历史必须可读（"谁在什么时候改了什么"是排错的第一手证据），
    而"当前生效的是哪一条"由 `is_active` 表达。
    """
    target = (await session.execute(select(SettingRevision).where(SettingRevision.rev == rev))).scalar_one_or_none()
    if target is None:
        raise AppError("INTERNAL", f"revision {rev} 不存在", status=404)
    payload = dict(target.payload or {})
    profile_id = str(payload.get("profile_id") or "")
    profile = await session.get(LlmProfile, profile_id) if profile_id else None
    if profile is not None:
        profile.roles = dict(payload.get("roles") or {})
        await session.flush()
        revision, _ = await _activate(session, profile)
        return revision
    latest = (await session.execute(select(SettingRevision).order_by(SettingRevision.rev.desc()).limit(1))).scalar_one()
    session.add(
        SettingRevision(
            id=new_id("revision"),
            rev=latest.rev + 1,
            summary=f"回滚到 rev {rev}",
            changes=[f"rollback:{rev}"],
            payload=payload,
            author="local",
            is_active=True,
            created_at=utcnow(),
        )
    )
    await session.flush()
    return latest.rev + 1


async def rotate_secret(session, new_secret: str) -> int:
    """用新密钥重加密全部 profile。失败回滚（同一事务）。

    注意：这里改的是**进程内的设置对象**，因此调用方必须在事务提交后再刷新
    `settings.secret_key`，否则会出现"库里是新密文、内存里还是旧 key"的窗口。
    """
    raw = (new_secret or "").strip()
    if len(raw) < 16:
        raise AppError("VALIDATION_FAILED", "新密钥至少 16 个字符", details={"field": "new_secret"})
    rows = (await session.execute(select(LlmProfile))).scalars().all()
    old_secret = (settings.secret_key or "").strip()
    key = _normalize_secret(raw)
    rotated = 0
    for row in rows:
        plain = decrypt_secret(row.api_key_ciphertext, row.id)
        if not plain:
            continue
        row.api_key_ciphertext = encrypt_secret(plain, row.id, key=key)
        row.rotated_at = utcnow()
        rotated += 1
    await session.flush()
    # 显式提交：密文与"现役密钥"必须同时生效，中间不能留可观测窗口。
    await session.commit()
    settings.secret_key = raw
    if old_secret:
        settings.secret_key_previous = old_secret
    persisted = _write_env_secret(raw, old_secret)
    if not persisted:
        log.warning("secret_rotated_not_persisted", rotated=rotated)
    log.info("secret_rotated", rotated=rotated, persisted=persisted)
    return rotated


def _normalize_secret(raw: str) -> bytes:
    """与 `Settings.fernet_key` 完全一致的归一化，避免两处口径漂移。"""
    import base64
    import hashlib

    try:
        decoded = base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4))
        if len(decoded) == 32:
            return decoded
    except Exception:  # noqa: BLE001 - 任意非法 base64 都走口令派生
        pass
    return hashlib.sha256(raw.encode("utf-8")).digest()


def _write_env_secret(new_secret: str, old_secret: str) -> bool:
    """把新密钥写回仓库根的 `.env`。没有 `.env` 时返回 False（不新建文件）。

    为什么不"下次启动再说"：`.env` 是唯一的持久化位置，内存里的密钥活不过
    这次重启；只改内存等于把故障推迟到下一次重启，而那时用户早已忘了轮换过。
    """
    from repolearn.core.config import REPO_ROOT

    path = REPO_ROOT / ".env"
    if not path.exists():
        return False
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
        out: list[str] = []
        seen_key = seen_prev = False
        for line in lines:
            if line.startswith("REPOLEARN_SECRET_KEY="):
                out.append(f"REPOLEARN_SECRET_KEY={new_secret}")
                seen_key = True
                continue
            if line.startswith("REPOLEARN_SECRET_KEY_PREVIOUS="):
                out.append(f"REPOLEARN_SECRET_KEY_PREVIOUS={old_secret}")
                seen_prev = True
                continue
            out.append(line)
        if not seen_key:
            out.append(f"REPOLEARN_SECRET_KEY={new_secret}")
        if old_secret and not seen_prev:
            out.append(f"REPOLEARN_SECRET_KEY_PREVIOUS={old_secret}")
        path.write_text("\n".join(out) + "\n", encoding="utf-8")
        return True
    except OSError as exc:  # noqa: BLE001 - 只读文件系统等
        log.error("env_write_failed", error=str(exc))
        return False


async def doctor(session) -> list[dict[str, Any]]:
    """Doctor 面板（spec §3.5.4 / §5.2）。一条一项，**状态与 hint 都要可执行**。"""
    from sqlalchemy import text

    from repolearn.core.db import check_db
    from repolearn.providers.agent_runtime import refresh_state as refresh
    from repolearn.rendering.pdf import chromium_available_async

    checks: list[dict[str, Any]] = []
    db_ok = await check_db()
    checks.append({"name": "数据库", "status": "ok" if db_ok else "fail", "detail": settings.database_url, "hint": None if db_ok else "检查 REPOLEARN_DATABASE_URL 与 var/data 目录权限"})

    gates = _read_preflight()
    state = await refresh()
    checks.append(
        {
            "name": "Agent 内核",
            "status": "ok" if state.mode == "kernel" else "degraded",
            "detail": f"{state.mode} · {state.reason} · core={state.core_version or '不可用'}",
            "hint": None
            if state.mode == "kernel"
            else "运行 `pnpm -C services/agent-kernel install` 并确认 npm registry 可达；否则课程将为简化版",
        }
    )
    chromium_ok = await chromium_available_async()
    checks.append(
        {
            "name": "PDF 引擎（Chromium）",
            "status": "ok" if chromium_ok else "degraded",
            # `detail` 给的是**这次真 launch 的结果**，preflight 里的 g2 只作旁证：
            # 只看 preflight 等于相信"另一个进程说过它能起来"，而 PDF 是在本进程里
            # 渲染的（异步上下文还得走 `chromium_available_async`，见 pdf.py）。
            "detail": f"launch={'ok' if chromium_ok else 'failed'} · preflight g2={gates.get('g2', 'unknown')}",
            "hint": None
            if chromium_ok
            else "运行 `python -m playwright install chromium`；否则导出将降级为打印视图",
        }
    )
    checks.append(
        {
            "name": "语法分析（tree-sitter）",
            "status": "ok" if _ts_available() else "degraded",
            "detail": gates.get("g3", "unknown"),
            "hint": None if _ts_available() else "`pip install tree-sitter-language-pack` 以提升锚点置信度",
        }
    )
    profile = await active_profile(session)
    checks.append(
        {
            "name": "模型配置",
            "status": "ok" if profile else "fail",
            "detail": profile.label if profile else "尚未配置",
            "hint": None if profile else "打开 /setup 完成配置引导",
        }
    )
    # 这里过去只看 `doubao_app_id and doubao_access_token`，于是：
    # * 换成 qwen 时永远显示"未配置"；
    # * 更糟的是它只证明"变量非空"，不证明 TTS 真的接进了生成流程。
    # 现在统一走 `tts.describe()`，detail 里带上 provider 与音色。
    from repolearn.providers.tts import describe as describe_tts

    tts_state = describe_tts()
    if tts_state["provider"] == "none":
        tts_status, tts_detail = "degraded", "已关闭（强制字幕模式）"
        tts_hint = "REPOLEARN_TTS_PROVIDER=none：课程只走字幕推进"
    elif tts_state["configured"]:
        tts_status, tts_detail = "ok", f"{tts_state['provider']} · {tts_state['voice'] or '默认音色'}"
        tts_hint = None
    else:
        tts_status = "degraded"
        missing = "REPOLEARN_QWEN_API_KEY" if tts_state["provider"] == "qwen" else "REPOLEARN_DOUBAO_APP_ID / REPOLEARN_DOUBAO_ACCESS_TOKEN"
        tts_detail = f"{tts_state['provider']} 未配置凭据"
        tts_hint = f"在 .env 里填 {missing} 后重启 API；未配置时课程自动切换为字幕推进模式"
    checks.append(
        {
            "name": "语音服务（TTS）",
            "status": tts_status,
            "detail": tts_detail,
            "hint": tts_hint,
        }
    )
    # 「GitHub 凭据」这一项的判据是**进程里实际用到的凭据**，不是"文件里写了没"：
    # 显式的 .env 值优先，其次是本机已登录凭据（gh CLI / Git Credential Manager）。
    from repolearn.ingest.github import token_diagnostics
    from repolearn.ingest.github_auth import local_tooling

    token = token_diagnostics()
    if token["configured"]:
        token_hint = None
        if token["padded"]:
            token_hint = (
                "值里有首尾空白（dotenv 会保留它，GitHub 会因此回 401 Bad credentials）；"
                "请删掉等号后的空格并存成不带空白的值"
            )
        checks.append(
            {
                "name": "GitHub 凭据",
                "status": "ok",
                "detail": (
                    f"已配置 {token['fingerprint']}（来源 {token['source']}，"
                    f"长度 {token['length']}，上限 5000 次/小时）"
                ),
                "hint": token_hint,
            }
        )
    else:
        tools = local_tooling()
        fix = "`gh auth login`" if tools["gh"] else "让 Git Credential Manager 记住 github.com（`git config --global credential.helper manager` 后 `git ls-remote https://github.com/octocat/Hello-World`）"
        checks.append(
            {
                "name": "GitHub 凭据",
                "status": "degraded",
                "detail": "未找到凭据 → 未认证调用，上限 60 次/小时",
                "hint": f"{token['detail']}；修法：{fix}，或直接在 .env 填 REPOLEARN_GITHUB_TOKEN，然后重启 API",
            }
        )
    checks.append(
        {
            "name": "GitHub 接入点",
            "status": "ok",
            "detail": f"{settings.github_api} · token={'是' if token['configured'] else '否'}",
            "hint": None
            if settings.github_api == "https://api.github.com"
            else "已指向自定义端点（GHE/镜像）；端点返回内容按不可信数据处理",
        }
    )
    checks.append(await _search_check(session))
    try:
        async with session.begin_nested():
            await session.execute(text("SELECT 1"))
        checks.append({"name": "会话", "status": "ok", "detail": "可用", "hint": None})
    except Exception as exc:  # noqa: BLE001
        checks.append({"name": "会话", "status": "fail", "detail": str(exc)[:200], "hint": "重启服务"})
    return checks


async def _search_check(session) -> dict[str, Any]:
    """搜索项必须报**实际生效模式**，而不是配置值（hardening spec P2-4）。

    v1 直接回显 `settings.search`，而 `settings.search` 正是那个"说了 fts 却没人
    实现"的开关——照抄它等于把谎言换个地方说。判定顺序固定为：先看库里有没有
    `course_search`（表存在才算有索引），再看 SQLite 版本够不够 trigram，最后才
    看用户配了什么。三者任意一环不满足，用户看到的就是 `degraded` + 原因。
    """
    from repolearn.services.search import fts_capability

    cap = await fts_capability(session)
    if settings.search == "scan":
        return {
            "name": "搜索",
            "status": "ok",
            "detail": "scan（LIKE，limit ≤ 50）",
            "hint": "课程量 > 5000 时设 REPOLEARN_SEARCH=fts（需要 SQLite ≥ 3.34 的 FTS5 trigram）",
        }
    if cap.available:
        return {
            "name": "搜索",
            "status": "ok",
            "detail": "fts（trigram，中文 ≥3 字）",
            "hint": "1–2 字查询自动回落 LIKE：trigram 的匹配单位是 3 字符",
        }
    return {
        "name": "搜索",
        "status": "degraded",
        "detail": f"scan（{cap.reason}）",
        "hint": f"配置值是 fts，但当前运行时用不了 FTS5 trigram：{cap.detail}。升级 Python/SQLite 后自动启用",
    }


def _ts_available() -> bool:
    from repolearn.analysis.symbols import TS_AVAILABLE

    return TS_AVAILABLE


__all__ = [
    "PROBE_TTL_DAYS",
    "activate_profile",
    "active_profile",
    "commit_setup",
    "doctor",
    "list_profiles",
    "list_revisions",
    "patch_roles",
    "probe_llm",
    "probe_tts",
    "profile_llm_configs",
    "rollback",
    "rotate_secret",
]

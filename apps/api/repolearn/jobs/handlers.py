"""任务处理器（spec §3.4 整条流水线的装配处）。

这个文件把 LangGraph 节点、provider 运行时、对象存储与发布事务缝在一起。
它是唯一知道"一次课程生成需要什么"的地方——runner 只负责 claim、心跳、终态。
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from typing import Any

from repolearn.core.clock import utcnow
from repolearn.core.config import settings
from repolearn.core.db import session_scope
from repolearn.core.errors import AppError
from repolearn.core.ids import new_id
from repolearn.core.logging import get_logger
from repolearn.ingest.mirror import line_count as mirror_line_count
from repolearn.ingest.mirror import list_files, mirror_path, read_file
from repolearn.models import CourseVersion
from repolearn.providers.agent_runtime import refresh_state
from repolearn.providers.base import AgentBudget, AgentRunRequest
from repolearn.providers.budget_guard import JobBudget, estimate_tokens, usd_for
from repolearn.providers.registry import build_resolver
from repolearn.providers.tts.doubao import DoubaoTts, TtsConfigIn
from repolearn.services import object_store
from repolearn.services.setup_service import active_profile, profile_llm_configs
from repolearn.workflow import NODE_LABELS, NODE_PROGRESS, NodeContext
from repolearn.workflow.publish import publish as publish_course_assets

log = get_logger("handlers")


@dataclass
class JobOutcome:
    status: str
    message: str = ""
    error: dict | None = None
    details: dict | None = None


# --------------------------------------------------------------------------- #
# 节点上下文                                                                   #
# --------------------------------------------------------------------------- #


class _Ctx:
    """把 NodeContext 的 6 个回调实现出来。

    这里刻意**不使用全局 session**：每个回调自己开事务。原因是 N6 并发 3 个课时，
    共享一个 AsyncSession 会踩到"同一 session 并发使用"的未定义行为。
    """

    def __init__(
        self,
        *,
        job_id: str,
        course_id: str,
        resolver: Any,
        budget: JobBudget,
        tts: DoubaoTts | None,
        runtime_mode: str,
        emit: Any,
    ) -> None:
        self.job_id = job_id
        self.course_id = course_id
        self.resolver = resolver
        self.budget = budget
        self.tts = tts
        self.runtime_mode = runtime_mode
        self._emit = emit
        self.sha = ""

    # ---- 模型调用 --------------------------------------------------------
    async def run(self, role: str, system: str, prompt: str, **kwargs: Any) -> tuple[str, dict]:
        """一次 Agent run。失败时按"主模型 → 备用链"切换（spec §3.7.3）。

        `node=` 决定节点级额度（`NODE_BUDGETS` 的键是**节点名**），
        `schema=` 只用于让 Kernel 做结构化产出的校验。两者混用会让每个节点都
        落回 8k 默认值：`plan_curriculum` 该拿 20k、`simulate_trace` 只该拿 2k。
        """
        chain = self.resolver.resolve(role)
        node = str(kwargs.get("node") or role)
        per_lesson = bool(kwargs.get("per_lesson"))
        max_tokens = self.budget.node_allowance(node, per_lesson=per_lesson)
        self.budget.check()
        last_error: Exception | None = None
        for candidate in chain:
            run_id = new_id("job").replace("job_", "run_")
            req = AgentRunRequest(
                run_id=run_id,
                role=role,
                config=candidate.config,
                system_prompt=system,
                prompt=prompt,
                tools=["repo_list_tree", "repo_read_file", "repo_grep", "repo_file_outline"],
                schema_ref=kwargs.get("schema"),
                budget=AgentBudget(
                    max_turns=16,
                    max_tokens=max_tokens,
                    max_usd=max(0.01, self.budget.max_usd - self.budget.used_usd),
                    deadline_ms=int(min(self.budget.remaining_ms(), 600_000)),
                ),
                mirror_dir=str(mirror_path(self.sha)) if self.sha else None,
                job_id=self.job_id,
                metadata={"lesson_key": kwargs.get("lesson_key", "")},
            )
            from repolearn.providers.agent_runtime import get_selector

            events, result = await get_selector().run(req)
            usage = result.usage or {}
            tokens_in = int(usage.get("tokensIn", usage.get("tokens_in", 0)) or 0)
            tokens_out = int(usage.get("tokensOut", usage.get("tokens_out", 0)) or 0)
            caps = candidate.capabilities or {}
            usd = usd_for(tokens_in, tokens_out, float(caps.get("price_in", 0) or 0), float(caps.get("price_out", 0) or 0))
            self.budget.charge(tokens_in, tokens_out, usd)
            await self._record_cost(role, candidate.model_id, tokens_in, tokens_out, usd, result.runtime)

            if result.status == "completed":
                text = _extract_text(result.result)
                if text:
                    return text, {"tokens_in": tokens_in, "tokens_out": tokens_out}
                last_error = AppError("CONTRACT_VIOLATION", "Agent 未产出结构化内容")
                continue
            if result.status == "degraded":
                raise AppError("PROVIDER_UNAVAILABLE", "Agent 内核不可用", retryable=False)
            if result.status == "budget_exceeded":
                raise AppError(
                    "BUDGET_EXCEEDED",
                    str((result.error or {}).get("message", "预算耗尽")),
                    details={"role": role},
                )
            last_error = AppError(
                "PROVIDER_UNAVAILABLE",
                str((result.error or {}).get("message", "Agent 调用失败")),
                retryable=True,
            )
        raise last_error or AppError("PROVIDER_UNAVAILABLE", "没有可用模型")

    async def _record_cost(self, role: str, model_id: str, tin: int, tout: int, usd: float, runtime: str) -> None:
        from repolearn.models import CostLedger

        async with session_scope() as session:
            session.add(
                CostLedger(
                    id=new_id("event"),
                    job_id=self.job_id,
                    role=role,
                    provider=runtime,
                    model_id=model_id,
                    tokens_in=tin,
                    tokens_out=tout,
                    usd=usd,
                    created_at=utcnow(),
                )
            )

    # ---- 镜像读取 --------------------------------------------------------
    def read_file(self, path: str) -> str:
        return read_file(self.sha, path)

    def line_count(self, path: str) -> int:
        return mirror_line_count(self.sha, path)

    # ---- 产物外置 --------------------------------------------------------
    def save_artifact(self, node: str, key: str, payload: Any) -> str:
        key_path = object_store.artifact_key(self.job_id, node, key)
        object_store.put_json("artifacts", key_path, payload)
        return key_path

    def load_artifact(self, key_path: str) -> Any:
        return object_store.get_json("artifacts", key_path)

    # ---- 进度 ------------------------------------------------------------
    async def emit_progress(self, node: str, percent: int = 0) -> None:
        await self._emit(node, NODE_PROGRESS.get(node, percent))

    # ---- TTS -------------------------------------------------------------
    async def synthesize(self, lesson_key: str, segments: list[dict]) -> tuple[dict | None, str]:
        """合成**一步**的配音，返回一条可播放的音轨（不是一段）。

        语义边界很重要：调用方按 step 传 segments，返回的 `url` 覆盖这一整步，
        `duration_ms` 是这些 segment 的真实时长之和。早期实现把全课的 segment
        一次传进来、只回第一段的 url 却回总和时长，结果播放器以为音轨有 3 分钟
        而实际 8 秒就静音——这类"看起来有配音"的假象比没有配音更难排查。
        """
        if self.tts is None or not self.tts.configured:
            return None, "estimated"
        texts = [str(s.get("text", "")) for s in segments if str(s.get("text", "")).strip()]
        if not texts:
            return None, "estimated"
        from repolearn.providers.tts.doubao import text_hash
        from repolearn.providers.tts.join import join_mp3

        total_ms = 0
        pieces: list[bytes] = []
        for text in texts[:12]:
            digest = text_hash(self.tts.provider, self.tts.cfg.voice_type, self.tts.cfg.speed_ratio, text)
            cached = await _lookup_audio(digest)
            if cached:
                # 命中缓存也要把字节读回来参与拼接：缓存的是**单段**音频，
                # 而这次要交付的是整步的音轨。
                try:
                    blob = object_store.get("audio", str(cached.get("object_key", "")))
                except Exception:  # noqa: BLE001 - 缓存行在、对象被 prune 掉了
                    blob = b""
                if blob:
                    pieces.append(blob)
                    total_ms += int(cached.get("duration_ms", 0) or 0)
                    continue
            result = await self.tts.synthesize(text)
            if not result.ok or not result.audio_bytes:
                # 单段失败即整体降级为字幕：拼接不完整的音频会让时间轴失真
                return None, "estimated"
            pieces.append(result.audio_bytes)
            total_ms += result.duration_ms
            key = object_store.put_content_addressed("audio", result.audio_bytes, ".mp3")
            await _store_audio(self.tts, digest, key, result.duration_ms, result.duration_source, len(result.audio_bytes), text)
        if not pieces or total_ms <= 0:
            return None, "estimated"
        track = join_mp3(pieces)
        if not track:
            return None, "estimated"
        track_key = object_store.put_content_addressed("audio", track, ".mp3")
        return (
            {
                "url": object_store.public_url("audio", track_key),
                "duration_ms": total_ms,
                "voice": self.tts.cfg.voice_type,
            },
            "tts",
        )

    # ---- 发布 ------------------------------------------------------------
    async def publish(self, state: dict) -> dict:
        sha = str((state.get("commit") or {}).get("sha", ""))
        files = list_files(sha)
        file_lines = {}
        for item in files:
            try:
                file_lines[str(item["path"])] = mirror_line_count(sha, str(item["path"]))
            except Exception:  # noqa: BLE001
                continue
        async with session_scope() as session:
            result = await publish_course_assets(
                session,
                course_id=self.course_id,
                curriculum=state.get("curriculum") or {},
                lessons=state.get("lessons") or {},
                traces=state.get("traces") or {},
                narration=state.get("narration") or {},
                commit_sha=sha,
                file_lines=file_lines,
                warnings=state.get("warnings") or [],
                failed_lessons=state.get("failed_lessons") or [],
                runtime=str(state.get("runtime", self.runtime_mode)),
                load_artifact=self.load_artifact,
                min_lessons=settings.min_lessons_to_publish,
                min_coverage=settings.min_anchor_coverage,
                min_sections=settings.min_sections_to_publish,
            )
        return {"publish": result}


def _extract_text(result: dict) -> str:
    """从 Agent 的结构化产出里取出 lesson/curriculum/trace 的 JSON 文本。

    Kernel 的 `emit_*` 工具把内容放进了结果槽；这里把它序列化回文本交给
    `parse_and_validate` ——这样"Kernel 校验"与"Python 校验"用的是同一份 schema，
    两次校验不是重复而是**两个不同进程的独立判断**。
    """
    if not result:
        return ""
    for key in ("lessons", "traces", "quizzes"):
        bucket = result.get(key) or {}
        if isinstance(bucket, dict) and bucket:
            return json.dumps(next(iter(bucket.values())), ensure_ascii=False)
    if result.get("curriculum"):
        return json.dumps(result["curriculum"], ensure_ascii=False)
    if result.get("raw"):
        return json.dumps(result["raw"], ensure_ascii=False)
    return ""


async def _lookup_audio(digest: str) -> dict | None:
    from sqlalchemy import select

    from repolearn.models import AudioAsset

    async with session_scope() as session:
        row = (
            await session.execute(select(AudioAsset).where(AudioAsset.text_hash == digest).limit(1))
        ).scalar_one_or_none()
        if row is None:
            return None
        return {"object_key": row.object_key, "duration_ms": row.duration_ms}


async def _store_audio(
    tts: DoubaoTts, digest: str, key: str, duration_ms: int, source: str, size: int, text: str
) -> None:
    from repolearn.models import AudioAsset

    async with session_scope() as session:
        session.add(
            AudioAsset(
                id=new_id("audio"),
                provider=tts.provider,
                voice=tts.cfg.voice_type,
                speed=tts.cfg.speed_ratio,
                text_hash=digest,
                object_key=key,
                duration_ms=duration_ms,
                duration_source=source,
                bytes=size,
                created_at=utcnow(),
            )
        )


# --------------------------------------------------------------------------- #
# 课程生成主流程                                                               #
# --------------------------------------------------------------------------- #


async def run_course_job(
    *,
    job_id: str,
    course_id: str,
    payload: dict,
    emit: Any,
) -> JobOutcome:
    """N1–N9 全流程。任何异常由 runner 转成 Job 终态。"""
    runtime = await refresh_state(force=True)
    await emit("job.phase", {"node": "normalize_repo", "phase": "start", "progress": 1})

    budget = JobBudget(
        max_tokens=settings.job_max_tokens,
        max_usd=settings.job_max_usd,
        deadline_ms=settings.job_deadline_ms,
    )

    async with session_scope() as session:
        profile = await active_profile(session)
        if profile is None and runtime.mode != "template":
            # 模板降级（状态 C）**不需要**模型配置：它用的是静态分析，不是 AI。
            # 在这里也要求 SETUP_REQUIRED，会让"没有 Key 的全新克隆"连演示课程都生成不了，
            # 而那正是 Gate 0 失败时唯一能用的路径。
            raise AppError("SETUP_REQUIRED")
        if profile is None:
            configs, roles = {}, {}
        else:
            configs, roles = profile_llm_configs(profile)
        resolver = build_resolver(roles, configs)

    tts = None
    if payload.get("tts"):
        tts = DoubaoTts(TtsConfigIn(**payload["tts"]))

    async def emit_node(node: str, progress: int) -> None:
        await emit("node.completed", {"node": node, "label": NODE_LABELS.get(node, node), "progress": progress})

    ctx = _Ctx(
        job_id=job_id,
        course_id=course_id,
        resolver=resolver,
        budget=budget,
        tts=tts,
        runtime_mode=runtime.mode,
        emit=emit_node,
    )
    ctx.sha = str((payload.get("commit") or {}).get("sha", "")) if payload.get("commit") else ""

    node_ctx = NodeContext(
        run=ctx.run,
        read_file=ctx.read_file,
        line_count=ctx.line_count,
        save_artifact=ctx.save_artifact,
        emit_progress=ctx.emit_progress,
        job_id=job_id,
    )
    # NodeContext 是 dataclass，额外挂上节点需要的其余能力（publish / load / tts / 模式）
    node_ctx.load_artifact = ctx.load_artifact
    node_ctx.publish = ctx.publish
    node_ctx.synthesize = ctx.synthesize
    node_ctx.runtime_mode = runtime.mode

    # 先把 N1 需要的 repo_url 与 N2 需要的 ref 放进初始 state
    from repolearn.workflow.state import new_state

    initial = new_state(job_id, course_id)
    initial["repo"] = {"repo_url": payload.get("repo_url", "")}
    initial["commit"] = {"requested_ref": payload.get("ref")}
    initial["runtime"] = runtime.mode

    final = await _run_with_initial(node_ctx, ctx, initial)

    sha = str((final.get("commit") or {}).get("sha", ""))
    ctx.sha = sha
    # N9 返回的是 `{"publish": {...}}`，LangGraph 写回 state 后形如
    # `state["publish"] = {...}`。这里**只解一层**：多解一层会静默拿到 `{}`，
    # 于是每一次成功生成都被上报成 partial、质量报告永远是 null。
    publish_info = final.get("publish") or {}
    status = str(publish_info.get("status", "partial"))
    return JobOutcome(
        status="ready" if status == "ready" else "partial",
        message=f"课程生成完成：{publish_info.get('lesson_count', 0)} 课时",
        details={"quality_report": publish_info.get("quality_report"), "commit_sha": sha},
    )


async def _run_with_initial(node_ctx: NodeContext, ctx_obj: _Ctx, initial: dict) -> dict:
    """跑图，并在每次节点产出后把 sha 回填到 `_Ctx`。

    为什么不能一开始就知道 sha：N2 才解析出 commit。而 N3 之后的每个节点都要靠
    `ctx.sha` 去读镜像。用一个 per-node 回调回填，比"先单独跑 N1/N2 再跑图"简单，
    也不会把图的原子性拆成两段。
    """
    from repolearn.workflow.course_graph import run_graph

    async def on_node(_name: str, state: dict) -> None:
        sha = str((state.get("commit") or {}).get("sha", ""))
        if sha:
            ctx_obj.sha = sha

    return await run_graph(
        job_id=str(initial.get("job_id", "")),
        course_id=str(initial.get("course_id", "")),
        ctx=node_ctx,
        on_node=on_node,
        initial_state=initial,
    )


__all__ = ["JobOutcome", "run_course_job", "estimate_tokens", "asyncio", "CourseVersion"]

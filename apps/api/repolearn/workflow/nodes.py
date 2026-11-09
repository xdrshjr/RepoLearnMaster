"""九个节点（spec §3.4 的 N1–N9）。

每个节点都是 `(state) -> partial_update` 的纯异步函数，只依赖注入的 `NodeContext`。
这条约束让节点可以在测试里单跑（喂假 run、假镜像），也让"哪个节点坏了"这件事
在 job_events 里一目了然。

失败策略严格照 §3.4 的表写：
* N1/N2 不可重试的业务错误直接抛（404/403）；
* N3 超限降级为"核心文件子集"并写 warning；
* N5 结构化校验失败 → 修复重试 2 次 → 退化为确定性模板；
* N6 单课时失败进 `failed_lessons`，**不阻塞整体**；
* N7 校验失败逐步降级为 `teaching_simulation`；
* N8 合成失败降级为字幕（`audio=null`）；
* N9 事务失败整体回滚。
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any

from repolearn.analysis import analyze
from repolearn.core.errors import AppError
from repolearn.core.logging import get_logger
from repolearn.ingest import fetch_and_mirror, mirror_stat
from repolearn.ingest.mirror import line_count as mirror_line_count
from repolearn.ingest.mirror import list_files, read_file
from repolearn.providers.base import WRITER_AGENT_TOOLS
from repolearn.workflow.parsing import (
    check_curriculum,
    check_lesson_anchors,
    check_quiz,
    check_segments,
)
from repolearn.workflow.prompts import (
    critic_prompt,
    critic_system,
    planner_prompt,
    planner_system,
    writer_prompt,
    writer_system,
)
from repolearn.workflow.repair import produce_validated
from repolearn.workflow.simulation_guard import guard_trace, template_trace
from repolearn.workflow.state import prune_tree
from repolearn.workflow.template import build_template_curriculum, build_template_lesson

log = get_logger("nodes")

LESSON_CONCURRENCY = 3
#: 为什么这个"3"必须落在**节点入口**而不是只落在 `_write_all` 里：
#:
#: 图是用 `Send` 按课时扇出的（见 `course_graph.fan_out_lessons`）：12 个课时 →
#: **12 个并发的 `write_lessons` 节点调用**，每个调用只写一个课时，根本走不到
#: `_write_all` 里那把信号量。结果是一次真实生成会同时向内核发起 12 路 run，
#: 而内核对并发有硬上限（`MAX_CONCURRENT_RUNS=8`，超出返回 429 KERNEL_BUSY）。
#:
#: 真实故障（2026-11-09 浏览器实测，连续三次）：课程每跑到"写课时"就整个失败，
#: job 终态 `PROVIDER_UNAVAILABLE · KERNEL_BUSY`，12 个课时一个都没留下。
#: 所以闸门放在 `write_lessons` 入口，两条路径（扇出与顺序）共用它。


def make_nodes(ctx: Any) -> dict[str, Callable[[dict], Any]]:
    """把 9 个节点绑定到注入的上下文上。"""

    # 每个图/job 一把闸：同一个 `make_nodes` 产生的所有节点调用共享它，
    # 这正是 `Send` 扇出需要的共享语义（12 个并发节点调用 → 最多 3 路真并发）。
    lesson_gate = asyncio.Semaphore(LESSON_CONCURRENCY)

    async def _emit(node: str, percent: int | None = None) -> None:
        result = ctx.emit_progress(node, percent or 0)
        import inspect

        if inspect.isawaitable(result):
            await result

    # ---- N1 ---------------------------------------------------------------
    async def normalize_repo(state: dict) -> dict:
        await _emit("normalize_repo")
        url = (state.get("repo") or {}).get("repo_url") or state.get("repo_url")
        if not url:
            raise AppError("REPO_NOT_FOUND", "缺少仓库地址")
        from repolearn.ingest.github import fetch_repo_meta, parse_repo_url

        ref = parse_repo_url(str(url))
        meta = await fetch_repo_meta(ref)
        if meta.is_private:
            raise AppError("REPO_FORBIDDEN", "该仓库是私有仓库")
        return {
            "repo": {
                "full_name": meta.full_name,
                "owner": meta.owner,
                "name": meta.name,
                "description": meta.description,
                "stars": meta.stars,
                "license": meta.license_spdx,
                "language": meta.primary_language,
                "default_branch": meta.default_branch,
                "html_url": meta.html_url,
            }
        }

    # ---- N2 ---------------------------------------------------------------
    async def resolve_commit(state: dict) -> dict:
        await _emit("resolve_commit")
        from repolearn.ingest.github import parse_repo_url
        from repolearn.ingest.github import resolve_commit as gh_resolve

        repo = state.get("repo") or {}
        ref = parse_repo_url(repo.get("full_name", ""))
        wanted = (state.get("commit") or {}).get("requested_ref")
        commit = await gh_resolve(ref, repo.get("default_branch", "main"), wanted)
        return {
            "commit": {
                "sha": commit.sha,
                "committed_at": commit.committed_at,
                "message": commit.message,
                "file_count": commit.file_count,
            }
        }

    # ---- N3 ---------------------------------------------------------------
    async def fetch_repo(state: dict) -> dict:
        await _emit("fetch_repo")
        repo = state.get("repo") or {}
        commit = state.get("commit") or {}
        sha = str(commit.get("sha", ""))
        warnings: list[dict] = []
        info = mirror_stat(sha)
        if info.file_count == 0:
            outcome = await fetch_and_mirror(repo.get("full_name", ""), sha)
            if outcome.extraction is not None:
                warnings.extend(outcome.extraction.stats.as_warnings())
            info = mirror_stat(sha)
        files = list_files(sha)
        if not files:
            raise AppError("PROVIDER_UNAVAILABLE", "镜像为空，无法分析", retryable=True)
        # 写回真实文件数：`resolve_commit` 拿不到它（commits 端点的 `files` 是"本次
        # commit 改动过的文件"），镜像清单才是真值。放在 `if not files` 之后，是为了
        # 让"镜像坏了"这条路径保持原样失败，而不是先写一个 0。
        if hasattr(ctx, "persist_commit_file_count"):
            await ctx.persist_commit_file_count(len(files))
        return {
            "mirror_dir": str(info.path),
            "tree": prune_tree(files),
            "warnings": warnings,
            "commit": {**(state.get("commit") or {}), "file_count": len(files)},
        }

    # ---- N4 ---------------------------------------------------------------
    async def analyze_repo(state: dict) -> dict:
        await _emit("analyze_repo")
        sha = str((state.get("commit") or {}).get("sha", ""))
        files = list_files(sha)
        result = analyze(files, lambda p: read_file(sha, p))
        full_kg = {
            "summary": result.summary(),
            "anchors": result.knowledge_graph.anchors(300),
            "chains": [c.as_dict() for c in result.chains],
            "mermaid": result.knowledge_graph.to_mermaid(24),
        }
        artifact = ctx.save_artifact("analyze_repo", "knowledge_graph", full_kg)
        summary = result.summary()
        summary["artifact"] = artifact
        return {
            "knowledge_graph": summary,
            "chain_ids": [c.id for c in result.chains],
            "warnings": result.warnings,
        }

    # ---- N5 ---------------------------------------------------------------
    async def plan_curriculum(state: dict) -> dict:
        await _emit("plan_curriculum")
        repo = state.get("repo") or {}
        kg = state.get("knowledge_graph") or {}
        anchors = _anchors_from_artifact(kg, ctx)
        chains = _chains_from_artifact(kg, ctx)

        if ctx.runtime_mode == "template":
            # 状态 C：模板降级（不尝试 exec，不假装模型生成了东西）

            sha = str((state.get("commit") or {}).get("sha", ""))
            kg_obj = _rehydrate_kg(state, sha, ctx)
            curriculum = build_template_curriculum(repo, kg_obj, lambda p: read_file(sha, p))
            return {
                "curriculum": curriculum,
                "runtime": "template",
                "warnings": [
                    {
                        "code": "AGENT_UNAVAILABLE",
                        "message": "Agent 内核不可用，课程由静态分析模板生成（简化版）",
                        "severity": "warning",
                        "node": "plan_curriculum",
                    }
                ],
            }

        async def run(system: str, prompt: str) -> tuple[str, dict]:
            return await ctx.run("planner", system, prompt, node="plan_curriculum", schema="course")

        def _template(reason: str) -> dict:
            """N5 的**唯一**兜底出口：确定性模板（spec §3.4 N5 失败策略）。

            两条失败路径必须走同一个出口：结构契约修不好（`outcome.ok=False`）与
            预算耗尽（`ctx.run` 抛 `BUDGET_EXCEEDED`）。早期只接了前者，后者一路
            冒到 runner 把**整门课**置成 `failed_budget`——用户看到"生成失败"，
            而按设计这里本该交付一份简化版课程（真实符号、真实行号，只是讲解浅）。
            预算是一次"这次讲不了那么多"的信号，不是"这门课不该存在"的信号。
            """

            sha = str((state.get("commit") or {}).get("sha", ""))
            kg_obj = _rehydrate_kg(state, sha, ctx)
            curriculum = build_template_curriculum(repo, kg_obj, lambda p: read_file(sha, p))
            return {
                "curriculum": curriculum,
                "runtime": "template",
                "warnings": [
                    {
                        "code": "CURRICULUM_FALLBACK",
                        "message": reason,
                        "severity": "warning",
                        "node": "plan_curriculum",
                    }
                ],
            }

        try:
            outcome = await produce_validated(
                run=run,
                system=planner_system(),
                prompt=planner_prompt(repo, kg, anchors, chains),
                schema_name="course",
                extra_checks=check_curriculum,
            )
        except AppError as exc:
            if exc.code != "BUDGET_EXCEEDED":
                raise
            return _template(f"规划阶段预算耗尽，已退化为确定性模板（{exc.message}）")

        if not outcome.ok:
            return _template(f"课程骨架多次不满足结构契约，已退化为确定性模板：{'; '.join(outcome.errors[:3])}")
        curriculum = dict(outcome.data)
        curriculum["_usage"] = outcome.usage
        return {"curriculum": curriculum, "warnings": []}

    # ---- N6 ---------------------------------------------------------------
    async def write_lessons(state: dict) -> dict:
        await _emit("write_lessons")
        lesson_plan = state.get("current_lesson") or {}
        if not lesson_plan:
            # 顺序执行路径：一次性处理全部课时
            return await _write_all(state)
        # 扇出路径：这里也必须过闸，否则 12 个 Send 分支会同时打内核（见 LESSON_CONCURRENCY）
        async with lesson_gate:
            try:
                return await _write_one(state, lesson_plan)
            except Exception as exc:  # noqa: BLE001
                # **扇出路径同样要隔离单课时失败**（图路径没有 `_write_all` 那层 try）。
                #
                # 真实故障（2026-11-09 浏览器实测，job job_01M6ZE5PWRJ2Z0ZK7HPQA2F0A0）：
                # 11 个课时生成成功，第 12 个撞上节点 token 分闸，异常从 LangGraph 节点
                # 直接穿到 `graph.ainvoke` → **整门课 failed**，已生成的 11 个课时白写。
                # 用户看到的是一句"预算耗尽"，而它本该是一门 partial 课程。
                key = str(lesson_plan.get("key", ""))
                log.warning("lesson_failed", key=key, error=str(exc)[:300])
                return {
                    "lessons": {},
                    "quizzes": {},
                    "failed_lessons": [key],
                    "warnings": [
                        {
                            "code": "LESSON_FAILED",
                            "message": f"课时 {key} 生成失败：{exc}",
                            "severity": "warning",
                            "node": "write_lessons",
                        }
                    ],
                }

    async def _write_all(state: dict) -> dict:
        lessons = [
            lesson
            for section in (state.get("curriculum", {}).get("sections") or [])
            for lesson in (section.get("lessons") or [])
        ]
        merged_lessons: dict[str, Any] = {}
        merged_quizzes: dict[str, Any] = {}
        failed: list[str] = []
        warnings: list[dict] = []
        semaphore = lesson_gate

        async def worker(plan: dict) -> tuple[dict, dict, list[dict], str | None]:
            async with semaphore:
                try:
                    update = await _write_one({**state, "current_lesson": plan}, plan)
                    return (
                        update.get("lessons") or {},
                        update.get("quizzes") or {},
                        [],
                        None,
                    )
                except Exception as exc:  # noqa: BLE001 - 单课时失败不阻塞整体
                    log.warning("lesson_failed", key=plan.get("key"), error=str(exc))
                    return (
                        {},
                        {},
                        [
                            {
                                "code": "LESSON_FAILED",
                                "message": f"课时 {plan.get('key')} 生成失败：{exc}",
                                "severity": "warning",
                                "node": "write_lessons",
                            }
                        ],
                        str(plan.get("key", "")),
                    )

        # `return_exceptions=True` 不是可选项：`except Exception` 接不住
        # `CancelledError` / `KeyboardInterrupt` 这类 BaseException，而 `gather`
        # 默认会把**第一个**抛出的异常直接穿透出去 —— 于是"单课时失败不阻塞整体"
        # 这句注释在某一个课时被取消时就会变成谎话，整门课跟着作废
        # （2026-11-09 实测：内核对并发的课时返回 429，整个 job 以
        #  PROVIDER_UNAVAILABLE 结束，12 个课时一个都没留下）。
        raw_results = await asyncio.gather(*(worker(p) for p in lessons), return_exceptions=True) if lessons else []
        results: list[tuple[dict, dict, list[dict], str | None]] = []
        for plan, item in zip(lessons, raw_results, strict=False):
            if isinstance(item, BaseException):
                key = str(plan.get("key", ""))
                log.warning("lesson_crashed", key=key, error=str(item)[:300])
                results.append(
                    (
                        {},
                        {},
                        [
                            {
                                "code": "LESSON_FAILED",
                                "message": f"课时 {key} 生成中断：{item}",
                                "severity": "warning",
                                "node": "write_lessons",
                            }
                        ],
                        key,
                    )
                )
            else:
                results.append(item)
        for lessons_update, quizzes_update, warns, failed_key in results:
            merged_lessons.update(lessons_update)
            merged_quizzes.update(quizzes_update)
            warnings.extend(warns)
            if failed_key:
                failed.append(failed_key)
        return {
            "lessons": merged_lessons,
            "quizzes": merged_quizzes,
            "failed_lessons": failed,
            "warnings": warnings,
        }

    async def _write_one(state: dict, plan: dict) -> dict:
        key = str(plan.get("key", ""))
        sha = str((state.get("commit") or {}).get("sha", ""))
        all_files = list_files(sha)
        # 给模型的清单只取前 40 个（prompt 预算），但**锚点校验必须看全部文件**：
        # 拿截断后的清单当真值，会把真实存在的文件判成"锚点文件不存在"
        # （2026-11-09 实测：`sherlock_project/sites.py` 排在第 40 个之后，于是
        # 所有讲它的课时都被打回，模型反复重试到轮数耗尽）。
        files = [{"path": f.get("path"), "lang": f.get("lang")} for f in all_files[:40]]
        anchors = _anchors_from_artifact(state.get("knowledge_graph") or {}, ctx)
        file_lines = {
            str(f["path"]): ctx.line_count(str(f["path"])) for f in all_files if f.get("path")
        }

        if ctx.runtime_mode == "template" or state.get("runtime") == "template":
            kg_obj = _rehydrate_kg(state, sha, ctx)
            lesson = build_template_lesson(
                lesson_plan={**plan, "layer": _layer_of(state, key)},
                kg=kg_obj,
                read=lambda p: read_file(sha, p),
            )
            artifact = ctx.save_artifact("write_lessons", f"{key}.json", lesson)
            return {
                "lessons": {
                    key: {
                        "artifact": artifact,
                        "anchors": [a for a in anchors if a.get("file") in {f["path"] for f in lesson.get("files", [])}][:10],
                        "quiz_artifact": artifact,
                        "warnings": [],
                    }
                },
                "quizzes": {key: lesson.get("quiz") or []},
            }

        async def run(system: str, prompt: str) -> tuple[str, dict]:
            return await ctx.run(
                "writer",
                system,
                prompt,
                node="write_lessons",
                schema="lesson",
                lesson_key=key,
                per_lesson=True,
                # 只给"看结构"的工具：通读文件会把上下文和 token 一起放大，
                # 而锚点（N4 产出、N7 复核）已经带了精确行区间。
                tools=WRITER_AGENT_TOOLS,
            )

        outcome = await produce_validated(
            run=run,
            system=writer_system(),
            prompt=writer_prompt({**plan, "layer": _layer_of(state, key)}, files, anchors, None),
            schema_name="lesson",
            extra_checks=lambda data: (
                check_segments(data.get("steps") or [])
                + check_quiz(data.get("quiz") or [])
                + check_lesson_anchors(data, file_lines)
            ),
        )
        if not outcome.ok:
            raise AppError("CONTRACT_VIOLATION", f"课时 {key} 产出不合契约：{'; '.join(outcome.errors[:3])}")
        lesson = dict(outcome.data)
        lesson.setdefault("layer", _layer_of(state, key))
        artifact = ctx.save_artifact("write_lessons", f"{key}.json", lesson)
        return {
            "lessons": {
                key: {
                    "artifact": artifact,
                    "anchors": [a for a in (lesson.get("quiz") or [{}])[0].get("evidence", []) if isinstance(a, dict)][:10]
                    or anchors[:5],
                    "quiz_artifact": artifact,
                    "warnings": [],
                    "usage": outcome.usage,
                }
            },
            "quizzes": {key: lesson.get("quiz") or []},
        }

    # ---- N7 ---------------------------------------------------------------
    async def simulate_trace(state: dict) -> dict:
        await _emit("simulate_trace")
        traces: dict[str, Any] = {}
        warnings: list[dict] = []
        sha = str((state.get("commit") or {}).get("sha", ""))
        chains = _chains_from_artifact(state.get("knowledge_graph") or {}, ctx)
        chain = chains[0] if chains else {}

        for key in (state.get("lessons") or {}):
            lesson_ref = (state.get("lessons") or {}).get(key) or {}
            if state.get("runtime") == "template" or ctx.runtime_mode == "template":
                trace = template_trace(chain, key)
            else:
                async def run(system: str, prompt: str, _key: str = key) -> tuple[str, dict]:
                    return await ctx.run(
                        "critic", system, prompt, node="simulate_trace", schema="trace", lesson_key=_key, per_lesson=True
                    )

                # 预算是**跨节点共享**的：课时写完之后，轨迹阶段可能只剩 1k 额度。
                # 真实故障（2026-11-09，job job_01M6ZFHM3PJJ1NSDNMR1AT61MN）：12 个课时
                # 全部写成功，轨迹阶段 `tokens used=4297 limit=1000` 抛 BUDGET_EXCEEDED，
                # 整门课被判 failed_budget —— 已经写好的 12 个课时一个都没发布。
                # 轨迹本来就是"可降级项"（模型推演 vs 静态调用链），所以预算耗尽必须和
                # "结构契约不通过"走同一个出口：用静态轨迹 + 一条警告，课程照常发布。
                try:
                    outcome = await produce_validated(
                        run=run,
                        system=critic_system(),
                        prompt=critic_prompt(chain, {"key": key, "ref": lesson_ref}, lesson_ref.get("anchors") or []),
                        schema_name="trace",
                    )
                except AppError as exc:
                    if exc.code != "BUDGET_EXCEEDED":
                        raise
                    log.warning("trace_budget_fallback", lesson_key=key, error=exc.message[:200])
                    trace = template_trace(chain, key)
                    warnings.append(
                        {
                            "code": "TRACE_FALLBACK",
                            "message": f"课时 {key} 的轨迹因预算耗尽改用静态调用链（内容仍可学）",
                            "severity": "warning",
                            "node": "simulate_trace",
                        }
                    )
                else:
                    trace = outcome.data if outcome.ok else template_trace(chain, key)
                    if not outcome.ok:
                        warnings.append(
                            {
                                "code": "TRACE_FALLBACK",
                                "message": f"课时 {key} 的轨迹生成失败，已用静态调用链替代",
                                "severity": "warning",
                                "node": "simulate_trace",
                            }
                        )
            guarded = guard_trace(trace, lambda p: mirror_line_count(sha, p), lesson_key=key)
            warnings.extend(guarded.warnings)
            payload = {"key": guarded.summary and trace.get("key") or f"trace_{key}", "steps": guarded.steps}
            artifact = ctx.save_artifact("simulate_trace", f"{key}.json", payload)
            traces[key] = {"artifact": artifact, "summary": guarded.summary}
        return {"traces": traces, "warnings": warnings}

    # ---- N8 ---------------------------------------------------------------
    async def synthesize_audio(state: dict) -> dict:
        await _emit("synthesize_audio")
        narration: dict[str, Any] = {}
        warnings: list[dict] = []
        for key in (state.get("lessons") or {}):
            lesson = _load_artifact((state.get("lessons") or {}).get(key) or {}, ctx)
            steps: dict[str, Any] = {}
            segment_count = 0
            voiced = 0
            for step in lesson.get("steps") or []:
                segments = [seg for seg in (step.get("segments") or []) if isinstance(seg, dict)]
                segment_count += len(segments)
                index = str(step.get("index", len(steps)))
                audio = None
                timing_source = "estimated"
                if segments:
                    try:
                        audio, timing_source = await ctx.synthesize(key, segments)
                    except Exception as exc:  # noqa: BLE001 - 合成失败降级为字幕
                        warnings.append(
                            {
                                "code": "TTS_DEGRADED",
                                "message": f"课时 {key} 第 {index} 步的配音合成失败，已切换为字幕推进：{exc}",
                                "severity": "info",
                                "node": "synthesize_audio",
                            }
                        )
                if audio:
                    voiced += 1
                # 每步一条音轨：播放器按 step 切换音源，共用一条整课音轨会让
                # "切到下一步"把音频拨回开头，字幕与声音立刻错位（spec §7.3）。
                steps[index] = {"audio": audio, "timing_source": timing_source, "segment_count": len(segments)}
            narration[key] = {
                "segment_count": segment_count,
                "timing_source": "tts" if voiced else "estimated",
                "voiced_steps": voiced,
                "steps": steps,
            }
        return {"narration": narration, "warnings": warnings}

    # ---- N9 ---------------------------------------------------------------
    async def publish_course(state: dict) -> dict:
        await _emit("publish_course", 100)

        result = await ctx.publish(state)
        return result

    return {
        "normalize_repo": normalize_repo,
        "resolve_commit": resolve_commit,
        "fetch_repo": fetch_repo,
        "analyze_repo": analyze_repo,
        "plan_curriculum": plan_curriculum,
        "write_lessons": write_lessons,
        "simulate_trace": simulate_trace,
        "synthesize_audio": synthesize_audio,
        "publish_course": publish_course,
    }


# --------------------------------------------------------------------------- #
# 小工具                                                                       #
# --------------------------------------------------------------------------- #


def _layer_of(state: dict, lesson_key: str) -> str:
    for section in (state.get("curriculum", {}).get("sections") or []):
        for lesson in (section.get("lessons") or []):
            if str(lesson.get("key")) == str(lesson_key):
                return str(section.get("key", "overview"))
    return "overview"


def _anchors_from_artifact(kg_summary: dict, ctx: Any) -> list[dict]:
    artifact = kg_summary.get("artifact")
    if not artifact:
        return []
    try:
        payload = ctx.load_artifact(artifact)
    except Exception:  # noqa: BLE001
        return []
    return payload.get("anchors") or []


def _chains_from_artifact(kg_summary: dict, ctx: Any) -> list[dict]:
    artifact = kg_summary.get("artifact")
    if not artifact:
        return []
    try:
        payload = ctx.load_artifact(artifact)
    except Exception:  # noqa: BLE001
        return []
    return payload.get("chains") or []


def _load_artifact(ref: dict, ctx: Any) -> dict:
    artifact = ref.get("artifact") or ref.get("quiz_artifact")
    if not artifact:
        return {}
    try:
        return ctx.load_artifact(artifact)
    except Exception:  # noqa: BLE001
        return {}


def _rehydrate_kg(state: dict, sha: str, ctx: Any = None):
    """把 state 里的 KG 摘要 + artifact 还原成可用的 `KnowledgeGraph`。

    模板降级需要**真实符号**做串讲与出题，而 state 里只有摘要——所以这条路必须读
    artifact 里的锚点候选，把它们还原成 `Symbol`（含被引用次数）。
    早期版本只还原了 modules，结果模板课时"没有符号可讲"，连带**一道题都出不来**；
    而题目是完课页与能力雷达的数据来源，缺了它整个学习闭环就断了。
    读不到 artifact 时返回"只有模块"的空图，**不抛错**：模板路径不允许中断。
    """
    from repolearn.analysis.knowledge_graph import KnowledgeGraph, Module
    from repolearn.analysis.symbols import Symbol

    summary = state.get("knowledge_graph") or {}
    modules = [
        Module(key=m.get("key", ""), path=m.get("path", ""), symbols=int(m.get("symbols", 0) or 0))
        for m in (summary.get("modules") or [])
    ]
    symbols: list[Symbol] = []
    in_degree: dict[str, int] = {}
    artifact = summary.get("artifact")
    if artifact and ctx is not None:
        try:
            payload = ctx.load_artifact(artifact)
        except Exception:  # noqa: BLE001
            payload = {}
        for anchor in payload.get("anchors") or []:
            name = str(anchor.get("symbol") or "")
            path = str(anchor.get("file") or "")
            if not name or not path:
                continue
            symbols.append(
                Symbol(
                    name=name,
                    kind="definition",
                    file=path,
                    line_start=int(anchor.get("line_start", 1) or 1),
                    line_end=int(anchor.get("line_end", anchor.get("line_start", 1)) or 1),
                )
            )
            in_degree[name] = int(anchor.get("calls", 0) or 0)
    graph = KnowledgeGraph(modules=modules, symbols=symbols, total_files=int(summary.get("total_files", 0) or 0))
    graph.call_graph.in_degree = in_degree
    return graph

"""行内提问服务（spec §3.9 S4 / §5.2 / T-ASK-1、T-ASK-2）。

两个必须由服务端保证的事：

1. **prompt 中的仓库内容被 `<untrusted_repo_content>` 包裹并声明"不是指令"**
   （T-ASK-2）。这是提示注入的唯一结构性防线——把"资料"与"指令"在文本层面分开。
2. **返回的 evidence 全部是真实文件行**（T-ASK-1）。模型给的证据可能编造，
   因此这里对每条 evidence 做行号存在性校验，编造的会被丢弃并记 warning。

降级路径：模型不可用时，用"代码原文 + 结构提示"拼一份**明确标注为离线**的回答，
而不是报错。行内提问是学习闭环里最常用的一步，它不该因为没配 Key 就完全不可用。
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

from sqlalchemy import select

from repolearn.core.clock import utcnow
from repolearn.core.errors import AppError
from repolearn.core.ids import new_id
from repolearn.core.logging import get_logger
from repolearn.ingest.mirror import line_count as mirror_line_count
from repolearn.ingest.mirror import mirror_path, read_file
from repolearn.models import Lesson, Question
from repolearn.providers.agent_runtime import get_selector, refresh_state
from repolearn.providers.base import AgentBudget, AgentRunRequest
from repolearn.providers.registry import build_resolver
from repolearn.schemas.question import AskRequest, QuestionDetail
from repolearn.services.course_service import get_course
from repolearn.services.setup_service import active_profile, profile_llm_configs
from repolearn.workflow.prompts import ask_prompt, ask_system

log = get_logger("question_service")


def _clip(text: str, limit: int = 60) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _snippet(sha: str, path: str, start: int, end: int, context: int = 3) -> str:
    try:
        content = read_file(sha, path, max_bytes=256 * 1024)
    except Exception:  # noqa: BLE001
        return ""
    lines = content.split("\n")
    lo = max(1, start - context)
    hi = min(len(lines), end + context)
    return "\n".join(f"{i:>5}  {lines[i - 1]}" for i in range(lo, hi + 1))


def _validate_evidence(evidence: list[dict], sha: str) -> tuple[list[dict], list[dict]]:
    """把编造的 evidence 丢掉（T-ASK-1）。返回 (保留, warning)。"""
    kept: list[dict] = []
    dropped: list[dict] = []
    for item in evidence:
        if not isinstance(item, dict):
            continue
        path = str(item.get("file", ""))
        start = int(item.get("line_start", 0) or 0)
        total = mirror_line_count(sha, path)
        if not path or total <= 0 or start < 1 or start > total:
            dropped.append(item)
            continue
        kept.append(
            {
                "file": path,
                "line_start": start,
                "line_end": min(int(item.get("line_end", start) or start), total),
                "quote": _clip(str(item.get("quote", "") or ""), 200),
            }
        )
    warnings: list[dict] = []
    if dropped:
        warnings.append(
            {
                "code": "EVIDENCE_DROPPED",
                "message": f"丢弃了 {len(dropped)} 条无法在镜像中定位的证据",
                "severity": "info",
                "node": "questions",
            }
        )
    return kept, warnings


def offline_answer(req: AskRequest, snippet: str) -> str:
    """离线回答：**明确标注为"未启用 AI"**，只呈现代码事实，不编讲解。"""
    return (
        "> ⚠️ 当前未启用 AI 服务，以下是对所选代码的**静态呈现**，不包含推断性讲解。\n\n"
        f"### 你选中的代码（`{req.file}` 第 {req.line_start}–{req.line_end} 行）\n\n"
        f"```\n{snippet or '（无法读取该文件，请确认它在本课程的镜像内）'}\n```\n\n"
        "### 你的问题\n\n"
        f"{req.question}\n\n"
        "### 下一步\n\n"
        "- 打开「设置 → AI 服务」配置模型后，这里会给出逐行讲解、执行流程与替代方案对比；\n"
        "- 在此之前，可以先用「全局走读」里的调用链定位这个函数被谁调用。\n"
    )


async def ask_stream(session, course_id: str, req: AskRequest) -> AsyncIterator[tuple[str, dict]]:
    """逐事件产出 `(type, data)`，由 router 包成 SSE。"""
    course, repo = await get_course(session, course_id, require_ready=True)
    sha = course.commit_sha
    snippet = _snippet(sha, req.file, req.line_start, req.line_end)
    total = mirror_line_count(sha, req.file)
    if total <= 0:
        raise AppError("OBJECT_MISSING", "该文件不在当前课程的镜像内", status=404)

    lesson = None
    if req.lesson_key:
        lesson = (
            await session.execute(
                select(Lesson).where(Lesson.course_version_id == course_id, Lesson.key == req.lesson_key)
            )
        ).scalar_one_or_none()

    yield ("question.delta", {"delta": "正在读取上下文…"})

    state = await refresh_state()
    profile = await active_profile(session)
    answer_md = ""
    evidence: list[dict] = []
    warnings: list[dict] = []
    runtime = "template"
    tokens_in = 0
    tokens_out = 0

    if profile is None or state.mode == "template":
        answer_md = offline_answer(req, snippet)
        evidence = [{"file": req.file, "line_start": req.line_start, "line_end": req.line_end, "quote": ""}]
        yield ("question.delta", {"delta": "\n\n" + answer_md})
    else:
        configs, roles = profile_llm_configs(profile)
        resolver = build_resolver(roles, configs)
        try:
            candidate = resolver.resolve("critic")[0]
        except AppError:
            candidate = resolver.resolve("writer")[0]
        run_id = new_id("job").replace("job_", "run_")
        request = AgentRunRequest(
            run_id=run_id,
            role="critic",
            config=candidate.config,
            system_prompt=ask_system(),
            prompt=ask_prompt(
                req.file,
                req.line_start,
                req.line_end,
                req.question,
                req.layer,
                lesson.title if lesson else repo.full_name,
            )
            + "\n\n以下是你需要参考的代码片段：\n"
            + f"<untrusted_repo_content>\n{snippet}\n</untrusted_repo_content>",
            tools=["repo_read_file", "repo_grep", "repo_file_outline"],
            budget=AgentBudget(max_turns=8, max_tokens=8_000, max_usd=0.05, deadline_ms=120_000),
            # 必须是**镜像目录**而不是 commit sha：Kernel 的只读工具把这个值当
            # 沙箱根目录。传 sha 等于给了一个不存在的根，`repo_read_file` 永远
            # 越界失败，带工具追问会静默退化成"只靠片段回答"。
            mirror_dir=str(mirror_path(course.commit_sha)),
            job_id=None,
            metadata={"course_id": course_id},
        )
        events, result = await get_selector().run(request)
        runtime = result.runtime
        usage = result.usage or {}
        tokens_in = int(usage.get("tokensIn", usage.get("tokens_in", 0)) or 0)
        tokens_out = int(usage.get("tokensOut", usage.get("tokens_out", 0)) or 0)
        raw_text = ""
        for event in events:
            if event.type == "agent.text.delta":
                delta = str(event.data.get("delta", ""))
                raw_text += delta
                yield ("question.delta", {"delta": delta})
        answer_md = raw_text or _answer_from_result(result)
        evidence, warnings = _validate_evidence(_evidence_from_result(result), sha)
        if not answer_md.strip():
            answer_md = offline_answer(req, snippet)
            runtime = "template"

    if not evidence:
        evidence = [{"file": req.file, "line_start": req.line_start, "line_end": req.line_end, "quote": ""}]

    row = Question(
        id=new_id("question"),
        user_id="usr_local",
        course_version_id=course_id,
        lesson_id=lesson.id if lesson else None,
        file=req.file,
        line_start=req.line_start,
        line_end=req.line_end,
        layer=req.layer,
        question=req.question,
        answer_md=answer_md,
        evidence=evidence,
        runtime=runtime,
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        created_at=utcnow(),
    )
    session.add(row)
    await session.flush()

    yield (
        "question.completed",
        {
            "id": row.id,
            "answer_md": answer_md,
            "evidence": evidence,
            "tokens": {"in": tokens_in, "out": tokens_out},
            "runtime": runtime,
            "warnings": warnings,
        },
    )


def _answer_from_result(result: Any) -> str:
    payload = result.result or {}
    for key in ("answer_md", "answer", "text"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value
    if payload.get("raw"):
        try:
            return json.dumps(payload["raw"], ensure_ascii=False)[:8000]
        except (TypeError, ValueError):
            return ""
    return ""


def _evidence_from_result(result: Any) -> list[dict]:
    payload = result.result or {}
    raw = payload.get("evidence")
    return [e for e in raw if isinstance(e, dict)] if isinstance(raw, list) else []


async def list_questions(session, course_id: str, lesson_key: str | None = None) -> list[QuestionDetail]:
    await get_course(session, course_id)
    stmt = select(Question).where(
        Question.course_version_id == course_id, Question.deleted_at.is_(None)
    )
    if lesson_key:
        lesson = (
            await session.execute(
                select(Lesson).where(Lesson.course_version_id == course_id, Lesson.key == lesson_key)
            )
        ).scalar_one_or_none()
        if lesson is not None:
            stmt = stmt.where(Question.lesson_id == lesson.id)
    rows = (await session.execute(stmt.order_by(Question.created_at.desc()).limit(100))).scalars().all()
    return [
        QuestionDetail(
            id=row.id,
            lesson_id=row.lesson_id,
            file=row.file,
            line_start=row.line_start,
            line_end=row.line_end,
            layer=row.layer,
            question=row.question,
            answer_md=row.answer_md,
            evidence=list(row.evidence or []),
            runtime=row.runtime,
            created_at=row.created_at.isoformat() if row.created_at else None,
        )
        for row in rows
    ]

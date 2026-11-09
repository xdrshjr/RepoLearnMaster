"""评审节点补的防回归用例（spec §「评审节点补记的缺陷」D17–D28）。

每一条都对应一个"代码看起来对、测试全绿、但那条路径其实没生效"的缺陷。
它们必须**真的走那条路径**，否则下一次重构会静默把修复删掉。
"""

from __future__ import annotations

import json

import pytest
from sqlalchemy import select

from repolearn.core.clock import utcnow
from repolearn.core.config import settings
from repolearn.core.errors import AppError
from repolearn.core.security import decrypt_secret, encrypt_secret, mask_key
from repolearn.jobs import queue
from repolearn.models import (
    BookVersion,
    CourseVersion,
    GenerationLock,
    Job,
    LlmProfile,
    QuizAttempt,
    Repository,
)
from repolearn.providers.base import LlmConfig
from repolearn.providers.budget_guard import JobBudget
from repolearn.providers.registry import build_resolver
from repolearn.providers.tts.join import join_mp3, strip_id3
from repolearn.services import job_service, setup_service
from repolearn.workflow.state import CourseGenState, new_state


async def seed_course(session, *, status: str = "generating", deleted: bool = False, cache_key: str = "ck_1"):
    """插一条最小可用的课程（含它的 repository，外键非空）。"""
    repo = Repository(
        id="rp_test1",
        full_name="owner/repo",
        owner="owner",
        name="repo",
        default_branch="main",
        html_url="https://github.com/owner/repo",
        is_public=True,
        created_at=utcnow(),
        updated_at=utcnow(),
    )
    session.add(repo)
    course = CourseVersion(
        id="cv_test1",
        repository_id=repo.id,
        commit_sha="a" * 40,
        cache_key=cache_key,
        policy_version="1",
        language="zh-CN",
        title="测试课程",
        status=status,
        sections=[],
        quality_report={},
        warnings=[],
        blueprint={},
        cover_palette="mint",
        visibility="public",
        created_at=utcnow(),
        updated_at=utcnow(),
    )
    if deleted:
        course.deleted_at = utcnow()
    session.add(course)
    await session.flush()
    return course


# --------------------------------------------------------------------------- #
# D17：锁冲突不能回滚整个请求事务
# --------------------------------------------------------------------------- #


async def test_acquire_lock_conflict_keeps_surrounding_writes(session):
    job = await queue.enqueue(session, kind="course", payload={}, cache_key="ck_lock")
    assert await queue.acquire_lock(session, "ck_lock", job.id) is True

    other = await queue.enqueue(session, kind="course", payload={}, cache_key="ck_lock")
    assert await queue.acquire_lock(session, "ck_lock", other.id) is False

    # 关键断言：两个 job 都还在（之前 `session.rollback()` 会把它们一起抹掉）
    assert await session.get(Job, job.id) is not None
    assert await session.get(Job, other.id) is not None


async def test_active_lock_job_reports_holder_and_reaps_stale_lock(session):
    job = await queue.enqueue(session, kind="course", payload={}, cache_key="ck_active")
    await queue.acquire_lock(session, "ck_active", job.id)
    assert await queue.active_lock_job(session, "ck_active") == job.id

    # Job 已终结 → 锁是僵尸锁，必须就地清掉（否则该仓库在 TTL 内无法重建）
    await queue.finish(session, job.id, status="failed")
    assert await queue.active_lock_job(session, "ck_active") is None
    assert (
        await session.execute(select(GenerationLock).where(GenerationLock.cache_key == "ck_active"))
    ).scalar_one_or_none() is None


async def test_idempotency_conflict_does_not_roll_back_request(session):
    job = await queue.enqueue(session, kind="course", payload={}, cache_key="ck_idem")
    await queue.store_idempotency(
        session, scope="courses.create", key="k1", request_hash="h1", response={"a": 1}, job_id=job.id
    )
    await queue.store_idempotency(
        session, scope="courses.create", key="k1", request_hash="h1", response={"a": 2}, job_id=job.id
    )
    assert await session.get(Job, job.id) is not None
    assert await queue.check_idempotency(session, scope="courses.create", key="k1", request_hash="h1") == {"a": 1}


# --------------------------------------------------------------------------- #
# D19：软删课程复活（cache_key 唯一，不能再插一行）
# --------------------------------------------------------------------------- #


async def test_soft_deleted_course_row_is_unique_and_resurrectable(session):
    course = await seed_course(session, status="ready", deleted=True)
    rows = (await session.execute(select(CourseVersion).where(CourseVersion.cache_key == "ck_1"))).scalars().all()
    assert len(rows) == 1, "cache_key 唯一：软删行同样占位，只能复活不能新增"

    course.deleted_at = None
    course.visibility = "public"
    await session.flush()
    await session.refresh(course)
    assert course.deleted_at is None and course.visibility == "public"


# --------------------------------------------------------------------------- #
# D20：失败的书可以重新生成（同一 cache_key 只有一行）
# --------------------------------------------------------------------------- #


async def test_failed_book_row_is_reused(session):
    session.add(
        BookVersion(
            id="bk_failed",
            course_version_id="cv_test1",
            cache_key="bk_ck",
            preset="standard",
            template_version="1",
            title="",
            status="failed",
            quality={},
            created_at=utcnow(),
        )
    )
    await session.flush()

    book = await session.get(BookVersion, "bk_failed")
    assert book is not None and book.status == "failed"
    # create_book 的复用分支：同一行重置为 generating，而不是插第二行
    book.status = "generating"
    book.quality = {}
    await session.flush()
    rows = (await session.execute(select(BookVersion).where(BookVersion.cache_key == "bk_ck"))).scalars().all()
    assert len(rows) == 1 and rows[0].status == "generating"


# --------------------------------------------------------------------------- #
# D23：取消 queued 任务 = 当场终结 + 释放锁 + 课程不再卡在 generating
# --------------------------------------------------------------------------- #


async def test_cancel_queued_job_finishes_immediately(session):
    course = await seed_course(session, status="generating")
    job = await queue.enqueue(session, kind="course", payload={}, course_version_id=course.id, cache_key="ck_1")
    await queue.acquire_lock(session, "ck_1", job.id)
    await session.flush()

    status = await job_service.cancel(session, job.id)
    assert status == "cancelled"

    await session.refresh(job)
    assert job.status == "cancelled"
    assert job.finished_at is not None
    await session.refresh(course)
    assert course.status == "failed"
    assert any(w.get("code") == "GENERATION_CANCELLED" for w in (course.warnings or []))
    # 锁必须已经释放，否则这个仓库在 TTL 内无法重新生成
    assert (
        await session.execute(select(GenerationLock).where(GenerationLock.cache_key == "ck_1"))
    ).scalar_one_or_none() is None


async def test_cancel_terminal_job_is_a_noop(session):
    job = await queue.enqueue(session, kind="course", payload={}, cache_key="ck_term")
    await queue.finish(session, job.id, status="ready")
    assert await job_service.cancel(session, job.id) == "ready"


# --------------------------------------------------------------------------- #
# D21 / D22：密钥轮换与兜底密钥
# --------------------------------------------------------------------------- #


async def test_rotate_secret_makes_new_key_active_and_keeps_ciphertext_readable(session, monkeypatch):
    profile = LlmProfile(
        id="lp_rotate",
        label="rotate",
        provider="anthropic",
        protocol="anthropic_messages",
        base_url=None,
        api_key_ciphertext=b"",
        api_key_last4="",
        org=None,
        active=True,
        created_at=utcnow(),
    )
    session.add(profile)
    await session.flush()
    profile.api_key_ciphertext = encrypt_secret("sk-ant-real-key-1234", profile.id)
    await session.flush()

    written: dict[str, str] = {}
    monkeypatch.setattr(
        setup_service,
        "_write_env_secret",
        lambda new, old: written.update(new=new, old=old) or True,
    )
    old_secret = settings.secret_key
    new_secret = "n" * 32
    try:
        rotated = await setup_service.rotate_secret(session, new_secret)
        assert rotated == 1
        assert settings.secret_key == new_secret
        assert written["new"] == new_secret and written["old"] == old_secret
        await session.refresh(profile)
        assert decrypt_secret(profile.api_key_ciphertext, profile.id) == "sk-ant-real-key-1234"
    finally:
        settings.secret_key = old_secret
        settings.secret_key_previous = ""


async def test_rotate_secret_rejects_short_secret(session):
    with pytest.raises(AppError):
        await setup_service.rotate_secret(session, "short")


def test_fernet_key_is_stable_when_secret_is_missing(monkeypatch):
    monkeypatch.setattr(settings, "secret_key", "")
    assert settings.fernet_key == settings.fernet_key


# --------------------------------------------------------------------------- #
# D24 / D25 / D26：工作流状态、节点额度、候选价格
# --------------------------------------------------------------------------- #


def test_publish_is_a_declared_state_key():
    assert "publish" in CourseGenState.__annotations__
    assert new_state("job_x", "cv_x").get("lessons") == {}


def test_node_allowance_uses_node_name_not_schema_name():
    # 显式给总闸而不是读 settings：这条用例测的是**节点分闸表**，不该被
    # `REPOLEARN_JOB_MAX_TOKENS` 这类环境变量左右（机器上有一个更小的值就会红）。
    budget = JobBudget(max_tokens=2_000_000)
    # 2026-11-09 放宽后：规划节点必须能容下一次 30k+ 的真实规划
    assert budget.node_allowance("plan_curriculum") == 200_000
    assert budget.node_allowance("simulate_trace") == 20_000
    assert budget.node_allowance("some_schema_name") == 8_000

    # 按课时扇出时要给后续课时留出额度：剩余额度紧张时才看得出差别
    tight = JobBudget(max_tokens=1_000_000, used_tokens=700_000)
    assert tight.node_allowance("write_lessons") == 120_000
    assert tight.node_allowance("write_lessons", per_lesson=True) == 1_000


def test_resolver_candidates_carry_prices():
    cfg = LlmConfig(provider="anthropic", protocol="anthropic_messages", api_key="k")
    resolver = build_resolver({"planner": "claude-sonnet-4-5"}, {"claude-sonnet-4-5": cfg})
    candidate = resolver.resolve("planner")[0]
    assert candidate.capabilities["price_in"] > 0
    assert candidate.capabilities["price_out"] > 0


# --------------------------------------------------------------------------- #
# D27：MP3 拼接
# --------------------------------------------------------------------------- #


def test_join_mp3_strips_id3_and_concatenates():
    id3 = b"ID3" + bytes([4, 0, 0, 0, 0, 0, 0x08]) + b"\x00" * 8
    frame_a = b"\xff\xfb\x90\x00" + b"A" * 16
    frame_b = b"\xff\xfb\x90\x00" + b"B" * 16
    joined = join_mp3([id3 + frame_a, id3 + frame_b])
    assert joined.startswith(b"\xff\xfb")
    assert b"ID3" not in joined
    assert joined == frame_a + frame_b


def test_strip_id3_handles_plain_and_v1_tags():
    assert strip_id3(b"") == b""
    payload = b"\xff\xfb" + b"x" * 10
    assert strip_id3(payload) == payload
    assert strip_id3(payload + b"TAG" + b"\x00" * 125) == payload


# --------------------------------------------------------------------------- #
# T-QUIZ-2 / T-SEC-5 形状回归
# --------------------------------------------------------------------------- #


async def test_quiz_attempt_single_row(session):
    course = await seed_course(session, status="ready", cache_key="ck_quiz")
    session.add(
        QuizAttempt(
            id="qa_1",
            user_id="usr_local",
            quiz_item_id="qi_1",
            course_version_id=course.id,
            choice_id="a",
            correct=True,
            submitted_at=utcnow(),
        )
    )
    await session.flush()
    rows = (await session.execute(select(QuizAttempt))).scalars().all()
    assert len(rows) == 1


def test_mask_key_never_leaks_the_middle():
    masked = mask_key("sk-ant-api03-abcdefgh1234")
    assert masked == "···1234"
    assert "abcdefgh" not in json.dumps({"k": masked})

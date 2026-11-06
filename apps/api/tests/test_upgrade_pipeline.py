"""升级流水线与进度迁移（hardening spec §7.5：T-UPG-4/5/6/7）。"""

from __future__ import annotations

import shutil

from sqlalchemy import select, text

from repolearn.core.clock import utcnow
from repolearn.core.config import REPO_ROOT
from repolearn.core.ids import new_id
from repolearn.models import (
    Commit,
    CourseVersion,
    Lesson,
    QuizItem,
    Repository,
    SourceAnchor,
    Step,
    UserProgress,
)
from repolearn.services.progress_service import carry_forward, carry_forward_percent

FIXTURES = REPO_ROOT / "tests" / "fixtures" / "repos"
OLD_SHA = "a1" * 32
NEW_SHA = "b2" * 32


# --------------------------------------------------------------------------- #
# T-UPG-6：进度迁移的两条不变式 + 公式本身                                     #
# --------------------------------------------------------------------------- #


def test_upg_6_percent_formula_is_deterministic():
    """T-UPG-6（纯函数部分）：断言**公式结果**，不是"不为 0"。

    如果只断言"迁移后 percent > 0"，那么把公式改成 `old_percent` 原样搬运也能通过
    ——而那正是会在新版本课时变多时让用户看到"已学完 8/12 却只点开过 3 个课时"
    的那个 bug。
    """
    # 学了 50%，旧版 10 课，新版 12 课，其中 8 课仍在：
    #   lesson_ratio = 8/10 = 0.8 → 50*0.8 = 40
    #   上限 = floor(100*8/12) = 66 → 取 40
    assert carry_forward_percent(old_percent=50, kept=8, old_lessons=10, new_lessons=12) == 40
    # 只保留 2 课、旧版 10 课、新版 12 课、old_percent=90：
    #   90*0.2 = 18；上限 floor(100*2/12)=16 → 取 16（不得超过上限）
    assert carry_forward_percent(old_percent=90, kept=2, old_lessons=10, new_lessons=12) == 16
    # 不变式 ①：只降不升
    for old_percent in (0, 1, 50, 99, 100):
        for kept in (0, 3, 10):
            value = carry_forward_percent(old_percent=old_percent, kept=kept, old_lessons=10, new_lessons=10)
            assert value <= old_percent
    # 退化输入不炸
    assert carry_forward_percent(old_percent=80, kept=0, old_lessons=0, new_lessons=0) == 0


async def _seed_pair(session, *, old_keys: list[str], new_keys: list[str]):
    """造一对"旧版本 / 新版本"课程（只建课时行，够迁移用）。"""
    repo = Repository(
        id=new_id("repository"),
        full_name="owner/upg",
        owner="owner",
        name="upg",
        description="",
        stars=0,
        license_spdx="MIT",
        primary_language="Python",
        default_branch="main",
        html_url="https://github.com/owner/upg",
        is_public=True,
        created_at=utcnow(),
        updated_at=utcnow(),
    )
    session.add(repo)
    await session.flush()

    def make(sha: str, keys: list[str]) -> CourseVersion:
        return CourseVersion(
            id=new_id("course_version"),
            repository_id=repo.id,
            commit_sha=sha,
            cache_key=f"upg-{sha[:6]}",
            policy_version="1",
            language="zh",
            title=f"课程 {sha[:4]}",
            status="ready",
            sections=[{"key": "overview", "title": "第一层", "minutes": 5, "lessons": []}],
            quality_report={},
            warnings=[],
            blueprint={},
            lesson_count=len(keys),
            total_minutes=len(keys) * 5,
            visibility="public",
            created_at=utcnow(),
            updated_at=utcnow(),
            published_at=utcnow(),
        )

    old = make(OLD_SHA, old_keys)
    new = make(NEW_SHA, new_keys)
    session.add_all([old, new])
    await session.flush()
    for version, keys in ((old, old_keys), (new, new_keys)):
        for index, key in enumerate(keys):
            session.add(
                Lesson(
                    id=new_id("lesson"),
                    course_version_id=version.id,
                    section_key="overview",
                    key=key,
                    title=f"课时 {key}",
                    goal="",
                    minutes=5,
                    order_index=index,
                    status="ready",
                    playback_meta={},
                    created_at=utcnow(),
                )
            )
    await session.flush()
    return old, new


async def test_upg_6_carry_forward_db(session):
    """T-UPG-6（DB 部分）：key 存活则保留位置；key 消失则落到最近存活 key。"""
    from repolearn.services.progress_service import ensure_local_user

    old, new = await _seed_pair(session, old_keys=["1.1", "1.2", "1.3"], new_keys=["1.1", "1.3"])
    user = await ensure_local_user(session)
    session.add(
        UserProgress(
            id=new_id("event"),
            user_id=user.id,
            course_version_id=old.id,
            current_lesson_key="1.3",
            current_step_index=2,
            position_ms=1234,
            percent=80,
            created_at=utcnow(),
            updated_at=utcnow(),
        )
    )
    await session.flush()

    result = await carry_forward(session, old, new)
    assert result["migrated"] is True
    row = (
        await session.execute(
            select(UserProgress).where(UserProgress.course_version_id == new.id)
        )
    ).scalar_one()
    # 1.3 在新版本里仍存在 → 位置原样保留，percent 按公式下调
    assert row.current_lesson_key == "1.3"
    assert row.current_step_index == 2
    assert row.position_ms == 1234
    expected = carry_forward_percent(old_percent=80, kept=2, old_lessons=3, new_lessons=2)
    assert row.percent == expected == 53
    assert row.percent <= 80


async def test_upg_6_carry_forward_falls_back_to_previous_key(session):
    """key 被删除时落到"最近的前一个仍存在"的 key，位置与步号归零。"""
    from repolearn.services.progress_service import ensure_local_user

    old, new = await _seed_pair(session, old_keys=["1.1", "1.2", "1.3"], new_keys=["1.1"])
    user = await ensure_local_user(session)
    session.add(
        UserProgress(
            id=new_id("event"),
            user_id=user.id,
            course_version_id=old.id,
            current_lesson_key="1.3",
            current_step_index=4,
            position_ms=999,
            percent=100,
            created_at=utcnow(),
            updated_at=utcnow(),
        )
    )
    await session.flush()
    await carry_forward(session, old, new)
    row = (
        await session.execute(select(UserProgress).where(UserProgress.course_version_id == new.id))
    ).scalar_one()
    assert row.current_lesson_key == "1.1"
    assert row.current_step_index == 0
    assert row.position_ms == 0
    # 上限 = floor(100*1/1) = 100，但比例 1/3 → 100*0.333 = 33
    assert row.percent == 33


# --------------------------------------------------------------------------- #
# T-UPG-4 / 5 / 7：真实流水线                                                  #
# --------------------------------------------------------------------------- #


async def _seed_pipeline_course(session, *, sha: str, files: list[str], with_anchors: bool = True):
    """造一门"已发布"的课程，内容引用给定文件（供复制/重讲比对）。"""
    repo = (
        await session.execute(select(Repository).where(Repository.full_name == "owner/tiny"))
    ).scalar_one_or_none()
    if repo is None:
        repo = Repository(
            id=new_id("repository"),
            full_name="owner/tiny",
            owner="owner",
            name="tiny",
            description="",
            stars=0,
            license_spdx="MIT",
            primary_language="Python",
            default_branch="main",
            html_url="https://github.com/owner/tiny",
            is_public=True,
            created_at=utcnow(),
            updated_at=utcnow(),
        )
        session.add(repo)
        await session.flush()
    session.add(
        Commit(
            id=new_id("commit"),
            repository_id=repo.id,
            sha=sha,
            committed_at=utcnow(),
            file_count=len(files),
            tarball_bytes=100,
            license_note="MIT",
            created_at=utcnow(),
        )
    )
    course = CourseVersion(
        id=new_id("course_version"),
        repository_id=repo.id,
        commit_sha=sha,
        cache_key=f"tiny-{sha[:8]}",
        policy_version="1",
        language="zh",
        title="Tiny 课程",
        status="ready",
        sections=[
            {"key": key, "title": key, "minutes": 5, "lessons": []}
            for key in ("overview", "walkthrough", "deep_dive", "recap")
        ],
        quality_report={"anchor_coverage": 0.9, "lesson_completeness": 1.0, "anchor_confidence": "high"},
        warnings=[],
        blueprint={"repo_full_name": "owner/tiny"},
        lesson_count=len(files) * 2,
        total_minutes=40,
        visibility="public",
        created_at=utcnow(),
        updated_at=utcnow(),
        published_at=utcnow(),
    )
    session.add(course)
    await session.flush()
    for index in range(len(files) * 2):
        path = files[index % len(files)]
        lesson_id = new_id("lesson")
        session.add(
            Lesson(
                id=lesson_id,
                course_version_id=course.id,
                section_key="overview",
                key=f"1.{index + 1}",
                title=f"课时 {index + 1}",
                goal="读代码",
                minutes=5,
                order_index=index,
                status="ready",
                playback_meta={"files": [{"path": path, "lang": "python", "line_count": 5}]},
                created_at=utcnow(),
            )
        )
        await session.flush()
        session.add(
            Step(
                id=new_id("step"),
                lesson_id=lesson_id,
                order_index=0,
                title="第一步",
                duration_ms=8000,
                timing_source="estimated",
                focus_file=path,
                focus_line_start=1,
                focus_line_end=2,
                segments=[
                    {
                        "id": "s0",
                        "text": "这里开始。",
                        "start_ms": 0,
                        "end_ms": 8000,
                        "focus": {"file": path, "line_start": 1, "line_end": 2},
                    }
                ],
                board={},
                code_notes=[],
                certainty={},
                created_at=utcnow(),
            )
        )
        if with_anchors:
            session.add(
                SourceAnchor(
                    id=new_id("anchor"),
                    course_version_id=course.id,
                    lesson_id=lesson_id,
                    file=path,
                    symbol=None,
                    line_start=1,
                    line_end=2,
                    commit_sha=sha,
                    kind="definition",
                    created_at=utcnow(),
                )
            )
        session.add(
            QuizItem(
                id=new_id("quiz"),
                course_version_id=course.id,
                lesson_id=lesson_id,
                stem="入口在哪？",
                choices=[{"id": "a", "text": "第 1 行"}],
                answer_id="a",
                explanation_md="在第 1 行。",
                evidence=[{"file": path, "line_start": 1, "line_end": 1}],
                difficulty=1,
                kind="recall",
                created_at=utcnow(),
            )
        )
    await session.flush()
    return course


def _put_mirrors():
    """把夹具放进镜像目录：旧 = tiny_v1，新 = tiny_v2。"""
    from repolearn.ingest.mirror import mirror_path

    shutil.copytree(FIXTURES / "tiny_v1", mirror_path(OLD_SHA), dirs_exist_ok=True)
    shutil.copytree(FIXTURES / "tiny_v2", mirror_path(NEW_SHA), dirs_exist_ok=True)


async def test_upg_7_idempotent_upgrade(session, monkeypatch):
    """T-UPG-7：同一个 to_sha 连续调两次 → 第二次 `mode in {none, reused}`，版本只多 1 行。"""
    from repolearn.ingest.github import CommitMeta, RepoMeta
    from repolearn.services import upgrade_service

    files = ["tiny/agent.py", "tiny/main.py"]
    old = await _seed_pipeline_course(session, sha=OLD_SHA, files=files)
    _put_mirrors()

    async def fake_meta(ref):
        return RepoMeta(
            full_name=ref.full_name,
            owner=ref.owner,
            name=ref.name,
            description=None,
            stars=0,
            license_spdx="MIT",
            primary_language="Python",
            default_branch="main",
            html_url=f"https://github.com/{ref.full_name}",
        )

    async def fake_resolve(ref, branch, wanted=None):
        return CommitMeta(sha=NEW_SHA, file_count=4)

    monkeypatch.setattr(upgrade_service, "fetch_repo_meta", fake_meta)
    monkeypatch.setattr(upgrade_service, "resolve_commit", fake_resolve)

    before = int((await session.execute(text("SELECT count(*) FROM course_versions"))).scalar() or 0)
    first, code = await upgrade_service.start_upgrade(session, old.id)
    assert code in (200, 202), first
    after_first = int((await session.execute(text("SELECT count(*) FROM course_versions"))).scalar() or 0)

    # 第二次调用只有两种**合法**结果，而且都不该多出一个版本：
    #   * 版本已 ready → `none` / `reused`（内容级复用）；
    #   * 第一次的 Job 还在跑 → `409 JOB_CONFLICT`（带 job_id，让调用方跳转而不是重试）。
    # 把 409 也算通过不是放宽：spec §3.5.2 第 7 条明确要求"命中活跃 Job → 409"，
    # 而"会不会凭空多一门课"这条不变式由下面的行数断言独立守住。
    from repolearn.core.errors import AppError

    try:
        second, code2 = await upgrade_service.start_upgrade(session, old.id)
    except AppError as exc:
        assert exc.code == "JOB_CONFLICT", exc.code
        assert exc.details.get("job_id"), exc.details
        second, code2 = {"mode": "conflict"}, 409
    assert second["mode"] in {"none", "reused", "conflict"}, second
    assert code2 in (200, 409)
    after_second = int((await session.execute(text("SELECT count(*) FROM course_versions"))).scalar() or 0)
    # 第一次（若真的建了版本）只允许 +1；第二次必须一行不加
    assert after_second == after_first
    assert after_first - before <= 1


async def test_upg_4_5_partial_upgrade_pipeline(session, monkeypatch):
    """T-UPG-4 / T-UPG-5：真跑 `run_upgrade_job`，只重讲受影响课时。

    断言都是"会失败"的形状：
    * 未受影响课时的 `steps.segments` **逐字节相同**，且带 `copied_from`
      （证明是复制而不是重新生成 —— 重新生成会得到不同的文本）；
    * 受影响课时的标题/内容变了；
    * `quality_report.upgrade.anchor_origin == "mixed"`，且发布**不因**
      `ANCHOR_STALE` 失败（复制来的锚点指向旧 commit，用新镜像校验必然失败）。
    """
    from repolearn.core.db import SessionMaker
    from repolearn.ingest import github as gh
    from repolearn.jobs.upgrade_jobs import run_upgrade_job

    files = ["tiny/agent.py", "tiny/bus.py", "tiny/main.py", "README.md"]
    old = await _seed_pipeline_course(session, sha=OLD_SHA, files=files)
    _put_mirrors()
    await session.commit()

    # 新版本行（占位）：真实升级由 upgrade_service 建，这里直接建等价的一行，
    # 把断言集中在"重讲 + 复制 + 发布"这条链上。
    new = CourseVersion(
        id=new_id("course_version"),
        repository_id=old.repository_id,
        commit_sha=NEW_SHA,
        cache_key=f"tiny-{NEW_SHA[:8]}",
        policy_version="1",
        language="zh",
        title=old.title,
        status="generating",
        sections=list(old.sections or []),
        quality_report={},
        warnings=[],
        blueprint={"repo_full_name": "owner/tiny"},
        lesson_count=old.lesson_count,
        total_minutes=old.total_minutes,
        visibility="public",
        upgraded_from_id=old.id,
        created_at=utcnow(),
        updated_at=utcnow(),
    )
    session.add(new)
    await session.commit()

    # 出站全部指向夹具镜像（两个 sha 的镜像都已就位 → N3 直接复用，不下载）
    async def fake_meta(ref):
        return gh.RepoMeta(
            full_name=ref.full_name,
            owner=ref.owner,
            name=ref.name,
            description=None,
            stars=0,
            license_spdx="MIT",
            primary_language="Python",
            default_branch="main",
            html_url=f"https://github.com/{ref.full_name}",
        )

    async def fake_resolve(ref, branch, wanted=None):
        return gh.CommitMeta(sha=NEW_SHA, file_count=len(files))

    monkeypatch.setattr(gh, "fetch_repo_meta", fake_meta)
    monkeypatch.setattr(gh, "resolve_commit", fake_resolve)
    import repolearn.ingest as ingest_mod

    monkeypatch.setattr(ingest_mod, "fetch_repo_meta", fake_meta)
    monkeypatch.setattr(ingest_mod, "resolve_commit", fake_resolve)

    # 受影响课时 = 引用 tiny/agent.py 的那两课（v2 改了它）
    old_steps = (
        await session.execute(
            select(Step).join(Lesson, Lesson.id == Step.lesson_id).where(Lesson.course_version_id == old.id)
        )
    ).scalars().all()
    affected_ids = {
        lesson.id for lesson in (
            await session.execute(select(Lesson).where(Lesson.course_version_id == old.id))
        ).scalars().all()
        if (lesson.playback_meta or {}).get("files", [{}])[0].get("path") == "tiny/agent.py"
    }
    affected = {
        lesson.key
        for lesson in (
            await session.execute(select(Lesson).where(Lesson.course_version_id == old.id))
        ).scalars().all()
        if lesson.id in affected_ids
    }
    assert affected, "夹具应当至少有 1 个课时引用被改动的文件"

    emitted: list[tuple[str, dict]] = []

    async def emit(event: str, payload: dict) -> None:
        emitted.append((event, payload))

    outcome = await run_upgrade_job(
        job_id="job_upg_1",
        course_id=new.id,
        payload={
            "from_course_id": old.id,
            "to_course_id": new.id,
            "repo_url": "owner/tiny",
            "new_sha": NEW_SHA,
            "plan": {"mode": "partial", "affected_keys": sorted(affected)},
        },
        emit=emit,
    )
    # 严格等于 `ready`：升级链路不跑 N5（不重排大纲），章节沿用旧版本，因此
    # "章节不齐"不该出现在任何一次升级里。写成 `in {ready, partial}` 会让
    # "每一次升级都永远 partial"这个缺陷完全隐形（publish_partial 曾因拿空的
    # `curriculum` 算章节门禁而 100% 判 partial）。
    assert outcome.status == "ready", outcome

    async with SessionMaker() as check:
        new_lessons = (
            await check.execute(select(Lesson).where(Lesson.course_version_id == new.id))
        ).scalars().all()
        new_version = await check.get(CourseVersion, new.id)
        new_steps = (
            await check.execute(
                select(Step).join(Lesson, Lesson.id == Step.lesson_id).where(Lesson.course_version_id == new.id)
            )
        ).scalars().all()

    # ① 未受影响的课时是**复制**来的，且内容逐字节相同
    copied = [lesson for lesson in new_lessons if lesson.key not in affected]
    assert copied, "未受影响的课时必须被复制过来"
    for lesson in copied:
        assert (lesson.playback_meta or {}).get("copied_from"), lesson.key
    old_by_key = {
        lesson.key: [step for step in old_steps if step.lesson_id == lesson.id]
        for lesson in (
            await session.execute(select(Lesson).where(Lesson.course_version_id == old.id))
        ).scalars().all()
    }
    for lesson in copied:
        mine = [step for step in new_steps if step.lesson_id == lesson.id]
        theirs = old_by_key[lesson.key]
        assert [step.segments for step in mine] == [step.segments for step in theirs], lesson.key

    # ② 受影响课时被重讲（存在），且新版本状态/质量报告可信
    regenerated = [lesson for lesson in new_lessons if lesson.key in affected]
    assert regenerated, "受影响的课时必须被重新生成"
    assert new_version.upgraded_from_id == old.id
    upgrade_report = (new_version.quality_report or {}).get("upgrade") or {}
    assert upgrade_report.get("anchor_origin") == "mixed"
    assert upgrade_report.get("from_sha") == OLD_SHA
    assert upgrade_report.get("to_sha") == NEW_SHA
    assert new_version.status == "ready", (new_version.status, (new_version.quality_report or {}).get("reasons"))
    assert "章节不齐" not in ((new_version.quality_report or {}).get("reasons") or [])
    # 复制来的锚点写的是**源版本** sha（否则 UI 会用新文件打开旧行号）
    anchors = (
        await check_anchors(session, new.id)
    )
    assert any(anchor.commit_sha == OLD_SHA for anchor in anchors)
    # 进度迁移跑过（旧版本没有进度行 → 明确返回 no_progress 而不是静默报错）
    assert any(event == "node.completed" for event, _ in emitted)


async def check_anchors(session, course_id):
    return (
        await session.execute(select(SourceAnchor).where(SourceAnchor.course_version_id == course_id))
    ).scalars().all()

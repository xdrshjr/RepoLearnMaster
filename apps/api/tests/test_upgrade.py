"""升级计划的纯函数与接口门禁（hardening spec §7.5：T-UPG-1/2/3/7）。"""

from __future__ import annotations

import pytest
from sqlalchemy import select, text

from repolearn.analysis.diff import (
    FileDelta,
    LessonRef,
    diff_snapshots,
    plan_upgrade,
)
from repolearn.core.config import REPO_ROOT

FIXTURES = REPO_ROOT / "tests" / "fixtures" / "repos"


def test_upg_1_plan_upgrade_six_scenarios():
    """T-UPG-1：判定顺序即语义，六个场景逐一钉死。

    最容易写错的是第 2 条：没有受影响课时必须是 `none` 而**不是** `partial`——
    否则用户点一次"检查更新"就会得到一个与旧版逐字节相同的新版本。
    """
    lessons = [LessonRef(key=f"1.{i}", files=(f"f{i}.py",)) for i in range(1, 11)]

    assert plan_upgrade(lessons, [], total_files=50).mode == "none"
    assert plan_upgrade([], [FileDelta("a.py", "modified")], total_files=10, old_mirror_ok=False).mode == "full"

    one_file = [FileDelta("f3.py", "modified")]
    partial = plan_upgrade(lessons, one_file, total_files=50)
    assert partial.mode == "partial"
    assert partial.affected_keys == ("1.3",)
    assert partial.stats["files_modified"] == 1

    # 受影响 70% → full（阈值 0.6）
    heavy = [FileDelta(f"f{i}.py", "modified") for i in range(1, 8)]
    shifted = plan_upgrade(lessons, heavy, total_files=50)
    assert shifted.mode == "full"
    assert shifted.reasons[0].startswith("curriculum_shift")

    # 新增 4 个文件（阈值 max(3, ceil(50*0.1)=5) 时不够；这里用 6 个触发）
    many_new = [FileDelta(f"new{i}.py", "added") for i in range(6)] + [FileDelta("f1.py", "modified")]
    new_files = plan_upgrade(lessons, many_new, total_files=50)
    assert new_files.mode == "full"
    assert new_files.reasons[0].startswith("many_new_files")

    missing_mirror = plan_upgrade(lessons, one_file, total_files=50, old_mirror_ok=False)
    assert missing_mirror.mode == "full"
    assert missing_mirror.reasons == ("old_mirror_missing",)


def test_upg_2_diff_snapshots_shape_is_deterministic():
    """T-UPG-2：tiny_v1 → tiny_v2 恰好 1 modified + 1 added + 1 removed。

    形状（而不是"数量"）是这条断言的关键：如果夹具被改成"全部重写"，
    升级路径就再也不会被真正走到，而测试会继续绿。
    """
    deltas = diff_snapshots(FIXTURES / "tiny_v1", FIXTURES / "tiny_v2")
    by_status: dict[str, list[str]] = {}
    for delta in deltas:
        by_status.setdefault(delta.status, []).append(delta.path)
    assert by_status.get("modified") == ["tiny/agent.py"]
    assert by_status.get("added") == ["tiny/router.py"]
    assert by_status.get("removed") == ["tiny/bus.py"]
    # 确定性：同样的输入两次得到完全相同的序列
    assert diff_snapshots(FIXTURES / "tiny_v1", FIXTURES / "tiny_v2") == deltas
    # README / main.py 逐字节未变，因此不能出现在 delta 里（"少判一次就多重建一课"）
    assert not any(d.path.endswith("main.py") for d in deltas)


@pytest.fixture()
def stubbed_github(monkeypatch):
    """把出站替换成"已知新 sha + 夹具镜像"，让升级路径能离线跑。"""
    from repolearn.ingest import github as github_mod

    async def fake_meta(ref):
        return github_mod.RepoMeta(full_name=ref.full_name,
            owner=ref.owner,
            name=ref.name,
            description="fixture",
            stars=1,
            license_spdx="MIT",
            primary_language="Python",
            default_branch="main",
            html_url=f"https://github.com/{ref.full_name}",
        )

    monkeypatch.setattr(github_mod, "fetch_repo_meta", fake_meta)
    return monkeypatch


async def _seed_version(session, *, sha: str, files: list[str]) -> str:
    from repolearn.core.clock import utcnow
    from repolearn.core.ids import new_id
    from repolearn.models import Commit, CourseVersion, Lesson, Repository, Step

    repo = Repository(
        id=new_id("repository"),
        full_name="owner/repo",
        owner="owner",
        name="repo",
        description="fixture",
        stars=1,
        license_spdx="MIT",
        primary_language="Python",
        default_branch="main",
        html_url="https://github.com/owner/repo",
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
        cache_key=f"seed-{sha[:8]}",
        policy_version="1",
        language="zh",
        title="旧版本课程",
        status="ready",
        sections=[
            {"key": "overview", "title": "第一层", "minutes": 5, "lessons": []},
            {"key": "walkthrough", "title": "第二层", "minutes": 5, "lessons": []},
            {"key": "deep_dive", "title": "第三层", "minutes": 5, "lessons": []},
            {"key": "recap", "title": "第四层", "minutes": 5, "lessons": []},
        ],
        quality_report={"anchor_coverage": 0.9, "lesson_completeness": 1.0},
        warnings=[],
        blueprint={"repo_full_name": "owner/repo"},
        lesson_count=len(files),
        total_minutes=20,
        visibility="public",
        created_at=utcnow(),
        updated_at=utcnow(),
        published_at=utcnow(),
    )
    session.add(course)
    await session.flush()
    for index, path in enumerate(files):
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
    await session.flush()
    return course.id


async def test_upg_3_dry_run_does_not_write(session, stubbed_github, monkeypatch):
    """T-UPG-3：`dry_run=True` 后 `course_versions` / `jobs` 行数不变。"""
    from repolearn.services import upgrade_service

    old_sha = "1" * 64
    new_sha = "2" * 64
    await _seed_version(session, sha=old_sha, files=["tiny/agent.py", "tiny/main.py"])

    from repolearn.ingest.github import CommitMeta, RepoMeta

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
        return CommitMeta(sha=new_sha, file_count=2)

    # `upgrade_service` 是 `from ... import` 引入的，因此要打它自己的命名空间
    monkeypatch.setattr(upgrade_service, "fetch_repo_meta", fake_meta)
    monkeypatch.setattr(upgrade_service, "resolve_commit", fake_resolve)
    # 旧镜像存在 → 不会走下载；新镜像不存在 → 走"下载 + 解包"，这里用夹具目录顶替
    source = FIXTURES / "tiny_v2"
    import shutil

    from repolearn.ingest.mirror import mirror_path

    old_mirror = mirror_path(old_sha)
    shutil.copytree(FIXTURES / "tiny_v1", old_mirror, dirs_exist_ok=True)
    new_mirror = mirror_path(new_sha)
    shutil.copytree(source, new_mirror, dirs_exist_ok=True)

    before_courses = int((await session.execute(text("SELECT count(*) FROM course_versions"))).scalar() or 0)
    before_jobs = int((await session.execute(text("SELECT count(*) FROM jobs"))).scalar() or 0)

    course_id = (
        await session.execute(select(__import__("repolearn.models", fromlist=["CourseVersion"]).CourseVersion.id))
    ).scalar_one()

    body, code = await upgrade_service.start_upgrade(session, course_id, dry_run=True)
    assert code == 200
    assert body["mode"] in {"partial", "full", "none"}
    assert body["from_sha"] == old_sha[:8]
    assert body["to_sha"] == new_sha[:8]
    after_courses = int((await session.execute(text("SELECT count(*) FROM course_versions"))).scalar() or 0)
    after_jobs = int((await session.execute(text("SELECT count(*) FROM jobs"))).scalar() or 0)
    assert (after_courses, after_jobs) == (before_courses, before_jobs)


# --------------------------------------------------------------------------- #
# T-UPG-8 / 9：路由层接线                                                      #
# --------------------------------------------------------------------------- #


async def test_upg_8_route_actually_calls_upgrade_service(client, ready_course, monkeypatch):
    """T-UPG-8：`POST /v1/courses/{id}/upgrade` 必须真的走 `upgrade_service`。

    v1 的路由调的是 `course_service.start_upgrade`——那个函数**不存在**，于是在
    所有 service 级用例全绿的情况下，这个接口 100% `AttributeError` → 500。
    这类"服务层绿、路由层死"的缺口只有经 TestClient 打一次才看得见，因此这里
    故意让服务内部的出站调用失败：只有真的进到服务里，才会得到映射后的
    `REPO_NOT_FOUND` 而不是 FastAPI 的 500。
    """
    from repolearn.core.errors import AppError
    from repolearn.services import upgrade_service

    async def boom(ref):
        raise AppError("REPO_NOT_FOUND", "仓库不存在")

    monkeypatch.setattr(upgrade_service, "fetch_repo_meta", boom)
    resp = await client.post(f"/v1/courses/{ready_course['course_id']}/upgrade", json={"dry_run": True})
    assert resp.status_code == 404, resp.text
    assert resp.json()["error"]["code"] == "REPO_NOT_FOUND"


async def test_upg_9_route_dry_run_plan_shape(client, ready_course, monkeypatch):
    """T-UPG-9：`dry_run` 响应形状（spec §5.1.2）少一个字段就是"空抽屉"。

    前端抽屉按 `mode / reasons / stats / affected_lessons / from_sha / to_sha`
    渲染，只断言"返回 200"等于什么都没断言。
    """
    from repolearn.analysis.diff import UpgradePlan
    from repolearn.services import upgrade_service

    async def fake_prepare(session, course, repo, *, ref):
        return (
            "b" * 64,
            UpgradePlan(
                mode="partial",
                affected_keys=("1.1",),
                reasons=("1 files changed, 1 lessons affected",),
                stats={"files_modified": 1, "lessons_total": 1, "total_files": 4},
            ),
            False,
        )

    monkeypatch.setattr(upgrade_service, "_prepare", fake_prepare)
    resp = await client.post(f"/v1/courses/{ready_course['course_id']}/upgrade", json={"dry_run": True})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["mode"] == "partial"
    assert body["from_sha"] == ready_course["sha"][:8]
    assert body["to_sha"] == "b" * 8
    assert body["affected_lessons"] == [{"key": "1.1", "title": "走读"}]
    assert body["stats"]["total_files"] == 4

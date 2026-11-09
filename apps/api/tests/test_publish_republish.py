"""同一个课程版本可以**重复发布**（T-PUB-1）。

真实现场（2026-11-09，job `job_01M6ZM6TBZR60JN48R9JVT6HKR`）：

    sqlite3.IntegrityError: UNIQUE constraint failed: lessons.course_version_id, lessons.key
    [SQL: INSERT INTO lessons (id, course_version_id, section_key, key, ...)]

`/rebuild` 与"同一个 commit 再生成一次"都是**同一个 course_version 重新发布**，
而 `publish()` 只 INSERT、不清理上一版留下的子行。于是：

* 第一次发布成功（哪怕只是 partial）；
* 之后每一次「重新生成」都会在发布阶段抛唯一约束错误 → job 以
  "生成过程中出现内部错误"失败；
* 用户看到的现象是"重新生成永远失败"，而课时内容其实完全正常。

这条用例直接在同一课程行上发布两次，并要求第二次不炸、且行数不翻倍。
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest
from sqlalchemy import func, select

from repolearn.core.clock import utcnow
from repolearn.core.db import SessionMaker
from repolearn.core.ids import new_id
from repolearn.models import CourseVersion, Lesson, Repository, SourceAnchor, Step
from repolearn.workflow.publish import publish

SHA = "a" * 40
FILE_LINES = {"pkg/core.py": 50}


@dataclass
class _Artifacts:
    """内存版产物仓库：`load_artifact` 的替身。"""

    docs: dict[str, dict]

    def __call__(self, key: str) -> dict:  # noqa: ANN001
        return self.docs.get(key, {})


def _lesson_doc(key: str) -> dict:
    return {
        "key": key,
        "title": f"课时 {key}",
        "layer": "overview",
        "minutes": 5,
        "steps": [
            {
                "index": 0,
                "title": "step",
                "duration_ms": 5000,
                "segments": [
                    {
                        "id": "s0",
                        "text": "讲一句",
                        "start_ms": 0,
                        "end_ms": 5000,
                        "focus": {"file": "pkg/core.py", "line_start": 1, "line_end": 10},
                    }
                ],
            }
        ],
        "quiz": [],
        "files": [{"path": "pkg/core.py"}],
    }


def _curriculum(keys: list[str]) -> dict:
    sections = []
    for section_key in ("overview", "walkthrough", "deep_dive", "recap"):
        sections.append({"key": section_key, "title": section_key, "minutes": 10, "lessons": []})
    for index, key in enumerate(keys):
        sections[index % 4]["lessons"].append({"key": key, "title": key, "minutes": 5})
    return {"title": "t", "sections": sections, "summary_md": "s"}


async def _make_course(session) -> str:  # noqa: ANN001
    repo = Repository(
        id=new_id("repository"),
        full_name=f"fixture/republish-{new_id('r')}",
        owner="fixture",
        name="republish",
        description="d",
        stars=1,
        license_spdx="MIT",
        primary_language="Python",
        default_branch="main",
        html_url="https://github.com/fixture/republish",
        is_public=True,
        created_at=utcnow(),
        updated_at=utcnow(),
    )
    session.add(repo)
    await session.flush()
    course = CourseVersion(
        id=new_id("course_version"),
        repository_id=repo.id,
        commit_sha=SHA,
        cache_key=f"key-{new_id('k')}",
        policy_version="v1",
        language="zh",
        title="t",
        status="generating",
        sections=[],
        quality_report={},
        warnings=[],
        blueprint={},
        cover_palette="mint",
        owner_user_id=None,
        visibility="public",
        created_at=utcnow(),
        updated_at=utcnow(),
    )
    session.add(course)
    await session.flush()
    return course.id


def test_lesson_files_are_derived_from_anchors():
    """T-PUB-2：课时没写 `files` 时，用锚点反推（文件树不能显示 0/0 个文件）。"""
    from repolearn.workflow.publish import _lesson_files

    doc = {
        "key": "ov-layers",
        "steps": [
            {
                "segments": [
                    {"focus": {"file": "pkg/a.py", "line_start": 1, "line_end": 5}},
                    {"focus": {"file": "pkg/b.py", "line_start": 3, "line_end": 9}},
                    {"focus": {"file": "pkg/a.py", "line_start": 10, "line_end": 12}},
                ],
                "code_notes": [{"file": "pkg/c.py", "line": 2}],
            }
        ],
    }
    assert _lesson_files(doc) == [{"path": "pkg/a.py"}, {"path": "pkg/b.py"}, {"path": "pkg/c.py"}]

    # 模型自己给了 files 就尊重它
    assert _lesson_files({"files": [{"path": "x.py"}], "steps": []}) == [{"path": "x.py"}]
    assert _lesson_files({"steps": []}) == []


@pytest.mark.asyncio
async def test_publishing_the_same_course_twice_does_not_violate_unique_key():
    keys = [f"l{i}" for i in range(1, 9)]
    docs = {f"write/{key}.json": _lesson_doc(key) for key in keys}
    artifacts = _Artifacts(docs)
    lessons_ref = {key: {"artifact": f"write/{key}.json", "anchors": []} for key in keys}
    curriculum = _curriculum(keys)

    async with SessionMaker() as session:
        course_id = await _make_course(session)
        await session.commit()

    for _attempt in (1, 2):
        async with SessionMaker() as session:
            result = await publish(
                session,
                course_id=course_id,
                curriculum=curriculum,
                lessons=lessons_ref,
                traces={},
                narration={},
                commit_sha=SHA,
                file_lines=FILE_LINES,
                warnings=[],
                failed_lessons=[],
                runtime="kernel",
                load_artifact=artifacts,
            )
            await session.commit()
        assert result["status"] in {"ready", "partial"}, result

    async with SessionMaker() as session:
        lesson_rows = (
            await session.execute(select(func.count()).select_from(Lesson).where(Lesson.course_version_id == course_id))
        ).scalar_one()
        step_rows = (await session.execute(select(func.count()).select_from(Step))).scalar_one()
        anchor_rows = (
            await session.execute(
                select(func.count()).select_from(SourceAnchor).where(SourceAnchor.course_version_id == course_id)
            )
        ).scalar_one()

    # 第二次发布覆盖第一次，而不是叠加——否则课时列表里会出现两份同 key 的课时
    assert lesson_rows == len(keys), f"课时行数 {lesson_rows}，应为 {len(keys)}"
    assert step_rows == len(keys), f"step 行数 {step_rows}，应为 {len(keys)}"
    assert anchor_rows >= len(keys), anchor_rows

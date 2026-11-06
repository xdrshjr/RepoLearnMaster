"""任务、对象代理与进度/答题 API（T-IDEM-1 / T-QUIZ-2 / §5.2 Range 契约）。"""

from __future__ import annotations

import os

from repolearn.models import QuizAttempt
from repolearn.services import object_store


async def test_jobs_list_empty(client):
    resp = await client.get("/v1/jobs")
    assert resp.status_code == 200
    assert resp.json()["items"] == []


async def test_job_not_found(client):
    resp = await client.get("/v1/jobs/job_nope")
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "JOB_NOT_FOUND"


async def test_job_lifecycle_visible_after_rebuild(client, ready_course):
    created = await client.post(
        f"/v1/courses/{ready_course['course_id']}/rebuild", json={"reason": "t"}
    )
    job_id = created.json()["job_id"]
    detail = await client.get(f"/v1/jobs/{job_id}")
    assert detail.status_code == 200
    body = detail.json()
    assert body["kind"] == "course"
    assert body["status"] == "queued"
    assert body["cost"]["tokens"] == 0

    listed = await client.get("/v1/jobs?kind=course")
    assert any(item["id"] == job_id for item in listed.json()["items"])


async def test_cancel_unknown_job_is_404(client):
    resp = await client.post("/v1/jobs/job_nope/cancel")
    assert resp.status_code == 404


async def test_metrics_shape(client):
    resp = await client.get("/v1/metrics")
    assert resp.status_code == 200
    body = resp.json()
    for key in ("jobs", "cache", "providers", "learning"):
        assert key in body
    assert "success_rate" in body["jobs"]


async def test_healthz_reports_gates(client):
    resp = await client.get("/healthz")
    assert resp.status_code == 200
    body = resp.json()
    assert body["db"] is True
    assert body["migration"] is True
    assert set(body["gates"]) >= {"g1", "g2", "g3"}


async def test_object_range_contract(client):
    """Range/ETag 契约（§5.2）：206 / 416 / 304 三态都必须是真的是这三态。"""
    key = object_store.put_content_addressed("audio", b"0123456789abcdef", ".mp3")
    url = f"/v1/objects/audio/{key}"

    full = await client.get(url)
    assert full.status_code == 200
    assert full.headers["accept-ranges"] == "bytes"
    etag = full.headers["etag"]

    partial = await client.get(url, headers={"Range": "bytes=0-3"})
    assert partial.status_code == 206
    assert partial.content == b"0123"
    assert partial.headers["content-range"] == "bytes 0-3/16"

    invalid = await client.get(url, headers={"Range": "bytes=99-120"})
    assert invalid.status_code == 416
    assert invalid.headers["content-range"] == "bytes */16"

    cached = await client.get(url, headers={"If-None-Match": etag})
    assert cached.status_code == 304


async def test_object_missing(client):
    resp = await client.get("/v1/objects/audio/aa/none.mp3")
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "OBJECT_MISSING"


async def test_progress_put_is_monotonic(client, ready_course):
    course_id = ready_course["course_id"]
    first = await client.put(
        f"/v1/courses/{course_id}/progress",
        json={"lesson_key": "1.1", "step_index": 0, "position_ms": 3000, "percent": 40},
    )
    assert first.status_code == 200
    assert first.json()["course_percent"] == 40

    back = await client.put(
        f"/v1/courses/{course_id}/progress",
        json={"lesson_key": "1.1", "step_index": 0, "position_ms": 1000, "percent": 10},
    )
    # 往回拖不应让完成度倒退，否则完课判据会在拖拽后失效
    assert back.json()["course_percent"] == 40


async def test_progress_beacon_accepts_text_body(client, ready_course):
    body = '{"lesson_key": "1.1", "step_index": 0, "position_ms": 5000, "percent": 60}'
    resp = await client.post(
        f"/v1/courses/{ready_course['course_id']}/progress/beacon",
        content=body.encode(),
        headers={"content-type": "text/plain"},
    )
    assert resp.status_code == 204


async def test_quiz_answer_and_idempotency(client, session, ready_course):
    """T-QUIZ-2：同一题提交 3 次，表里只有 1 行，后两次 `replayed:true`。"""
    course_id = ready_course["course_id"]
    item_id = ready_course["quiz_item_id"]
    url = f"/v1/courses/{course_id}/quiz/{item_id}/answer"

    first = await client.post(url, json={"choice_id": "a"})
    assert first.status_code == 200
    assert first.json()["correct"] is True
    assert first.json()["replayed"] is False
    assert first.json()["explanation_md"]

    second = await client.post(url, json={"choice_id": "b"})
    assert second.json()["replayed"] is True
    # 重放必须返回首次结果，而不是按新选择重算
    assert second.json()["correct"] is True

    third = await client.post(url, json={"choice_id": "a"})
    assert third.json()["replayed"] is True

    from sqlalchemy import func, select

    count = (
        await session.execute(
            select(func.count(QuizAttempt.id)).where(QuizAttempt.quiz_item_id == item_id)
        )
    ).scalar()
    assert count == 1


async def test_recap_shape(client, ready_course):
    resp = await client.get(f"/v1/courses/{ready_course['course_id']}/recap")
    assert resp.status_code == 200
    body = resp.json()
    assert body["quiz_stats"]["total"] == 1
    assert set(body["ability"]) >= {"架构理解", "完成度"}
    assert body["knowledge_points"][0]["key"] == "1.1"
    assert body["next_steps"]


async def test_ask_stream_offline_degrades_to_static_answer(client, ready_course):
    """无 AI 配置时行内提问**不应报错**，而要给明确标注的静态呈现。"""
    resp = await client.post(
        f"/v1/courses/{ready_course['course_id']}/questions",
        json={"file": "pkg/mod.py", "line_start": 1, "line_end": 2, "question": "foo 做什么？"},
    )
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/event-stream")
    assert resp.headers["x-accel-buffering"] == "no"
    text = resp.text
    assert "question.completed" in text
    assert "未启用 AI" in text or "静态呈现" in text


async def test_notes_crud(client, ready_course):
    created = await client.post(
        "/v1/notes",
        json={"course_version_id": ready_course["course_id"], "body_md": "这行很关键", "tags": ["重点"]},
    )
    assert created.status_code == 200
    note_id = created.json()["id"]

    listed = await client.get("/v1/notes")
    assert len(listed.json()["items"]) == 1

    patched = await client.patch(f"/v1/notes/{note_id}", json={"body_md": "改一下"})
    assert patched.json()["body_md"] == "改一下"

    deleted = await client.delete(f"/v1/notes/{note_id}")
    assert deleted.status_code == 204
    assert (await client.get("/v1/notes")).json()["items"] == []

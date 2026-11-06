"""课程与课时 API（spec §5.2 / §5.3 / T-PLAY-1）。"""

from __future__ import annotations


async def test_list_courses_empty(client):
    resp = await client.get("/v1/courses")
    assert resp.status_code == 200
    body = resp.json()
    # 空列表的语义：没有任何课程、生效模式是 `none`（没检索条件）、无分页信息。
    # 这三个"空"不是一回事——`mode=none` 表示"没检索"，不是"检索了但没结果"，
    # 前端据此决定展示热门列表还是空态文案（hardening spec §3.4.4）。
    assert body["items"] == []
    assert body["next_cursor"] is None
    assert body["mode"] == "none"
    assert body["fallback_reason"] is None
    assert body["next_offset"] is None
    assert body["total"] is None


async def test_list_courses_returns_projection(client, ready_course):
    resp = await client.get("/v1/courses")
    body = resp.json()
    assert len(body["items"]) == 1
    item = body["items"][0]
    assert item["id"] == ready_course["course_id"]
    assert item["repo"]["full_name"] == "owner/repo"
    assert item["lesson_count"] == 1
    assert item["quality"]["anchor_coverage"] == 0.9


async def test_list_courses_filters_by_status(client, ready_course):
    assert len((await client.get("/v1/courses?status=ready")).json()["items"]) == 1
    assert len((await client.get("/v1/courses?status=generating")).json()["items"]) == 0


async def test_get_course_detail(client, ready_course):
    resp = await client.get(f"/v1/courses/{ready_course['course_id']}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == ready_course["course_id"]
    assert body["status"] == "ready"
    assert body["sections"][0]["key"] == "overview"
    assert body["commit"]["sha"] == ready_course["sha"]


async def test_missing_course_is_404_with_hint(client):
    resp = await client.get("/v1/courses/crs_does_not_exist")
    assert resp.status_code == 404
    error = resp.json()["error"]
    assert error["code"] == "COURSE_NOT_READY"
    assert error["req_id"]


async def test_lessons_list_groups_by_section(client, ready_course):
    resp = await client.get(f"/v1/courses/{ready_course['course_id']}/lessons")
    body = resp.json()
    assert body["sections"][0]["lessons"][0]["key"] == "1.1"
    assert body["sections"][0]["lessons"][0]["step_count"] == 1


async def test_playback_bundle_shape(client, ready_course):
    """`PlaybackBundle` 是播放器的唯一数据源（§5.3）：segments 必须连续。"""
    resp = await client.get(f"/v1/courses/{ready_course['course_id']}/lessons/1.1/playback")
    assert resp.status_code == 200
    assert resp.headers["cache-control"] == "no-store"
    bundle = resp.json()
    assert bundle["lesson"]["key"] == "1.1"
    assert bundle["commit_sha"] == ready_course["sha"]
    step = bundle["steps"][0]
    assert step["timing_source"] == "estimated"
    assert step["audio"] is None
    segs = step["segments"]
    assert segs[0]["start_ms"] == 0
    assert segs[-1]["end_ms"] == step["duration_ms"]
    assert step["certainty_legend"]["source_fact"] == "源码事实"
    assert bundle["files"][0]["content_ref"].startswith("/api/courses/")


async def test_missing_lesson_is_404(client, ready_course):
    resp = await client.get(f"/v1/courses/{ready_course['course_id']}/lessons/9.9/playback")
    assert resp.status_code == 404


async def test_file_content_rejects_traversal(client, ready_course):
    """`?path=../../etc/passwd` 必须被拒绝（T-SEC-2 的 API 侧）。"""
    resp = await client.get(
        f"/v1/courses/{ready_course['course_id']}/files", params={"path": "../../etc/passwd"}
    )
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "INGEST_BLOCKED_PATH"


async def test_file_content_returns_source(client, ready_course):
    resp = await client.get(
        f"/v1/courses/{ready_course['course_id']}/files", params={"path": "pkg/mod.py"}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "def foo" in body["content"]
    assert body["lang"] == "python"
    assert resp.headers["cache-control"].startswith("private")


async def test_file_content_rejects_file_outside_mirror(client, ready_course):
    resp = await client.get(
        f"/v1/courses/{ready_course['course_id']}/files", params={"path": "pkg/other.py"}
    )
    assert resp.status_code == 404


async def test_soft_delete_hides_course(client, ready_course):
    deleted = await client.delete(f"/v1/courses/{ready_course['course_id']}")
    assert deleted.status_code == 204
    assert (await client.get("/v1/courses")).json()["items"] == []
    assert (await client.get(f"/v1/courses/{ready_course['course_id']}")).status_code == 404


async def test_rebuild_creates_job(client, ready_course):
    resp = await client.post(
        f"/v1/courses/{ready_course['course_id']}/rebuild", json={"reason": "test", "from": "lessons"}
    )
    assert resp.status_code == 202
    job_id = resp.json()["job_id"]
    assert job_id.startswith("job_")


async def test_create_course_requires_valid_url(client):
    resp = await client.post("/v1/courses", json={"repo_url": "not a url"}, headers={"Idempotency-Key": "k1"})
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "REPO_NOT_FOUND"

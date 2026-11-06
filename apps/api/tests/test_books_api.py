"""书籍与 PDF API（T-BOOK-1 / T-PDF-1 的离线部分 / G2 降级）。"""

from __future__ import annotations

from repolearn.core.clock import utcnow
from repolearn.core.db import SessionMaker
from repolearn.core.ids import new_id
from repolearn.models import BookChapter, BookVersion


async def _make_book(course_id: str, *, status: str = "ready") -> str:
    import hashlib

    book_id = new_id("book")
    key = hashlib.sha256(f"{course_id}|standard|1".encode()).hexdigest()
    async with SessionMaker() as session:
        session.add(
            BookVersion(
                id=book_id,
                course_version_id=course_id,
                cache_key=key,
                preset="standard",
                template_version="1",
                title="测试书籍",
                status=status,
                word_count=120,
                chapter_count=1,
                quality={"chapters": 1},
                created_at=utcnow(),
            )
        )
        await session.flush()
        session.add(
            BookChapter(
                id=new_id("chapter"),
                book_version_id=book_id,
                key="overview",
                title="第一部分 · 宏观架构",
                order_index=0,
                blocks=[{"type": "md", "text": "## 1.1 走读\n\n这一节看 foo。"}],
                source_refs=[{"file": "pkg/mod.py", "line_start": 1, "line_end": 2}],
                word_count=120,
                created_at=utcnow(),
            )
        )
        await session.commit()
    return book_id


async def test_create_book_returns_job(client, ready_course):
    resp = await client.post(
        f"/v1/courses/{ready_course['course_id']}/books",
        json={"preset": "standard"},
        headers={"Idempotency-Key": "book-1"},
    )
    assert resp.status_code == 202, resp.text
    body = resp.json()
    assert body["book_id"].startswith("bok_")
    assert body["job_id"].startswith("job_")


async def test_create_book_is_idempotent(client, ready_course):
    """两种幂等是两件事，必须分别断言（§3.10 / §6.2）：

    * **请求级**（同 `Idempotency-Key`）→ 返回**逐字节相同**的首次响应（连 job_id 都一样），
      因为重放查的是快照，不是重新执行；
    * **内容级**（`book_versions.cache_key`）→ 换一个 Idempotency-Key 也命中，
      返回 `200 reused:true`，不新建 Job（T-BOOK-1）。
    """
    first = await client.post(
        f"/v1/courses/{ready_course['course_id']}/books",
        json={"preset": "standard"},
        headers={"Idempotency-Key": "book-2"},
    )
    replay = await client.post(
        f"/v1/courses/{ready_course['course_id']}/books",
        json={"preset": "standard"},
        headers={"Idempotency-Key": "book-2"},
    )
    assert first.status_code == 202
    assert replay.status_code == 200
    # 请求级重放：与首次响应完全一致（包括 job_id）
    assert replay.json() == first.json()

    # 内容级复用：新键、同内容 → reused，且不产生第二个 Job
    reused = await client.post(
        f"/v1/courses/{ready_course['course_id']}/books",
        json={"preset": "standard"},
        headers={"Idempotency-Key": "book-2-other"},
    )
    assert reused.status_code == 200
    assert reused.json()["reused"] is True
    assert reused.json()["book_id"] == first.json()["book_id"]
    assert reused.json()["job_id"] is None


async def test_idempotency_mismatch_on_same_key(client, ready_course):
    """同键异体 → 422（不静默返回首次结果，否则会掩盖调用方 bug）。"""
    await client.post(
        f"/v1/courses/{ready_course['course_id']}/books",
        json={"preset": "standard"},
        headers={"Idempotency-Key": "book-3"},
    )
    resp = await client.post(
        f"/v1/courses/{ready_course['course_id']}/books",
        json={"preset": "deep"},
        headers={"Idempotency-Key": "book-3"},
    )
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "IDEMPOTENCY_MISMATCH"


async def test_get_book_and_chapter(client, ready_course):
    book_id = await _make_book(ready_course["course_id"])
    detail = await client.get(f"/v1/books/{book_id}")
    assert detail.status_code == 200
    body = detail.json()
    assert body["chapter_count"] if "chapter_count" in body else body["chapters"][0]["key"] == "overview"
    assert body["toc"][0]["order"] == 0

    chapter = await client.get(f"/v1/books/{book_id}/chapters/overview")
    assert chapter.status_code == 200
    ch = chapter.json()
    assert ch["blocks"][0]["type"] == "md"
    assert ch["source_refs"][0]["file"] == "pkg/mod.py"


async def test_missing_book_chapter_is_404(client, ready_course):
    book_id = await _make_book(ready_course["course_id"])
    resp = await client.get(f"/v1/books/{book_id}/chapters/nope")
    assert resp.status_code == 404


async def test_pdf_status_before_export(client, ready_course):
    book_id = await _make_book(ready_course["course_id"])
    resp = await client.get(f"/v1/books/{book_id}/pdf")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "queued"
    assert body["pdf_url"] is None
    assert body["commit_sha"] == ready_course["sha"]


async def test_pdf_request_degrades_when_chromium_missing(client, ready_course, monkeypatch):
    """G2 失败时**不生成假 PDF**：直接标成 browser-print 并给打印视图地址。"""
    import repolearn.services.book_service as bs

    monkeypatch.setattr(bs, "chromium_available", lambda: False)
    book_id = await _make_book(ready_course["course_id"])
    resp = await client.post(f"/v1/books/{book_id}/pdf", json={"engine": "chromium"})
    assert resp.status_code == 202
    job_id = resp.json()["job_id"]
    assert job_id.startswith("job_")

    status_resp = await client.get(f"/v1/books/{book_id}/pdf")
    body = status_resp.json()
    assert body["engine"] == "browser-print"
    assert body["print_view_url"].endswith("?print=1")


async def test_pdf_requires_ready_book(client, ready_course):
    book_id = await _make_book(ready_course["course_id"], status="generating")
    resp = await client.post(f"/v1/books/{book_id}/pdf", json={"engine": "chromium"})
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "COURSE_NOT_READY"

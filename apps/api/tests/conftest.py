"""pytest 全局夹具（spec §8.1 分层测试策略）。

**关键约束：环境变量必须在导入 `repolearn` 之前设置。** `core/config.py` 的
`settings` 是模块级单例，导入之后再改 `os.environ` 不会生效——这正是"测试跑在
开发库上、把真实数据删了"这类事故的成因。conftest 在 pytest 里最先被导入，
因此这里是唯一正确的位置。
"""

from __future__ import annotations

import asyncio
import os
import tempfile
from pathlib import Path

_TMP = Path(tempfile.mkdtemp(prefix="repolearn-tests-"))
os.environ.setdefault("REPOLEARN_ENV", "test")
os.environ["REPOLEARN_DATABASE_URL"] = f"sqlite+aiosqlite:///{(_TMP / 'test.db').as_posix()}"
os.environ["REPOLEARN_CHECKPOINT_DB"] = str(_TMP / "langgraph.sqlite")
os.environ["REPOLEARN_OBJECT_ROOT"] = str(_TMP / "objects")
os.environ["REPOLEARN_SECRET_KEY"] = "dGVzdC1rZXktMzItYnl0ZXMtbG9uZy1mb3ItcmVwb2xlYXJuISE="
os.environ["REPOLEARN_INTERNAL_TOKEN"] = "test-internal-token"
os.environ["REPOLEARN_AGENT_RUNTIME"] = "template"
# 出站端点指向一个**几乎肯定没有进程**的本地端口（hardening spec §4.1 第 18 行）。
# 目的不是省事，而是让任何漏 mock 的出站调用**当场连接失败**，而不是悄悄打到真实
# GitHub —— 后者会让测试套件变成隐性的网络依赖，在 CI 里表现成"偶发红"。
os.environ.setdefault("REPOLEARN_GITHUB_API_BASE", "http://127.0.0.1:9911")
os.environ.setdefault("REPOLEARN_GITHUB_WEB_BASE", "http://127.0.0.1:9911")
os.environ["REPOLEARN_HEARTBEAT_SECONDS"] = "3"
os.environ["REPOLEARN_JOB_STALE_SECONDS"] = "30"

# 回环流量绝不走代理（`httpx` 只认环境变量，不认 Windows 注册表里的 `ProxyOverride`）。
# 没有这一行，"开发机装了 Clash/VPN"会让所有打 127.0.0.1 的用例变成 502
# —— 与产品代码无关的红灯最难排查。产品侧同样有 `providers/http.py::new_local_client`。
_LOOPBACK = "127.0.0.1,localhost,::1"
os.environ["NO_PROXY"] = f"{_LOOPBACK},{os.environ['NO_PROXY']}" if os.environ.get("NO_PROXY") else _LOOPBACK
os.environ["no_proxy"] = os.environ["NO_PROXY"]

import pytest  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402
from sqlalchemy import text  # noqa: E402

from repolearn.core.db import Base, SessionMaker, engine  # noqa: E402
from repolearn.models import ALL_MODELS  # noqa: E402,F401  —— 注册全部表


def _alembic_upgrade() -> None:
    """用 Alembic 建表而不是 `create_all`。

    这样测试本身就在验证迁移（T-DB-1 的前半段）：如果 `0001_initial.py` 漏了一张表，
    测试会因为缺表而失败，而不是"测试通过、部署时炸"。
    """
    from alembic import command
    from alembic.config import Config

    from repolearn.core.config import REPO_ROOT

    cfg = Config(str(REPO_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(REPO_ROOT / "apps" / "api" / "migrations"))
    command.upgrade(cfg, "head")


_alembic_upgrade()


@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture()
async def session():
    async with SessionMaker() as s:
        yield s


@pytest.fixture(autouse=True)
async def clean_db():
    """每个用例前清空全部业务表（保留 alembic_version）。

    关闭外键再删：否则 `user_progress` 对 `course_versions` 的 RESTRICT 会让清理失败，
    而失败信息看起来像是测试本身写错了。
    """
    yield
    async with engine.begin() as conn:
        await conn.execute(text("PRAGMA foreign_keys=OFF"))
        for table in reversed(Base.metadata.sorted_tables):
            if table.name == "alembic_version":
                continue
            await conn.execute(text(f'DELETE FROM "{table.name}"'))
        # FTS5 虚拟表**不进 `Base.metadata`**，所以上面的循环看不到它。不清的话
        # 索引行会跨用例泄漏，产生"单独跑绿、全量跑红"的经典幻觉（spec F18）。
        # `try/except` 是为了容忍"这次迁移没建表"（老 SQLite 上能力探测跳过建表）。
        try:
            await conn.execute(text("DELETE FROM course_search"))
        except Exception:  # noqa: BLE001 - 表不存在 = 没有行要清
            pass
        await conn.execute(text("PRAGMA foreign_keys=ON"))


@pytest.fixture()
def app():
    from repolearn.main import create_app

    return create_app()


@pytest.fixture()
async def client(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport,
        base_url="http://test",
        headers={
            "X-Internal-Token": os.environ["REPOLEARN_INTERNAL_TOKEN"],
            "X-CSRF-Token": "test-csrf",
            "Cookie": "rl_csrf=test-csrf",
        },
    ) as c:
        yield c


@pytest.fixture()
def tmp_root() -> Path:
    return _TMP


@pytest.fixture()
async def ready_course():
    """插入一门最小可用的 `ready` 课程，返回 (course_id, lesson_key, quiz_item_id)。

    不用 CLI 的 `seed-demo`：那个函数把整门演示课写死，测试若依赖它，改演示内容
    就会连带改测试。这里只造测试真正需要的形状（1 章 1 课 1 步 1 题）。
    """
    import hashlib

    from repolearn.core.clock import utcnow
    from repolearn.core.db import SessionMaker
    from repolearn.core.ids import new_id
    from repolearn.models import Commit, CourseVersion, Lesson, QuizItem, Repository, Step
    from repolearn.services.object_store import mirror_dir

    sha = "t" * 64
    base = mirror_dir(sha[:8])
    (base / "pkg").mkdir(parents=True, exist_ok=True)
    (base / "pkg" / "mod.py").write_text("def foo():\n    return 1\n\nclass Bar:\n    pass\n", encoding="utf-8")

    course_id = new_id("course_version")
    lesson_id = new_id("lesson")
    quiz_id = new_id("quiz")
    cache_key = hashlib.sha256(f"o/r|{sha}|1|zh".encode()).hexdigest()
    async with SessionMaker() as session:
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
                file_count=1,
                tarball_bytes=64,
                license_note="MIT",
                created_at=utcnow(),
            )
        )
        session.add(
            CourseVersion(
                id=course_id,
                repository_id=repo.id,
                commit_sha=sha,
                cache_key=cache_key,
                policy_version="1",
                language="zh",
                title="Fixture 课程",
                subtitle="测试用",
                summary_md="用于 API 测试的最小课程。",
                status="ready",
                sections=[
                    {"key": "overview", "title": "第一层", "minutes": 5, "lessons": [{"key": "1.1", "title": "走读", "minutes": 5}]}
                ],
                quality_report={"anchor_coverage": 0.9, "lesson_completeness": 1.0, "degraded": False, "anchor_confidence": "high"},
                warnings=[],
                blueprint={"repo_full_name": "owner/repo", "license": "MIT"},
                cover_palette="mint",
                lesson_count=1,
                total_minutes=5,
                visibility="public",
                created_at=utcnow(),
                updated_at=utcnow(),
                published_at=utcnow(),
            )
        )
        await session.flush()
        session.add(
            Lesson(
                id=lesson_id,
                course_version_id=course_id,
                section_key="overview",
                key="1.1",
                title="走读",
                goal="看懂 foo",
                minutes=5,
                order_index=0,
                status="ready",
                playback_meta={
                    "files": [{"path": "pkg/mod.py", "lang": "python", "line_count": 5}],
                    "trace_key": "trace_1.1",
                    "narration": {"segment_count": 1, "audio": None, "timing_source": "estimated"},
                },
                created_at=utcnow(),
            )
        )
        await session.flush()
        session.add(
            Step(
                id=new_id("step"),
                lesson_id=lesson_id,
                order_index=0,
                title="先看入口",
                duration_ms=10000,
                timing_source="estimated",
                focus_file="pkg/mod.py",
                focus_line_start=1,
                focus_line_end=2,
                segments=[
                    {
                        "id": "s0",
                        "text": "这里从入口开始。",
                        "start_ms": 0,
                        "end_ms": 10000,
                        "focus": {"file": "pkg/mod.py", "line_start": 1, "line_end": 2},
                    }
                ],
                board={"kind": "architecture", "mermaid": "flowchart LR\n  a[foo] --> b[Bar]"},
                code_notes=[{"file": "pkg/mod.py", "line": 1, "text": "定义 foo"}],
                certainty={},
                created_at=utcnow(),
            )
        )
        session.add(
            QuizItem(
                id=quiz_id,
                course_version_id=course_id,
                lesson_id=lesson_id,
                stem="foo 定义在哪一行？",
                choices=[{"id": "a", "text": "第 1 行"}, {"id": "b", "text": "第 3 行"}],
                answer_id="a",
                explanation_md="`def foo` 在第 1 行。",
                evidence=[{"file": "pkg/mod.py", "line_start": 1, "line_end": 1}],
                difficulty=1,
                kind="recall",
                created_at=utcnow(),
            )
        )
        await session.commit()
    return {"course_id": course_id, "lesson_key": "1.1", "quiz_item_id": quiz_id, "sha": sha}

"""模型层统一出口。

**导入顺序即注册顺序**，且 `Base.metadata` 只在这里被完整填充一次。迁移脚本
（`migrations/env.py`）与 `Base.metadata.create_all()` 都依赖"import 本模块"
这一件事——少导入一张表，建表就会静默少一张，而错误要到第一次写入时才暴露。

表数量门禁：`SPEC_TABLE_COUNT = 26`（spec §6.2 定稿）。测试会断言
`len(Base.metadata.tables) == SPEC_TABLE_COUNT`。
"""

from __future__ import annotations

from sqlalchemy import MetaData, Table

from repolearn.core.db import Base
from repolearn.models.ai_cache import AiCache
from repolearn.models.audio_asset import AudioAsset
from repolearn.models.book_chapter import BookChapter
from repolearn.models.book_version import BookVersion
from repolearn.models.commit import Commit
from repolearn.models.cost_ledger import CostLedger
from repolearn.models.course_version import CourseVersion
from repolearn.models.generation_lock import GenerationLock
from repolearn.models.idempotency_key import IdempotencyKey
from repolearn.models.job import Job
from repolearn.models.job_event import JobEvent
from repolearn.models.lesson import Lesson
from repolearn.models.llm_profile import LlmProfile
from repolearn.models.model_catalog import ModelCatalog
from repolearn.models.note import Note
from repolearn.models.pdf_export import PdfExport
from repolearn.models.question import Question
from repolearn.models.quiz_attempt import QuizAttempt
from repolearn.models.quiz_item import QuizItem
from repolearn.models.repository import Repository
from repolearn.models.setting_revision import SettingRevision
from repolearn.models.simulated_trace import SimulatedTrace
from repolearn.models.source_anchor import SourceAnchor
from repolearn.models.step import Step
from repolearn.models.user import User
from repolearn.models.user_progress import UserProgress

SPEC_TABLE_COUNT = 26

ALL_MODELS = (
    AiCache,
    AudioAsset,
    BookChapter,
    BookVersion,
    Commit,
    CostLedger,
    CourseVersion,
    GenerationLock,
    IdempotencyKey,
    Job,
    JobEvent,
    Lesson,
    LlmProfile,
    ModelCatalog,
    Note,
    PdfExport,
    Question,
    QuizAttempt,
    QuizItem,
    Repository,
    SettingRevision,
    SimulatedTrace,
    SourceAnchor,
    Step,
    User,
    UserProgress,
)


def table_names() -> list[str]:
    meta: MetaData = Base.metadata
    return sorted(t.name for t in meta.tables.values() if isinstance(t, Table))


def missing_tables() -> list[str]:
    return [m.__tablename__ for m in ALL_MODELS if m.__tablename__ not in Base.metadata.tables]


__all__ = [
    "ALL_MODELS",
    "SPEC_TABLE_COUNT",
    "AiCache",
    "AudioAsset",
    "BookChapter",
    "BookVersion",
    "Commit",
    "CostLedger",
    "CourseVersion",
    "GenerationLock",
    "IdempotencyKey",
    "Job",
    "JobEvent",
    "Lesson",
    "LlmProfile",
    "ModelCatalog",
    "Note",
    "PdfExport",
    "Question",
    "QuizAttempt",
    "QuizItem",
    "Repository",
    "SettingRevision",
    "SimulatedTrace",
    "SourceAnchor",
    "Step",
    "User",
    "UserProgress",
    "missing_tables",
    "table_names",
]

"""0001_initial —— 一次建全表（spec §6.2 的 26 张表 + 索引 + 唯一约束）。

由 `scripts/gen_migration.py` 从 ORM 元数据生成，**之后冻结**：任何结构变更都必须
新增迁移文件，不得修改本文件（T-DB-1 的 upgrade→downgrade→upgrade 往返依赖它
作为稳定基线）。
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None

#: JSON 在 SQLite 存 TEXT，在 PG 存 JSONB（spec §6.7）
JSON_T = sa.JSON().with_variant(JSONB(), "postgresql")


def upgrade() -> None:
    op.create_table(
        "ai_cache",
        sa.Column("key", sa.String(80), primary_key=True, nullable=False),
        sa.Column("response_json", JSON_T, nullable=False),
        sa.Column("tokens_in", sa.Integer(), nullable=False),
        sa.Column("tokens_out", sa.Integer(), nullable=False),
        sa.Column("model_id", sa.String(160), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("expires_at", sa.DateTime()),
    )

    op.create_table(
        "audio_assets",
        sa.Column("id", sa.String(40), primary_key=True, nullable=False),
        sa.Column("provider", sa.String(40), nullable=False),
        sa.Column("voice", sa.String(120), nullable=False),
        sa.Column("speed", sa.Float(), nullable=False),
        sa.Column("text_hash", sa.String(64), nullable=False),
        sa.Column("object_key", sa.String(300), nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=False),
        sa.Column("duration_source", sa.String(16), nullable=False),
        sa.Column("bytes", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("provider", "voice", "speed", "text_hash", name="ux_audio_cache_key"),
    )
    op.create_index("ix_audio_text_hash", "audio_assets", ["text_hash"])

    op.create_table(
        "cost_ledger",
        sa.Column("id", sa.String(40), primary_key=True, nullable=False),
        sa.Column("job_id", sa.String(40)),
        sa.Column("role", sa.String(20), nullable=False),
        sa.Column("provider", sa.String(40), nullable=False),
        sa.Column("model_id", sa.String(160), nullable=False),
        sa.Column("tokens_in", sa.Integer(), nullable=False),
        sa.Column("tokens_out", sa.Integer(), nullable=False),
        sa.Column("usd", sa.Float(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_cost_ledger_created", "cost_ledger", ["created_at"])
    op.create_index("ix_cost_ledger_job_id", "cost_ledger", ["job_id"])

    op.create_table(
        "generation_locks",
        sa.Column("cache_key", sa.String(80), primary_key=True, nullable=False),
        sa.Column("job_id", sa.String(40), nullable=False),
        sa.Column("acquired_at", sa.DateTime(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
    )

    op.create_table(
        "idempotency_keys",
        sa.Column("id", sa.String(40), primary_key=True, nullable=False),
        sa.Column("scope", sa.String(40), nullable=False),
        sa.Column("key", sa.String(120), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("response_snapshot", JSON_T, nullable=False),
        sa.Column("job_id", sa.String(40)),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("expires_at", sa.DateTime()),
        sa.UniqueConstraint("scope", "key", name="ux_idempotency_scope_key"),
    )
    op.create_index("ix_idempotency_expires", "idempotency_keys", ["expires_at"])

    op.create_table(
        "llm_profiles",
        sa.Column("id", sa.String(40), primary_key=True, nullable=False),
        sa.Column("label", sa.String(200), nullable=False),
        sa.Column("provider", sa.String(40), nullable=False),
        sa.Column("protocol", sa.String(40), nullable=False),
        sa.Column("base_url", sa.String(400)),
        sa.Column("api_key_ciphertext", sa.LargeBinary()),
        sa.Column("api_key_last4", sa.String(8), nullable=False),
        sa.Column("org", sa.String(120)),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("last_probe", JSON_T, nullable=False),
        sa.Column("roles", JSON_T, nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("rotated_at", sa.DateTime()),
    )

    op.create_table(
        "model_catalog",
        sa.Column("id", sa.String(40), primary_key=True, nullable=False),
        sa.Column("provider", sa.String(40), nullable=False),
        sa.Column("model_id", sa.String(160), nullable=False),
        sa.Column("display_name", sa.String(200), nullable=False),
        sa.Column("capabilities", JSON_T, nullable=False),
        sa.Column("context_window", sa.Integer(), nullable=False),
        sa.Column("price_in", sa.Float(), nullable=False),
        sa.Column("price_out", sa.Float(), nullable=False),
        sa.Column("probed_at", sa.DateTime()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("provider", "model_id", name="ux_model_catalog_provider_model"),
    )

    op.create_table(
        "repositories",
        sa.Column("id", sa.String(40), primary_key=True, nullable=False),
        sa.Column("full_name", sa.String(200), nullable=False),
        sa.Column("owner", sa.String(120), nullable=False),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("description", sa.String(1200)),
        sa.Column("stars", sa.Integer(), nullable=False),
        sa.Column("license_spdx", sa.String(80)),
        sa.Column("primary_language", sa.String(60)),
        sa.Column("default_branch", sa.String(120), nullable=False),
        sa.Column("html_url", sa.String(400)),
        sa.Column("is_public", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime()),
        sa.UniqueConstraint("full_name", name="ux_repositories_full_name"),
    )

    op.create_table(
        "setting_revisions",
        sa.Column("id", sa.String(40), primary_key=True, nullable=False),
        sa.Column("rev", sa.Integer(), nullable=False),
        sa.Column("summary", sa.String(300), nullable=False),
        sa.Column("changes", JSON_T, nullable=False),
        sa.Column("payload", JSON_T, nullable=False),
        sa.Column("author", sa.String(60), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("rev", name="ux_setting_revisions_rev"),
    )

    op.create_table(
        "users",
        sa.Column("id", sa.String(40), primary_key=True, nullable=False),
        sa.Column("handle", sa.String(64), nullable=False),
        sa.Column("display_name", sa.String(200), nullable=False),
        sa.Column("is_local", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("handle", name="ux_users_handle"),
    )

    op.create_table(
        "commits",
        sa.Column("id", sa.String(40), primary_key=True, nullable=False),
        sa.Column("repository_id", sa.String(40), sa.ForeignKey("repositories.id", ondelete="CASCADE"), nullable=False),
        sa.Column("sha", sa.String(64), nullable=False),
        sa.Column("committed_at", sa.DateTime()),
        sa.Column("file_count", sa.Integer(), nullable=False),
        sa.Column("tarball_bytes", sa.Integer(), nullable=False),
        sa.Column("license_note", sa.String(400)),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("repository_id", "sha", name="ux_commits_repo_sha"),
    )
    op.create_index("ix_commits_repository_id", "commits", ["repository_id"])
    op.create_index("ix_commits_sha", "commits", ["sha"])

    op.create_table(
        "course_versions",
        sa.Column("id", sa.String(40), primary_key=True, nullable=False),
        sa.Column("repository_id", sa.String(40), sa.ForeignKey("repositories.id", ondelete="CASCADE"), nullable=False),
        sa.Column("commit_sha", sa.String(64), nullable=False),
        sa.Column("cache_key", sa.String(80), nullable=False),
        sa.Column("policy_version", sa.String(40), nullable=False),
        sa.Column("language", sa.String(10), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("subtitle", sa.String(400)),
        sa.Column("summary_md", sa.Text()),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("sections", JSON_T, nullable=False),
        sa.Column("quality_report", JSON_T, nullable=False),
        sa.Column("warnings", JSON_T, nullable=False),
        sa.Column("blueprint", JSON_T, nullable=False),
        sa.Column("cover_palette", sa.String(20), nullable=False),
        sa.Column("lesson_count", sa.Integer(), nullable=False),
        sa.Column("total_minutes", sa.Integer(), nullable=False),
        sa.Column("owner_user_id", sa.String(40)),
        sa.Column("visibility", sa.String(12), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime()),
        sa.Column("published_at", sa.DateTime()),
        sa.Column("deleted_at", sa.DateTime()),
    )
    op.create_index("ix_course_versions_cache_key", "course_versions", ["cache_key"], unique=True)
    op.create_index("ix_course_versions_repo_created", "course_versions", ["repository_id", "created_at"])
    op.create_index("ix_course_versions_status_created", "course_versions", ["status", "created_at"])

    op.create_table(
        "book_versions",
        sa.Column("id", sa.String(40), primary_key=True, nullable=False),
        sa.Column("course_version_id", sa.String(40), sa.ForeignKey("course_versions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("cache_key", sa.String(80), nullable=False),
        sa.Column("preset", sa.String(16), nullable=False),
        sa.Column("template_version", sa.String(20), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("subtitle", sa.Text()),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("word_count", sa.Integer(), nullable=False),
        sa.Column("chapter_count", sa.Integer(), nullable=False),
        sa.Column("quality", JSON_T, nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("cache_key", name="ux_book_versions_cache_key"),
    )
    op.create_index("ix_book_versions_course_version_id", "book_versions", ["course_version_id"])

    op.create_table(
        "lessons",
        sa.Column("id", sa.String(40), primary_key=True, nullable=False),
        sa.Column("course_version_id", sa.String(40), sa.ForeignKey("course_versions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("section_key", sa.String(20), nullable=False),
        sa.Column("key", sa.String(40), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("goal", sa.Text()),
        sa.Column("minutes", sa.Integer(), nullable=False),
        sa.Column("order_index", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(12), nullable=False),
        sa.Column("playback_meta", JSON_T, nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("course_version_id", "key", name="ux_lessons_course_key"),
    )
    op.create_index("ix_lessons_course_order", "lessons", ["course_version_id", "order_index"])

    op.create_table(
        "user_progress",
        sa.Column("id", sa.String(40), primary_key=True, nullable=False),
        sa.Column("user_id", sa.String(40), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("course_version_id", sa.String(40), sa.ForeignKey("course_versions.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("current_lesson_key", sa.String(40)),
        sa.Column("current_step_index", sa.Integer(), nullable=False),
        sa.Column("position_ms", sa.Integer(), nullable=False),
        sa.Column("percent", sa.Integer(), nullable=False),
        sa.Column("completed_at", sa.DateTime()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime()),
        sa.UniqueConstraint("user_id", "course_version_id", name="ux_progress_user_course"),
    )
    op.create_index("ix_progress_user_updated", "user_progress", ["user_id", "updated_at"])

    op.create_table(
        "book_chapters",
        sa.Column("id", sa.String(40), primary_key=True, nullable=False),
        sa.Column("book_version_id", sa.String(40), sa.ForeignKey("book_versions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("key", sa.String(40), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("order_index", sa.Integer(), nullable=False),
        sa.Column("blocks", JSON_T, nullable=False),
        sa.Column("source_refs", JSON_T, nullable=False),
        sa.Column("word_count", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("book_version_id", "key", name="ux_book_chapter_key"),
    )
    op.create_index("ix_book_chapters_book_order", "book_chapters", ["book_version_id", "order_index"])

    op.create_table(
        "jobs",
        sa.Column("id", sa.String(40), primary_key=True, nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column("payload", JSON_T, nullable=False),
        sa.Column("course_version_id", sa.String(40), sa.ForeignKey("course_versions.id", ondelete="CASCADE")),
        sa.Column("book_version_id", sa.String(40), sa.ForeignKey("book_versions.id", ondelete="CASCADE")),
        sa.Column("cache_key", sa.String(80)),
        sa.Column("worker_id", sa.String(60)),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("progress", sa.Integer(), nullable=False),
        sa.Column("node", sa.String(40)),
        sa.Column("message", sa.String(500)),
        sa.Column("error", JSON_T, nullable=False),
        sa.Column("heartbeat_at", sa.DateTime()),
        sa.Column("run_after", sa.DateTime()),
        sa.Column("started_at", sa.DateTime()),
        sa.Column("finished_at", sa.DateTime()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_jobs_cache_key", "jobs", ["cache_key"])
    op.create_index("ix_jobs_status_priority_created", "jobs", ["status", "priority", "created_at"])

    op.create_table(
        "pdf_exports",
        sa.Column("id", sa.String(40), primary_key=True, nullable=False),
        sa.Column("book_version_id", sa.String(40), sa.ForeignKey("book_versions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("cache_key", sa.String(80), nullable=False),
        sa.Column("engine", sa.String(20), nullable=False),
        sa.Column("object_key", sa.String(300)),
        sa.Column("pages", sa.Integer(), nullable=False),
        sa.Column("bytes", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("error", JSON_T, nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("finished_at", sa.DateTime()),
        sa.UniqueConstraint("cache_key", name="ux_pdf_exports_cache_key"),
    )
    op.create_index("ix_pdf_exports_book_version_id", "pdf_exports", ["book_version_id"])

    op.create_table(
        "questions",
        sa.Column("id", sa.String(40), primary_key=True, nullable=False),
        sa.Column("user_id", sa.String(40), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("course_version_id", sa.String(40), sa.ForeignKey("course_versions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("lesson_id", sa.String(40), sa.ForeignKey("lessons.id", ondelete="CASCADE")),
        sa.Column("file", sa.String(400), nullable=False),
        sa.Column("line_start", sa.Integer(), nullable=False),
        sa.Column("line_end", sa.Integer(), nullable=False),
        sa.Column("layer", sa.String(20), nullable=False),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("answer_md", sa.Text(), nullable=False),
        sa.Column("evidence", JSON_T, nullable=False),
        sa.Column("runtime", sa.String(12), nullable=False),
        sa.Column("tokens_in", sa.Integer(), nullable=False),
        sa.Column("tokens_out", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("deleted_at", sa.DateTime()),
    )
    op.create_index("ix_questions_course_lesson", "questions", ["course_version_id", "lesson_id"])

    op.create_table(
        "quiz_items",
        sa.Column("id", sa.String(40), primary_key=True, nullable=False),
        sa.Column("course_version_id", sa.String(40), sa.ForeignKey("course_versions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("lesson_id", sa.String(40), sa.ForeignKey("lessons.id", ondelete="CASCADE")),
        sa.Column("stem", sa.Text(), nullable=False),
        sa.Column("choices", JSON_T, nullable=False),
        sa.Column("answer_id", sa.String(20), nullable=False),
        sa.Column("explanation_md", sa.Text(), nullable=False),
        sa.Column("evidence", JSON_T, nullable=False),
        sa.Column("difficulty", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_quiz_course_lesson", "quiz_items", ["course_version_id", "lesson_id"])

    op.create_table(
        "simulated_traces",
        sa.Column("id", sa.String(40), primary_key=True, nullable=False),
        sa.Column("course_version_id", sa.String(40), sa.ForeignKey("course_versions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("lesson_id", sa.String(40), sa.ForeignKey("lessons.id", ondelete="CASCADE")),
        sa.Column("key", sa.String(40), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("entry_anchor_id", sa.String(40)),
        sa.Column("steps", JSON_T, nullable=False),
        sa.Column("certainty_summary", JSON_T, nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_traces_course_key", "simulated_traces", ["course_version_id", "key"])

    op.create_table(
        "source_anchors",
        sa.Column("id", sa.String(40), primary_key=True, nullable=False),
        sa.Column("course_version_id", sa.String(40), sa.ForeignKey("course_versions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("lesson_id", sa.String(40), sa.ForeignKey("lessons.id", ondelete="CASCADE")),
        sa.Column("file", sa.String(400), nullable=False),
        sa.Column("symbol", sa.String(200)),
        sa.Column("line_start", sa.Integer(), nullable=False),
        sa.Column("line_end", sa.Integer(), nullable=False),
        sa.Column("commit_sha", sa.String(64), nullable=False),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("snippet_hash", sa.String(64)),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_anchors_course_file", "source_anchors", ["course_version_id", "file"])
    op.create_index("ix_anchors_lesson", "source_anchors", ["lesson_id"])

    op.create_table(
        "steps",
        sa.Column("id", sa.String(40), primary_key=True, nullable=False),
        sa.Column("lesson_id", sa.String(40), sa.ForeignKey("lessons.id", ondelete="CASCADE"), nullable=False),
        sa.Column("order_index", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=False),
        sa.Column("timing_source", sa.String(12), nullable=False),
        sa.Column("audio_asset_id", sa.String(40)),
        sa.Column("focus_file", sa.String(400)),
        sa.Column("focus_line_start", sa.Integer()),
        sa.Column("focus_line_end", sa.Integer()),
        sa.Column("segments", JSON_T, nullable=False),
        sa.Column("board", JSON_T, nullable=False),
        sa.Column("code_notes", JSON_T, nullable=False),
        sa.Column("certainty", JSON_T, nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("lesson_id", "order_index", name="ux_steps_lesson_order"),
    )
    op.create_index("ix_steps_lesson_order", "steps", ["lesson_id", "order_index"])

    op.create_table(
        "job_events",
        sa.Column("id", sa.String(40), primary_key=True, nullable=False),
        sa.Column("job_id", sa.String(40), sa.ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("type", sa.String(40), nullable=False),
        sa.Column("data", JSON_T, nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("job_id", "seq", name="ux_job_events_job_seq"),
    )
    op.create_index("ix_job_events_job_id", "job_events", ["job_id"])

    op.create_table(
        "notes",
        sa.Column("id", sa.String(40), primary_key=True, nullable=False),
        sa.Column("user_id", sa.String(40), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("course_version_id", sa.String(40), sa.ForeignKey("course_versions.id", ondelete="CASCADE")),
        sa.Column("lesson_id", sa.String(40), sa.ForeignKey("lessons.id", ondelete="CASCADE")),
        sa.Column("anchor_id", sa.String(40), sa.ForeignKey("source_anchors.id", ondelete="SET NULL")),
        sa.Column("body_md", sa.String(8000), nullable=False),
        sa.Column("tags", JSON_T, nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime()),
        sa.Column("deleted_at", sa.DateTime()),
    )
    op.create_index("ix_notes_user_course", "notes", ["user_id", "course_version_id"])

    op.create_table(
        "quiz_attempts",
        sa.Column("id", sa.String(40), primary_key=True, nullable=False),
        sa.Column("user_id", sa.String(40), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("quiz_item_id", sa.String(40), sa.ForeignKey("quiz_items.id", ondelete="CASCADE"), nullable=False),
        sa.Column("course_version_id", sa.String(40), sa.ForeignKey("course_versions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("choice_id", sa.String(20), nullable=False),
        sa.Column("correct", sa.Boolean(), nullable=False),
        sa.Column("submitted_at", sa.DateTime()),
        sa.UniqueConstraint("user_id", "quiz_item_id", name="ux_quiz_attempt_user_item"),
    )
    op.create_index("ix_quiz_attempt_course", "quiz_attempts", ["course_version_id", "submitted_at"])

    # 部分唯一索引：不能同时存在两个 active profile（T-DB-3）。
    op.execute("CREATE UNIQUE INDEX ux_llm_profiles_active ON llm_profiles (active) WHERE active = 1")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ux_llm_profiles_active")
    op.drop_index("ix_quiz_attempt_course", table_name="quiz_attempts")
    op.drop_table("quiz_attempts")
    op.drop_index("ix_notes_user_course", table_name="notes")
    op.drop_table("notes")
    op.drop_index("ix_job_events_job_id", table_name="job_events")
    op.drop_table("job_events")
    op.drop_index("ix_steps_lesson_order", table_name="steps")
    op.drop_table("steps")
    op.drop_index("ix_anchors_course_file", table_name="source_anchors")
    op.drop_index("ix_anchors_lesson", table_name="source_anchors")
    op.drop_table("source_anchors")
    op.drop_index("ix_traces_course_key", table_name="simulated_traces")
    op.drop_table("simulated_traces")
    op.drop_index("ix_quiz_course_lesson", table_name="quiz_items")
    op.drop_table("quiz_items")
    op.drop_index("ix_questions_course_lesson", table_name="questions")
    op.drop_table("questions")
    op.drop_index("ix_pdf_exports_book_version_id", table_name="pdf_exports")
    op.drop_table("pdf_exports")
    op.drop_index("ix_jobs_cache_key", table_name="jobs")
    op.drop_index("ix_jobs_status_priority_created", table_name="jobs")
    op.drop_table("jobs")
    op.drop_index("ix_book_chapters_book_order", table_name="book_chapters")
    op.drop_table("book_chapters")
    op.drop_index("ix_progress_user_updated", table_name="user_progress")
    op.drop_table("user_progress")
    op.drop_index("ix_lessons_course_order", table_name="lessons")
    op.drop_table("lessons")
    op.drop_index("ix_book_versions_course_version_id", table_name="book_versions")
    op.drop_table("book_versions")
    op.drop_index("ix_course_versions_cache_key", table_name="course_versions")
    op.drop_index("ix_course_versions_repo_created", table_name="course_versions")
    op.drop_index("ix_course_versions_status_created", table_name="course_versions")
    op.drop_table("course_versions")
    op.drop_index("ix_commits_repository_id", table_name="commits")
    op.drop_index("ix_commits_sha", table_name="commits")
    op.drop_table("commits")
    op.drop_table("users")
    op.drop_table("setting_revisions")
    op.drop_table("repositories")
    op.drop_table("model_catalog")
    op.drop_table("llm_profiles")
    op.drop_index("ix_idempotency_expires", table_name="idempotency_keys")
    op.drop_table("idempotency_keys")
    op.drop_table("generation_locks")
    op.drop_index("ix_cost_ledger_created", table_name="cost_ledger")
    op.drop_index("ix_cost_ledger_job_id", table_name="cost_ledger")
    op.drop_table("cost_ledger")
    op.drop_index("ix_audio_text_hash", table_name="audio_assets")
    op.drop_table("audio_assets")
    op.drop_table("ai_cache")

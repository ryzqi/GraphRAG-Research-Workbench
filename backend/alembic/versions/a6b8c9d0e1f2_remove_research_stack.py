"""移除 research backend 实现相关持久化结构

Revision ID: a6b8c9d0e1f2
Revises: f3a2c1d4e5b6
Create Date: 2026-03-25 16:30:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# Alembic 修订标识。
revision = "a6b8c9d0e1f2"
down_revision = "f3a2c1d4e5b6"
branch_labels = None
depends_on = None

RESEARCH_SESSIONS_BACKUP_TABLE = "migration_backup_research_sessions"
RESEARCH_ARTIFACTS_BACKUP_TABLE = "migration_backup_research_artifacts"
RESEARCH_EVENTS_BACKUP_TABLE = "migration_backup_research_events"
RESEARCH_REPORTS_BACKUP_TABLE = "migration_backup_research_reports"


def _replace_agent_run_type_enum(values: tuple[str, ...], temp_type_name: str) -> None:
    bind = op.get_bind()
    replacement = postgresql.ENUM(*values, name=temp_type_name)
    replacement.create(bind, checkfirst=True)

    op.execute(
        sa.text(
            f"ALTER TABLE agent_runs "
            f"ALTER COLUMN run_type TYPE {temp_type_name} "
            f"USING run_type::text::{temp_type_name}"
        )
    )

    old_enum = postgresql.ENUM(name="agent_run_type")
    old_enum.drop(bind, checkfirst=True)
    op.execute(sa.text(f"ALTER TYPE {temp_type_name} RENAME TO agent_run_type"))


def _table_exists(table_name: str) -> bool:
    bind = op.get_bind()
    exists = bind.execute(
        sa.text("SELECT to_regclass(:table_name) IS NOT NULL"),
        {"table_name": f"public.{table_name}"},
    ).scalar()
    return bool(exists)


def _backup_research_history() -> None:
    if _table_exists("research_sessions") and not _table_exists(RESEARCH_SESSIONS_BACKUP_TABLE):
        op.execute(
            sa.text(
                f"""
                CREATE TABLE {RESEARCH_SESSIONS_BACKUP_TABLE} AS
                SELECT
                    id,
                    thread_id,
                    question,
                    selected_kb_ids,
                    allow_external,
                    status::text AS status_text,
                    metrics,
                    error_message,
                    trace_id,
                    last_event_sequence,
                    last_resume_idempotency_key,
                    last_resume_response,
                    legacy_run_id,
                    created_at,
                    started_at,
                    finished_at,
                    updated_at
                FROM research_sessions
                """
            )
        )

    if _table_exists("research_artifacts") and not _table_exists(RESEARCH_ARTIFACTS_BACKUP_TABLE):
        op.execute(
            sa.text(
                f"""
                CREATE TABLE {RESEARCH_ARTIFACTS_BACKUP_TABLE} AS
                SELECT
                    id,
                    session_id,
                    artifact_key,
                    content_text,
                    content_json,
                    created_at,
                    updated_at
                FROM research_artifacts
                """
            )
        )

    if _table_exists("research_events") and not _table_exists(RESEARCH_EVENTS_BACKUP_TABLE):
        op.execute(
            sa.text(
                f"""
                CREATE TABLE {RESEARCH_EVENTS_BACKUP_TABLE} AS
                SELECT
                    id,
                    session_id,
                    event_id,
                    sequence,
                    event_type,
                    payload,
                    trace_id,
                    idempotency_key,
                    created_at
                FROM research_events
                """
            )
        )

    if (
        _table_exists("research_reports")
        and _table_exists("research_sessions")
        and not _table_exists(RESEARCH_REPORTS_BACKUP_TABLE)
    ):
        op.execute(
            sa.text(
                f"""
                CREATE TABLE {RESEARCH_REPORTS_BACKUP_TABLE} AS
                SELECT
                    rr.id,
                    rs.id AS session_id,
                    rr.content_md,
                    rr.citations,
                    rr.created_at
                FROM research_reports AS rr
                LEFT JOIN research_sessions AS rs
                    ON rs.legacy_run_id = rr.run_id
                """
            )
        )


def upgrade() -> None:
    bind = op.get_bind()

    _backup_research_history()

    op.execute(
        sa.text(
            "DELETE FROM export_jobs "
            "WHERE run_id IN (SELECT id FROM agent_runs WHERE run_type = 'research')"
        )
    )
    op.execute(sa.text("DELETE FROM agent_runs WHERE run_type = 'research'"))

    op.drop_index(op.f("ix_research_reports_run_id"), table_name="research_reports")
    op.drop_table("research_reports")

    op.drop_index(op.f("ix_research_events_trace_id"), table_name="research_events")
    op.drop_index(op.f("ix_research_events_session_id"), table_name="research_events")
    op.drop_table("research_events")

    op.drop_index(op.f("ix_research_artifacts_session_id"), table_name="research_artifacts")
    op.drop_table("research_artifacts")

    op.drop_index(
        op.f("ix_research_sessions_trace_id"),
        table_name="research_sessions",
    )
    op.drop_index(
        op.f("ix_research_sessions_legacy_run_id"),
        table_name="research_sessions",
    )
    op.drop_table("research_sessions")

    research_session_status = postgresql.ENUM(name="research_session_status")
    research_session_status.drop(bind, checkfirst=True)

    _replace_agent_run_type_enum(
        ("kb_answer", "general_answer"),
        "agent_run_type_without_research",
    )


def downgrade() -> None:
    bind = op.get_bind()

    _replace_agent_run_type_enum(
        ("kb_answer", "general_answer", "research"),
        "agent_run_type_with_research",
    )

    research_session_status = postgresql.ENUM(
        "created",
        "queued",
        "running",
        "interrupted",
        "resumed",
        "final",
        "failed",
        "canceled",
        "timed_out",
        name="research_session_status",
        create_type=False,
    )
    research_session_status.create(bind, checkfirst=True)

    op.create_table(
        "research_sessions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("thread_id", sa.String(length=128), nullable=False),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("selected_kb_ids", postgresql.ARRAY(sa.Uuid()), nullable=True),
        sa.Column("allow_external", sa.Boolean(), nullable=False),
        sa.Column(
            "mode",
            sa.Enum("single_agent", "multi_agent", name="agent_mode", create_type=False),
            nullable=False,
        ),
        sa.Column("status", research_session_status, nullable=False),
        sa.Column("stage_summaries", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("metrics", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("final_output", sa.Text(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("trace_id", sa.String(length=128), nullable=True),
        sa.Column("last_event_sequence", sa.Integer(), server_default="0", nullable=False),
        sa.Column("last_resume_idempotency_key", sa.String(length=128), nullable=True),
        sa.Column("last_resume_response", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("legacy_run_id", sa.Uuid(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("thread_id"),
    )
    op.create_index(
        op.f("ix_research_sessions_legacy_run_id"),
        "research_sessions",
        ["legacy_run_id"],
        unique=True,
    )
    op.create_index(
        op.f("ix_research_sessions_trace_id"),
        "research_sessions",
        ["trace_id"],
        unique=False,
    )

    op.create_table(
        "research_artifacts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("session_id", sa.Uuid(), nullable=False),
        sa.Column("artifact_key", sa.String(length=64), nullable=False),
        sa.Column("content_text", sa.Text(), nullable=True),
        sa.Column("content_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["session_id"], ["research_sessions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "session_id",
            "artifact_key",
            name="uq_research_artifacts_session_key",
        ),
    )
    op.create_index(
        op.f("ix_research_artifacts_session_id"),
        "research_artifacts",
        ["session_id"],
        unique=False,
    )

    op.create_table(
        "research_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("session_id", sa.Uuid(), nullable=False),
        sa.Column("event_id", sa.String(length=128), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("trace_id", sa.String(length=128), nullable=True),
        sa.Column("idempotency_key", sa.String(length=128), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["session_id"], ["research_sessions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "session_id",
            "event_id",
            name="uq_research_events_session_event_id",
        ),
        sa.UniqueConstraint(
            "session_id",
            "sequence",
            name="uq_research_events_session_sequence",
        ),
    )
    op.create_index(
        op.f("ix_research_events_session_id"),
        "research_events",
        ["session_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_research_events_trace_id"),
        "research_events",
        ["trace_id"],
        unique=False,
    )

    op.create_table(
        "research_reports",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("content_md", sa.Text(), nullable=False),
        sa.Column("citations", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["run_id"], ["agent_runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_research_reports_run_id"),
        "research_reports",
        ["run_id"],
        unique=True,
    )

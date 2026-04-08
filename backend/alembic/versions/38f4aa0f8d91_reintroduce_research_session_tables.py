"""reintroduce research session tables

Revision ID: 38f4aa0f8d91
Revises: a6b8c9d0e1f2
Create Date: 2026-03-29 14:20:20.497530

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# Alembic 修订标识。
revision: str = '38f4aa0f8d91'
down_revision: Union[str, Sequence[str], None] = 'a6b8c9d0e1f2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

RESEARCH_SESSIONS_BACKUP_TABLE = "migration_backup_research_sessions"
RESEARCH_ARTIFACTS_BACKUP_TABLE = "migration_backup_research_artifacts"
RESEARCH_EVENTS_BACKUP_TABLE = "migration_backup_research_events"
RESEARCH_REPORTS_BACKUP_TABLE = "migration_backup_research_reports"


def _table_exists(table_name: str) -> bool:
    bind = op.get_bind()
    exists = bind.execute(
        sa.text("SELECT to_regclass(:table_name) IS NOT NULL"),
        {"table_name": f"public.{table_name}"},
    ).scalar()
    return bool(exists)


def _report_json_uuid_sql(column_name: str) -> str:
    return (
        "("
        f"substr(md5({column_name}::text || '__report_json'), 1, 8) || '-' || "
        f"substr(md5({column_name}::text || '__report_json'), 9, 4) || '-' || "
        f"substr(md5({column_name}::text || '__report_json'), 13, 4) || '-' || "
        f"substr(md5({column_name}::text || '__report_json'), 17, 4) || '-' || "
        f"substr(md5({column_name}::text || '__report_json'), 21, 12)"
        ")::uuid"
    )


def _restore_research_sessions_from_backup() -> None:
    if not _table_exists(RESEARCH_SESSIONS_BACKUP_TABLE):
        return

    op.execute(
        sa.text(
            f"""
            INSERT INTO research_sessions (
                id,
                thread_id,
                question,
                selected_kb_ids,
                allow_external,
                status,
                planner_phase,
                runtime_phase,
                finalizer_phase,
                trace_id,
                last_event_sequence,
                last_resume_idempotency_key,
                last_resume_response,
                metrics,
                error_message,
                created_at,
                started_at,
                finished_at,
                updated_at
            )
            SELECT
                id,
                thread_id,
                question,
                selected_kb_ids,
                allow_external,
                CASE status_text
                    WHEN 'interrupted' THEN 'running'
                    WHEN 'resumed' THEN 'running'
                    ELSE status_text
                END::research_session_status,
                NULL,
                NULL,
                NULL,
                trace_id,
                COALESCE(last_event_sequence, 0),
                last_resume_idempotency_key,
                last_resume_response,
                metrics,
                error_message,
                created_at,
                started_at,
                finished_at,
                updated_at
            FROM {RESEARCH_SESSIONS_BACKUP_TABLE}
            ON CONFLICT DO NOTHING
            """
        )
    )


def _restore_research_artifacts_from_backup() -> None:
    if not _table_exists(RESEARCH_ARTIFACTS_BACKUP_TABLE):
        return

    op.execute(
        sa.text(
            f"""
            INSERT INTO research_artifacts (
                id,
                session_id,
                artifact_key,
                content_text,
                content_json,
                source_type,
                source_provider,
                retrieval_method,
                origin_url,
                created_at,
                updated_at
            )
            SELECT
                id,
                session_id,
                artifact_key,
                content_text,
                content_json,
                NULL,
                NULL,
                NULL,
                NULL,
                created_at,
                updated_at
            FROM {RESEARCH_ARTIFACTS_BACKUP_TABLE}
            ON CONFLICT DO NOTHING
            """
        )
    )


def _restore_research_events_from_backup() -> None:
    if not _table_exists(RESEARCH_EVENTS_BACKUP_TABLE):
        return

    op.execute(
        sa.text(
            f"""
            INSERT INTO research_events (
                id,
                session_id,
                event_id,
                sequence,
                event_type,
                phase,
                namespace,
                payload,
                trace_id,
                idempotency_key,
                created_at
            )
            SELECT
                id,
                session_id,
                event_id,
                sequence,
                event_type,
                'legacy',
                'main',
                payload,
                trace_id,
                idempotency_key,
                created_at
            FROM {RESEARCH_EVENTS_BACKUP_TABLE}
            ON CONFLICT DO NOTHING
            """
        )
    )


def _restore_research_reports_from_backup() -> None:
    if not _table_exists(RESEARCH_REPORTS_BACKUP_TABLE):
        return

    op.execute(
        sa.text(
            f"""
            INSERT INTO research_artifacts (
                id,
                session_id,
                artifact_key,
                content_text,
                content_json,
                source_type,
                source_provider,
                retrieval_method,
                origin_url,
                created_at,
                updated_at
            )
            SELECT
                id,
                session_id,
                'report_md',
                content_md,
                NULL,
                NULL,
                NULL,
                NULL,
                NULL,
                created_at,
                created_at
            FROM {RESEARCH_REPORTS_BACKUP_TABLE}
            WHERE session_id IS NOT NULL
            ON CONFLICT DO NOTHING
            """
        )
    )
    op.execute(
        sa.text(
            f"""
            INSERT INTO research_artifacts (
                id,
                session_id,
                artifact_key,
                content_text,
                content_json,
                source_type,
                source_provider,
                retrieval_method,
                origin_url,
                created_at,
                updated_at
            )
            SELECT
                {_report_json_uuid_sql('id')},
                session_id,
                'report_json',
                NULL,
                jsonb_build_object(
                    'legacy_report', true,
                    'report_md', content_md,
                    'citations', COALESCE(citations, '[]'::jsonb),
                    'claim_map', '[]'::jsonb,
                    'coverage_matrix', jsonb_build_object(
                        'provider_counts', '{{}}'::jsonb,
                        'missing_providers', '[]'::jsonb
                    ),
                    'conflicts', '[]'::jsonb,
                    'source_ledger', '[]'::jsonb
                ),
                NULL,
                NULL,
                NULL,
                NULL,
                created_at,
                created_at
            FROM {RESEARCH_REPORTS_BACKUP_TABLE}
            WHERE session_id IS NOT NULL
            ON CONFLICT DO NOTHING
            """
        )
    )


def _drop_backup_tables() -> None:
    for table_name in (
        RESEARCH_REPORTS_BACKUP_TABLE,
        RESEARCH_EVENTS_BACKUP_TABLE,
        RESEARCH_ARTIFACTS_BACKUP_TABLE,
        RESEARCH_SESSIONS_BACKUP_TABLE,
    ):
        if _table_exists(table_name):
            op.execute(sa.text(f"DROP TABLE {table_name}"))


def upgrade() -> None:
    """升级数据库结构。"""
    bind = op.get_bind()
    research_session_status = postgresql.ENUM(
        "created",
        "planning",
        "awaiting_confirmation",
        "queued",
        "running",
        "interrupted",
        "resuming",
        "finalizing",
        "final",
        "failed",
        "canceled",
        "timed_out",
        name="research_session_status",
        create_type=False,
    )
    research_session_status.create(bind, checkfirst=True)

    # ### commands auto generated by Alembic - please adjust! ###
    op.create_table('research_sessions',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('thread_id', sa.String(length=128), nullable=False),
    sa.Column('question', sa.Text(), nullable=False),
    sa.Column('selected_kb_ids', postgresql.ARRAY(sa.Uuid()), nullable=True),
    sa.Column('allow_external', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('status', research_session_status, server_default='created', nullable=False),
    sa.Column('planner_phase', sa.String(length=64), nullable=True),
    sa.Column('runtime_phase', sa.String(length=64), nullable=True),
    sa.Column('finalizer_phase', sa.String(length=64), nullable=True),
    sa.Column('trace_id', sa.String(length=128), nullable=True),
    sa.Column('last_event_sequence', sa.Integer(), server_default='0', nullable=False),
    sa.Column('last_resume_idempotency_key', sa.String(length=128), nullable=True),
    sa.Column('last_resume_response', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('metrics', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('error_message', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('thread_id')
    )
    op.create_index(op.f('ix_research_sessions_status'), 'research_sessions', ['status'], unique=False)
    op.create_index(op.f('ix_research_sessions_trace_id'), 'research_sessions', ['trace_id'], unique=False)
    op.create_table('research_artifacts',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('session_id', sa.Uuid(), nullable=False),
    sa.Column('artifact_key', sa.String(length=64), nullable=False),
    sa.Column('content_text', sa.Text(), nullable=True),
    sa.Column('content_json', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('source_type', sa.String(length=32), nullable=True),
    sa.Column('source_provider', sa.String(length=64), nullable=True),
    sa.Column('retrieval_method', sa.String(length=64), nullable=True),
    sa.Column('origin_url', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['session_id'], ['research_sessions.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('session_id', 'artifact_key', name='uq_research_artifacts_session_key')
    )
    op.create_index(op.f('ix_research_artifacts_session_id'), 'research_artifacts', ['session_id'], unique=False)
    op.create_table('research_events',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('session_id', sa.Uuid(), nullable=False),
    sa.Column('event_id', sa.String(length=128), nullable=False),
    sa.Column('sequence', sa.Integer(), nullable=False),
    sa.Column('event_type', sa.String(length=64), nullable=False),
    sa.Column('phase', sa.String(length=64), nullable=False),
    sa.Column('namespace', sa.String(length=255), server_default='main', nullable=False),
    sa.Column('payload', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('trace_id', sa.String(length=128), nullable=True),
    sa.Column('idempotency_key', sa.String(length=128), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['session_id'], ['research_sessions.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('session_id', 'event_id', name='uq_research_events_session_event_id'),
    sa.UniqueConstraint('session_id', 'sequence', name='uq_research_events_session_sequence')
    )
    op.create_index(op.f('ix_research_events_session_id'), 'research_events', ['session_id'], unique=False)
    op.create_index(op.f('ix_research_events_trace_id'), 'research_events', ['trace_id'], unique=False)
    _restore_research_sessions_from_backup()
    _restore_research_artifacts_from_backup()
    _restore_research_events_from_backup()
    _restore_research_reports_from_backup()
    _drop_backup_tables()
    # ### end Alembic commands ###


def downgrade() -> None:
    """回退数据库结构。"""
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_index(op.f('ix_research_events_trace_id'), table_name='research_events')
    op.drop_index(op.f('ix_research_events_session_id'), table_name='research_events')
    op.drop_table('research_events')
    op.drop_index(op.f('ix_research_artifacts_session_id'), table_name='research_artifacts')
    op.drop_table('research_artifacts')
    op.drop_index(op.f('ix_research_sessions_status'), table_name='research_sessions')
    op.drop_index(op.f('ix_research_sessions_trace_id'), table_name='research_sessions')
    op.drop_table('research_sessions')
    postgresql.ENUM(name='research_session_status').drop(op.get_bind(), checkfirst=True)
    # ### end Alembic commands ###

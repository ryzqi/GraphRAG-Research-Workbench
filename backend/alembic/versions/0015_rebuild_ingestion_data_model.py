"""Rebuild knowledge-base readiness and ingestion data model.

Revision ID: 0015
Revises: 0014
Create Date: 2026-02-07
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0015"
down_revision: str | None = "0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _create_enum(name: str, values: tuple[str, ...]) -> postgresql.ENUM:
    enum = postgresql.ENUM(*values, name=name, create_type=False)
    enum.create(op.get_bind(), checkfirst=True)
    return enum


def upgrade() -> None:
    readiness_enum = _create_enum(
        "knowledge_base_readiness",
        ("not_ready", "ready"),
    )
    batch_status_enum = _create_enum(
        "ingestion_batch_status",
        ("queued", "running", "succeeded", "partial_failed", "failed", "canceled"),
    )
    doc_status_enum = _create_enum(
        "ingestion_doc_status",
        ("pending", "running", "succeeded", "failed", "canceled"),
    )
    source_type_enum = _create_enum(
        "ingestion_source_type",
        ("text", "url", "file"),
    )

    op.add_column(
        "knowledge_bases",
        sa.Column(
            "readiness",
            readiness_enum,
            nullable=False,
            server_default="not_ready",
        ),
    )
    op.add_column(
        "knowledge_bases",
        sa.Column(
            "readiness_updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.add_column(
        "knowledge_bases",
        sa.Column(
            "current_config_version",
            sa.Integer(),
            nullable=False,
            server_default="1",
        ),
    )

    op.execute(
        """
        UPDATE knowledge_bases kb
        SET readiness = 'ready', readiness_updated_at = now()
        WHERE EXISTS (
            SELECT 1
            FROM document_chunks dc
            WHERE dc.kb_id = kb.id
        );
        """
    )

    op.create_table(
        "kb_config_snapshots",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "kb_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("knowledge_bases.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("config_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint("kb_id", "version", name="uq_kb_config_snapshots_kb_version"),
    )
    op.create_index(
        "ix_kb_config_snapshots_kb_id",
        "kb_config_snapshots",
        ["kb_id"],
        unique=False,
    )

    bind = op.get_bind()
    snapshot_table = sa.table(
        "kb_config_snapshots",
        sa.column("id", sa.Uuid(as_uuid=True)),
        sa.column("kb_id", sa.Uuid(as_uuid=True)),
        sa.column("version", sa.Integer),
        sa.column("config_json", postgresql.JSONB),
    )
    kb_rows = bind.execute(
        sa.text("SELECT id, index_config FROM knowledge_bases")
    ).mappings()
    for row in kb_rows:
        bind.execute(
            sa.insert(snapshot_table).values(
                id=uuid.uuid4(),
                kb_id=row["id"],
                version=1,
                config_json=row["index_config"] or {},
            )
        )

    op.create_table(
        "ingestion_batches",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "kb_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("knowledge_bases.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "config_snapshot_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("kb_config_snapshots.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("config_version", sa.Integer(), nullable=False),
        sa.Column("is_bootstrap", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column(
            "status",
            batch_status_enum,
            nullable=False,
            server_default="queued",
        ),
        sa.Column("total_docs", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("succeeded_docs", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("failed_docs", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("canceled_docs", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("succeeded_chunks", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("progress_percent", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_summary", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("requested_by", sa.String(length=128), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_ingestion_batches_kb_id", "ingestion_batches", ["kb_id"], unique=False)
    op.create_index(
        "uq_ingestion_batches_bootstrap_kb",
        "ingestion_batches",
        ["kb_id"],
        unique=True,
        postgresql_where=sa.text("is_bootstrap = true"),
    )

    op.create_table(
        "ingestion_batch_docs",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "batch_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("ingestion_batches.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "kb_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("knowledge_bases.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "config_snapshot_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("kb_config_snapshots.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("config_version", sa.Integer(), nullable=False),
        sa.Column("source_type", source_type_enum, nullable=False),
        sa.Column("source_ref", sa.Text(), nullable=True),
        sa.Column("title", sa.Text(), nullable=True),
        sa.Column("fingerprint", sa.String(length=128), nullable=False),
        sa.Column(
            "status",
            doc_status_enum,
            nullable=False,
            server_default="pending",
        ),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("retry_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("retryable", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("chunk_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint(
            "kb_id",
            "fingerprint",
            "config_version",
            name="uq_ingestion_batch_docs_idempotency",
        ),
    )
    op.create_index(
        "ix_ingestion_batch_docs_batch_id",
        "ingestion_batch_docs",
        ["batch_id"],
        unique=False,
    )
    op.create_index(
        "ix_ingestion_batch_docs_kb_id",
        "ingestion_batch_docs",
        ["kb_id"],
        unique=False,
    )

    op.create_table(
        "ingestion_events",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "batch_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("ingestion_batches.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "doc_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("ingestion_batch_docs.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("from_status", sa.String(length=32), nullable=True),
        sa.Column("to_status", sa.String(length=32), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index("ix_ingestion_events_batch_id", "ingestion_events", ["batch_id"], unique=False)
    op.create_index("ix_ingestion_events_doc_id", "ingestion_events", ["doc_id"], unique=False)

    op.drop_table("ingestion_job_items")
    op.drop_table("ingestion_jobs")
    op.execute("DROP TYPE IF EXISTS ingestion_job_item_action")
    op.execute("DROP TYPE IF EXISTS ingestion_status")


def downgrade() -> None:
    ingestion_status_enum = _create_enum(
        "ingestion_status",
        ("queued", "running", "succeeded", "failed", "canceled"),
    )
    ingestion_job_item_action_enum = _create_enum(
        "ingestion_job_item_action",
        ("create", "update"),
    )

    op.create_table(
        "ingestion_jobs",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "kb_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("knowledge_bases.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("status", ingestion_status_enum, nullable=False, server_default="queued"),
        sa.Column("requested_by", sa.String(length=128), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("stats", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_ingestion_jobs_kb_id", "ingestion_jobs", ["kb_id"], unique=False)

    op.create_table(
        "ingestion_job_items",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "job_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("ingestion_jobs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "material_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("source_materials.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "action",
            ingestion_job_item_action_enum,
            nullable=False,
            server_default="create",
        ),
    )
    op.create_index(
        "ix_ingestion_job_items_job_id",
        "ingestion_job_items",
        ["job_id"],
        unique=False,
    )

    op.drop_index("ix_ingestion_events_doc_id", table_name="ingestion_events")
    op.drop_index("ix_ingestion_events_batch_id", table_name="ingestion_events")
    op.drop_table("ingestion_events")

    op.drop_index("ix_ingestion_batch_docs_kb_id", table_name="ingestion_batch_docs")
    op.drop_index("ix_ingestion_batch_docs_batch_id", table_name="ingestion_batch_docs")
    op.drop_table("ingestion_batch_docs")

    op.drop_index("uq_ingestion_batches_bootstrap_kb", table_name="ingestion_batches")
    op.drop_index("ix_ingestion_batches_kb_id", table_name="ingestion_batches")
    op.drop_table("ingestion_batches")

    op.drop_index("ix_kb_config_snapshots_kb_id", table_name="kb_config_snapshots")
    op.drop_table("kb_config_snapshots")

    op.drop_column("knowledge_bases", "current_config_version")
    op.drop_column("knowledge_bases", "readiness_updated_at")
    op.drop_column("knowledge_bases", "readiness")

    op.execute("DROP TYPE IF EXISTS ingestion_source_type")
    op.execute("DROP TYPE IF EXISTS ingestion_doc_status")
    op.execute("DROP TYPE IF EXISTS ingestion_batch_status")
    op.execute("DROP TYPE IF EXISTS knowledge_base_readiness")

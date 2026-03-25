"""新增导入任务 outbox

Revision ID: 9b9a6f4f20d1
Revises: 6f4b0d9e2c31
Create Date: 2026-02-18 18:20:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# Alembic 修订标识。
revision = "9b9a6f4f20d1"
down_revision = "6f4b0d9e2c31"
branch_labels = None
depends_on = None


def upgrade() -> None:
    status_enum = postgresql.ENUM(
        "pending",
        "dispatching",
        "dispatched",
        "failed",
        name="ingestion_task_outbox_status",
        create_type=False,
    )
    status_enum.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "ingestion_task_outbox",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("doc_id", sa.Uuid(), nullable=False),
        sa.Column("batch_id", sa.Uuid(), nullable=False),
        sa.Column("task_name", sa.String(length=255), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column(
            "status",
            status_enum,
            nullable=False,
            server_default=sa.text("'pending'::ingestion_task_outbox_status"),
        ),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("max_attempts", sa.Integer(), nullable=False, server_default=sa.text("20")),
        sa.Column("next_retry_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("dispatched_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["batch_id"], ["ingestion_batches.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["doc_id"], ["ingestion_batch_docs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("doc_id", "task_name", name="uq_ingestion_task_outbox_doc_task"),
    )
    op.create_index(op.f("ix_ingestion_task_outbox_batch_id"), "ingestion_task_outbox", ["batch_id"], unique=False)
    op.create_index(op.f("ix_ingestion_task_outbox_doc_id"), "ingestion_task_outbox", ["doc_id"], unique=False)
    op.create_index(
        "ix_ingestion_task_outbox_status_next_retry_created",
        "ingestion_task_outbox",
        ["status", "next_retry_at", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_ingestion_task_outbox_status_next_retry_created", table_name="ingestion_task_outbox")
    op.drop_index(op.f("ix_ingestion_task_outbox_doc_id"), table_name="ingestion_task_outbox")
    op.drop_index(op.f("ix_ingestion_task_outbox_batch_id"), table_name="ingestion_task_outbox")
    op.drop_table("ingestion_task_outbox")

    status_enum = sa.Enum(
        "pending",
        "dispatching",
        "dispatched",
        "failed",
        name="ingestion_task_outbox_status",
    )
    status_enum.drop(op.get_bind(), checkfirst=True)

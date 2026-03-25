"""新增索引重建任务 outbox

Revision ID: d1e8b6c4a9f0
Revises: b7c3d1a9f2e4
Create Date: 2026-02-18 23:30:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# Alembic 修订标识。
revision = "d1e8b6c4a9f0"
down_revision = "b7c3d1a9f2e4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    status_enum = postgresql.ENUM(
        "pending",
        "dispatching",
        "dispatched",
        "failed",
        name="index_rebuild_task_outbox_status",
        create_type=False,
    )
    status_enum.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "index_rebuild_task_outbox",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("job_id", sa.Uuid(), nullable=False),
        sa.Column("task_name", sa.String(length=255), nullable=False),
        sa.Column(
            "payload",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "status",
            status_enum,
            nullable=False,
            server_default=sa.text("'pending'::index_rebuild_task_outbox_status"),
        ),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("max_attempts", sa.Integer(), nullable=False, server_default=sa.text("20")),
        sa.Column("next_retry_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("dispatched_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
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
        sa.ForeignKeyConstraint(["job_id"], ["index_rebuild_jobs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("job_id", "task_name", name="uq_index_rebuild_outbox_job_task"),
    )
    op.create_index(
        op.f("ix_index_rebuild_task_outbox_job_id"),
        "index_rebuild_task_outbox",
        ["job_id"],
        unique=False,
    )
    op.create_index(
        "ix_index_rebuild_outbox_status_next_retry_created",
        "index_rebuild_task_outbox",
        ["status", "next_retry_at", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_index_rebuild_outbox_status_next_retry_created",
        table_name="index_rebuild_task_outbox",
    )
    op.drop_index(
        op.f("ix_index_rebuild_task_outbox_job_id"),
        table_name="index_rebuild_task_outbox",
    )
    op.drop_table("index_rebuild_task_outbox")

    status_enum = sa.Enum(
        "pending",
        "dispatching",
        "dispatched",
        "failed",
        name="index_rebuild_task_outbox_status",
    )
    status_enum.drop(op.get_bind(), checkfirst=True)

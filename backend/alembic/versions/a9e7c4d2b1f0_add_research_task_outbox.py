"""新增 research task outbox

Revision ID: a9e7c4d2b1f0
Revises: f4b2c1d9e8a7
Create Date: 2026-04-08 18:10:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# Alembic 修订标识。
revision = "a9e7c4d2b1f0"
down_revision = "f4b2c1d9e8a7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    status_enum = postgresql.ENUM(
        "pending",
        "dispatching",
        "dispatched",
        "failed",
        name="research_task_outbox_status",
        create_type=False,
    )
    status_enum.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "research_task_outbox",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("session_id", sa.Uuid(), nullable=False),
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
            server_default=sa.text("'pending'::research_task_outbox_status"),
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
        sa.ForeignKeyConstraint(["session_id"], ["research_sessions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("session_id", "task_name", name="uq_research_task_outbox_session_task"),
    )
    op.create_index(
        op.f("ix_research_task_outbox_session_id"),
        "research_task_outbox",
        ["session_id"],
        unique=False,
    )
    op.create_index(
        "ix_research_task_outbox_status_next_retry_created",
        "research_task_outbox",
        ["status", "next_retry_at", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_research_task_outbox_status_next_retry_created",
        table_name="research_task_outbox",
    )
    op.drop_index(
        op.f("ix_research_task_outbox_session_id"),
        table_name="research_task_outbox",
    )
    op.drop_table("research_task_outbox")

    status_enum = sa.Enum(
        "pending",
        "dispatching",
        "dispatched",
        "failed",
        name="research_task_outbox_status",
    )
    status_enum.drop(op.get_bind(), checkfirst=True)

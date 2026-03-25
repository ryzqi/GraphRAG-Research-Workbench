"""新增聊天请求去重表

Revision ID: f3a2c1d4e5b6
Revises: e5a1b7d3c4f2
Create Date: 2026-02-28 20:30:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# Alembic 修订标识。
revision = "f3a2c1d4e5b6"
down_revision = "e5a1b7d3c4f2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "chat_request_dedup",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("session_id", sa.Uuid(), nullable=False),
        sa.Column("client_request_id", sa.String(length=128), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=True),
        sa.Column("user_message_id", sa.Uuid(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["run_id"], ["agent_runs.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["session_id"], ["chat_sessions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["user_message_id"],
            ["chat_messages.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "session_id",
            "client_request_id",
            name="uq_chat_request_dedup_session_request",
        ),
    )
    op.create_index(
        op.f("ix_chat_request_dedup_run_id"),
        "chat_request_dedup",
        ["run_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_chat_request_dedup_session_id"),
        "chat_request_dedup",
        ["session_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_chat_request_dedup_session_id"), table_name="chat_request_dedup")
    op.drop_index(op.f("ix_chat_request_dedup_run_id"), table_name="chat_request_dedup")
    op.drop_table("chat_request_dedup")

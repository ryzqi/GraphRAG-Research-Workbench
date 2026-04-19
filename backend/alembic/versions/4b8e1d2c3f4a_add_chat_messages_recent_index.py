"""add chat messages recent index

Revision ID: 4b8e1d2c3f4a
Revises: 19a4c2e7d8f1
Create Date: 2026-04-19 17:10:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "4b8e1d2c3f4a"
down_revision = "19a4c2e7d8f1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """升级数据库结构。"""
    op.create_index(
        "ix_chat_messages_session_created_role_desc",
        "chat_messages",
        ["session_id", sa.text("created_at DESC"), "role"],
        unique=False,
    )


def downgrade() -> None:
    """回退数据库结构。"""
    op.drop_index(
        "ix_chat_messages_session_created_role_desc",
        table_name="chat_messages",
    )

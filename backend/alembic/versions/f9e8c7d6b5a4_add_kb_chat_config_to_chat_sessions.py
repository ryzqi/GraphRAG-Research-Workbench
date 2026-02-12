"""add kb_chat_config to chat_sessions

Revision ID: f9e8c7d6b5a4
Revises: b52c8d9f1a10
Create Date: 2026-02-12 20:30:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = "f9e8c7d6b5a4"
down_revision = "b52c8d9f1a10"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "chat_sessions",
        sa.Column("kb_chat_config", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("chat_sessions", "kb_chat_config")

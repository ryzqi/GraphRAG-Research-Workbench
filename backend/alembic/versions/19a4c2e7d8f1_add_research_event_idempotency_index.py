"""add research event idempotency index

Revision ID: 19a4c2e7d8f1
Revises: f4c6d8e0a1b2
Create Date: 2026-04-19 16:40:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "19a4c2e7d8f1"
down_revision = "f4c6d8e0a1b2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """升级数据库结构。"""
    op.create_index(
        "uq_research_events_session_idempotency_key",
        "research_events",
        ["session_id", "idempotency_key"],
        unique=True,
        postgresql_where=sa.text("idempotency_key IS NOT NULL"),
    )


def downgrade() -> None:
    """回退数据库结构。"""
    op.drop_index(
        "uq_research_events_session_idempotency_key",
        table_name="research_events",
    )

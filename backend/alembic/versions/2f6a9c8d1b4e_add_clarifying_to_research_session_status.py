"""add clarifying to research session status

Revision ID: 2f6a9c8d1b4e
Revises: 1c2d3e4f5a6b
Create Date: 2026-03-31 00:55:00
"""

from __future__ import annotations

from alembic import op

# revision identifiers, used by Alembic.
revision = "2f6a9c8d1b4e"
down_revision = "1c2d3e4f5a6b"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute(
            "ALTER TYPE research_session_status "
            "ADD VALUE IF NOT EXISTS 'clarifying' AFTER 'planning'"
        )


def downgrade() -> None:
    # PostgreSQL ENUM 删除值成本高且可能影响既有数据，这里保持 no-op。
    pass

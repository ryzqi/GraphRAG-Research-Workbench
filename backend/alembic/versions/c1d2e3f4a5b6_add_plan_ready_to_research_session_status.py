"""add plan_ready to research session status

Revision ID: c1d2e3f4a5b6
Revises: 2f6a9c8d1b4e
Create Date: 2026-04-02 00:40:00
"""

from __future__ import annotations

from alembic import op

# revision identifiers, used by Alembic.
revision = "c1d2e3f4a5b6"
down_revision = "2f6a9c8d1b4e"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute(
            "ALTER TYPE research_session_status "
            "ADD VALUE IF NOT EXISTS 'plan_ready' AFTER 'clarifying'"
        )


def downgrade() -> None:
    # PostgreSQL ENUM 删除值成本高且可能影响既有数据，这里保持 no-op。
    pass

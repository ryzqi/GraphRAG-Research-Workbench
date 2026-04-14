"""add succeeded to ingestion task outbox status

Revision ID: e8f9a0b1c2d3
Revises: c7d8e9f0a1b2
Create Date: 2026-04-14 23:15:00
"""

from __future__ import annotations

from alembic import op

# revision identifiers, used by Alembic.
revision = "e8f9a0b1c2d3"
down_revision = "c7d8e9f0a1b2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute(
            "ALTER TYPE ingestion_task_outbox_status "
            "ADD VALUE IF NOT EXISTS 'succeeded' AFTER 'failed'"
        )


def downgrade() -> None:
    # PostgreSQL ENUM 删除值成本高且可能影响既有数据，这里保持 no-op。
    pass

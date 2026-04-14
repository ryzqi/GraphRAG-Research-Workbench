"""drop tool extension observability config

Revision ID: f4c6d8e0a1b2
Revises: e8f9a0b1c2d3
Create Date: 2026-04-15 01:20:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "f4c6d8e0a1b2"
down_revision = "e8f9a0b1c2d3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """升级数据库结构。"""
    op.drop_column("tool_extensions", "observability_config")


def downgrade() -> None:
    """回退数据库结构。"""
    op.add_column("tool_extensions",
        sa.Column(
            "observability_config",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
    )

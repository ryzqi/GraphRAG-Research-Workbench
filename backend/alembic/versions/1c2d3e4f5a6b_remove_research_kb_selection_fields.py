"""remove research kb selection fields

Revision ID: 1c2d3e4f5a6b
Revises: 38f4aa0f8d91
Create Date: 2026-03-30 17:30:00.000000

"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# Alembic 修订标识。
revision: str = "1c2d3e4f5a6b"
down_revision: Union[str, Sequence[str], None] = "38f4aa0f8d91"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """升级数据库结构。"""
    op.drop_column("research_sessions", "allow_external")
    op.drop_column("research_sessions", "selected_kb_ids")


def downgrade() -> None:
    """回退数据库结构。"""
    op.add_column(
        "research_sessions",
        sa.Column(
            "selected_kb_ids",
            postgresql.ARRAY(sa.Uuid()),
            nullable=True,
        ),
    )
    op.add_column(
        "research_sessions",
        sa.Column(
            "allow_external",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )

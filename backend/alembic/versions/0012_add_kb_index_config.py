"""为知识库新增索引配置字段

Revision ID: 0012
Revises: 0011
Create Date: 2026-01-23
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "knowledge_bases",
        sa.Column(
            "index_config",
            postgresql.JSONB,
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )
    op.alter_column("knowledge_bases", "index_config", server_default=None)


def downgrade() -> None:
    op.drop_column("knowledge_bases", "index_config")

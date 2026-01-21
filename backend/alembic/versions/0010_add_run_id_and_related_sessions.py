"""新增导出关联字段与评测关联会话字段
Revision ID: 0010
Revises: 0009
Create Date: 2026-01-21
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("export_jobs", sa.Column("run_id", sa.Uuid(as_uuid=True), nullable=True))
    op.add_column(
        "evaluation_runs",
        sa.Column(
            "related_session_ids",
            postgresql.ARRAY(sa.Uuid(as_uuid=True)),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("evaluation_runs", "related_session_ids")
    op.drop_column("export_jobs", "run_id")

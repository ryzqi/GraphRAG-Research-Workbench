"""移除反馈表

Revision ID: 0009
Revises: 0007
Create Date: 2025-01-01
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0009"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_table("feedback")
    op.execute("DROP TYPE IF EXISTS feedback_status")


def downgrade() -> None:
    # 回滚会重建结构，历史数据无法恢复。
    feedback_status = postgresql.ENUM(
        "pending", "reviewed", "resolved", "dismissed",
        name="feedback_status",
        create_type=False,
    )
    feedback_status.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "feedback",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column(
            "run_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("agent_runs.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("rating", sa.SmallInteger, nullable=False, comment="评分 1-5"),
        sa.Column("comment", sa.Text, nullable=True),
        sa.Column(
            "status",
            feedback_status,
            nullable=False,
            server_default="pending",
        ),
        sa.Column("resolution_note", sa.Text, nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )

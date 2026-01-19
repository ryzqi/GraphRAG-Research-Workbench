"""创建候选沉淀表

Revision ID: 0006
Revises: 0005
Create Date: 2025-01-01
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 创建枚举类型
    proposal_status = postgresql.ENUM(
        "pending", "approved", "rejected", "applied", name="proposal_status", create_type=False
    )
    proposal_status.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "knowledge_update_proposals",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column(
            "kb_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("knowledge_bases.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "source_run_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("agent_runs.id", ondelete="SET NULL"),
            nullable=True,
            index=True,
        ),
        sa.Column("summary", sa.Text, nullable=False),
        sa.Column("payload", postgresql.JSONB, nullable=False),
        sa.Column(
            "status",
            proposal_status,
            nullable=False,
            server_default="pending",
        ),
        sa.Column("created_by", sa.String(128), nullable=True),
        sa.Column("reviewed_by", sa.String(128), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("knowledge_update_proposals")
    op.execute("DROP TYPE IF EXISTS proposal_status")

"""移除工具调用记录表

Revision ID: 0011
Revises: 0010
Create Date: 2026-01-22
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_table("tool_invocations")
    op.execute("DROP TYPE IF EXISTS invocation_status")


def downgrade() -> None:
    invocation_status = postgresql.ENUM(
        "succeeded", "failed", "canceled", name="invocation_status", create_type=False
    )
    invocation_status.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "tool_invocations",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column(
            "extension_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("tool_extensions.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "run_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("agent_runs.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("tool_name", sa.String(256), nullable=False),
        sa.Column("purpose", sa.Text, nullable=True),
        sa.Column("input", postgresql.JSONB, nullable=True),
        sa.Column("output", postgresql.JSONB, nullable=True),
        sa.Column(
            "status",
            invocation_status,
            nullable=False,
        ),
        sa.Column("error_message", sa.Text, nullable=True),
        sa.Column("requires_confirmation", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("user_confirmed", sa.Boolean, nullable=True),
        sa.Column(
            "started_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
    )

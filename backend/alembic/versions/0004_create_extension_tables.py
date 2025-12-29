"""创建扩展相关表

Revision ID: 0004
Revises: 0003
Create Date: 2025-01-01
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 创建枚举类型
    extension_transport = postgresql.ENUM(
        "stdio", "http", name="extension_transport", create_type=False
    )
    extension_transport.create(op.get_bind(), checkfirst=True)

    extension_status = postgresql.ENUM(
        "enabled", "disabled", name="extension_status", create_type=False
    )
    extension_status.create(op.get_bind(), checkfirst=True)

    invocation_status = postgresql.ENUM(
        "succeeded", "failed", "canceled", name="invocation_status", create_type=False
    )
    invocation_status.create(op.get_bind(), checkfirst=True)

    # 创建 tool_extensions 表
    op.create_table(
        "tool_extensions",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(128), nullable=False, unique=True),
        sa.Column(
            "transport",
            sa.Enum("stdio", "http", name="extension_transport", create_type=False),
            nullable=False,
        ),
        sa.Column("endpoint", sa.Text, nullable=False),
        sa.Column(
            "status",
            sa.Enum("enabled", "disabled", name="extension_status", create_type=False),
            nullable=False,
            server_default="disabled",
        ),
        sa.Column("scope", postgresql.JSONB, nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )

    # 创建 tool_invocations 表
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
            sa.Enum("succeeded", "failed", "canceled", name="invocation_status", create_type=False),
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


def downgrade() -> None:
    op.drop_table("tool_invocations")
    op.drop_table("tool_extensions")

    op.execute("DROP TYPE IF EXISTS invocation_status")
    op.execute("DROP TYPE IF EXISTS extension_status")
    op.execute("DROP TYPE IF EXISTS extension_transport")

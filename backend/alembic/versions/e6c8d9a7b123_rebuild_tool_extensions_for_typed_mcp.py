"""rebuild tool_extensions for typed mcp configs

Revision ID: e6c8d9a7b123
Revises: f9e8c7d6b5a4
Create Date: 2026-02-15 00:00:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = "e6c8d9a7b123"
down_revision = "f9e8c7d6b5a4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_table("tool_extensions")
    op.create_table(
        "tool_extensions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column(
            "transport",
            sa.Enum(
                "stdio",
                "http",
                name="extension_transport",
                create_type=False,
            ),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.Enum(
                "enabled",
                "disabled",
                name="extension_status",
                create_type=False,
            ),
            nullable=False,
        ),
        sa.Column("http_config", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("stdio_config", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "security_config",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "observability_config",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )


def downgrade() -> None:
    op.drop_table("tool_extensions")
    op.create_table(
        "tool_extensions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column(
            "transport",
            sa.Enum(
                "stdio",
                "http",
                name="extension_transport",
                create_type=False,
            ),
            nullable=False,
        ),
        sa.Column("endpoint", sa.Text(), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "enabled",
                "disabled",
                name="extension_status",
                create_type=False,
            ),
            nullable=False,
        ),
        sa.Column("scope", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )

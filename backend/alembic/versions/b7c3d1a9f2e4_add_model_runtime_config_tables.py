"""add model runtime config tables

Revision ID: b7c3d1a9f2e4
Revises: c4d7a3f1b8e9
Create Date: 2026-02-18 22:10:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "b7c3d1a9f2e4"
down_revision = "c4d7a3f1b8e9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    provider_enum = postgresql.ENUM(
        "openai",
        "ollama",
        "nvidia",
        name="model_provider",
        create_type=False,
    )
    provider_enum.create(bind, checkfirst=True)

    op.create_table(
        "model_provider_configs",
        sa.Column("provider", provider_enum, nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("base_url", sa.String(length=2048), nullable=True),
        sa.Column("api_key_encrypted", sa.Text(), nullable=True),
        sa.Column("model", sa.String(length=256), nullable=True),
        sa.Column("thinking_enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("thinking_level", sa.String(length=32), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("provider"),
    )

    op.create_table(
        "model_runtime_selection",
        sa.Column("id", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column(
            "active_provider",
            provider_enum,
            nullable=False,
            server_default=sa.text("'openai'::model_provider"),
        ),
        sa.Column("active_model", sa.String(length=256), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("id"),
    )

    op.execute(
        sa.text(
            """
            INSERT INTO model_provider_configs
                (provider, enabled, base_url, api_key_encrypted, model, thinking_enabled, thinking_level)
            VALUES
                ('openai', true, 'https://api.openai.com/v1', NULL, 'gpt-4o-mini', true, 'high'),
                ('ollama', true, 'http://127.0.0.1:11434', NULL, NULL, true, 'high'),
                ('nvidia', true, NULL, NULL, NULL, true, NULL)
            ON CONFLICT (provider) DO NOTHING
            """
        )
    )

    op.execute(
        sa.text(
            """
            INSERT INTO model_runtime_selection (id, active_provider, active_model)
            VALUES (1, 'openai', 'gpt-4o-mini')
            ON CONFLICT (id) DO NOTHING
            """
        )
    )


def downgrade() -> None:
    op.drop_table("model_runtime_selection")
    op.drop_table("model_provider_configs")

    provider_enum = postgresql.ENUM(name="model_provider")
    provider_enum.drop(op.get_bind(), checkfirst=True)

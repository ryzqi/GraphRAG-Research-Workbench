"""add llama.cpp model provider

Revision ID: b3c4d5e6f7a8
Revises: a9e7c4d2b1f0
Create Date: 2026-04-10 20:45:00
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "b3c4d5e6f7a8"
down_revision = "a9e7c4d2b1f0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute(
            "ALTER TYPE model_provider "
            "ADD VALUE IF NOT EXISTS 'llama.cpp'"
        )

    op.execute(
        sa.text(
            """
            INSERT INTO model_provider_configs
                (provider, enabled, base_url, api_key_encrypted, models, thinking_enabled, thinking_level)
            VALUES
                ('llama.cpp', true, 'http://127.0.0.1:8080/v1', NULL, '{}'::character varying[], false, NULL)
            ON CONFLICT (provider) DO NOTHING
            """
        )
    )


def downgrade() -> None:
    # PostgreSQL ENUM 删除值成本高且可能影响既有数据，这里保持 no-op。
    pass

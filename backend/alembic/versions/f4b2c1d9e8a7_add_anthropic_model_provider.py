"""add anthropic model provider

Revision ID: f4b2c1d9e8a7
Revises: c1d2e3f4a5b6
Create Date: 2026-04-08 15:40:00
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "f4b2c1d9e8a7"
down_revision = "c1d2e3f4a5b6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute(
            "ALTER TYPE model_provider "
            "ADD VALUE IF NOT EXISTS 'anthropic'"
        )

    op.execute(
        sa.text(
            """
            INSERT INTO model_provider_configs
                (provider, enabled, base_url, api_key_encrypted, models, thinking_enabled, thinking_level)
            VALUES
                ('anthropic', true, NULL, NULL, '{}'::character varying[], true, 'high')
            ON CONFLICT (provider) DO NOTHING
            """
        )
    )


def downgrade() -> None:
    # PostgreSQL ENUM 删除值成本高且可能影响既有数据，这里保持 no-op。
    pass

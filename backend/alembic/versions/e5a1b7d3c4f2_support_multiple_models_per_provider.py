"""支持每个提供商配置多个模型

Revision ID: e5a1b7d3c4f2
Revises: d1e8b6c4a9f0
Create Date: 2026-02-19 00:10:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# Alembic 修订标识。
revision = "e5a1b7d3c4f2"
down_revision = "d1e8b6c4a9f0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "model_provider_configs",
        sa.Column(
            "models",
            postgresql.ARRAY(sa.String(length=256)),
            nullable=False,
            server_default=sa.text("'{}'::character varying[]"),
        ),
    )

    op.execute(
        sa.text(
            """
            UPDATE model_provider_configs
            SET models = CASE
                WHEN model IS NULL OR btrim(model) = '' THEN '{}'::character varying[]
                ELSE ARRAY[btrim(model)]
            END
            """
        )
    )

    op.drop_column("model_provider_configs", "model")


def downgrade() -> None:
    op.add_column(
        "model_provider_configs",
        sa.Column("model", sa.String(length=256), nullable=True),
    )

    op.execute(
        sa.text(
            """
            UPDATE model_provider_configs
            SET model = CASE
                WHEN models IS NULL OR array_length(models, 1) IS NULL THEN NULL
                ELSE NULLIF(btrim(models[1]), '')
            END
            """
        )
    )

    op.drop_column("model_provider_configs", "models")

"""Drop legacy contextual.timeout_seconds from knowledge base index config JSON.

Revision ID: 0016
Revises: 0015
Create Date: 2026-02-09
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0016"
down_revision: str | None = "0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE knowledge_bases
        SET index_config = index_config #- '{contextual,timeout_seconds}'
        WHERE jsonb_typeof(index_config->'contextual') = 'object'
          AND (index_config->'contextual') ? 'timeout_seconds';
        """
    )

    op.execute(
        """
        UPDATE kb_config_snapshots
        SET config_json = config_json #- '{contextual,timeout_seconds}'
        WHERE jsonb_typeof(config_json->'contextual') = 'object'
          AND (config_json->'contextual') ? 'timeout_seconds';
        """
    )


def downgrade() -> None:
    op.execute(
        """
        UPDATE knowledge_bases
        SET index_config = jsonb_set(
            index_config,
            '{contextual,timeout_seconds}',
            '15'::jsonb,
            true
        )
        WHERE jsonb_typeof(index_config->'contextual') = 'object'
          AND NOT ((index_config->'contextual') ? 'timeout_seconds');
        """
    )

    op.execute(
        """
        UPDATE kb_config_snapshots
        SET config_json = jsonb_set(
            config_json,
            '{contextual,timeout_seconds}',
            '15'::jsonb,
            true
        )
        WHERE jsonb_typeof(config_json->'contextual') = 'object'
          AND NOT ((config_json->'contextual') ? 'timeout_seconds');
        """
    )

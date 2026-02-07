"""Drop legacy retrieval.parent_child.enabled from knowledge_bases.index_config

Revision ID: 0014
Revises: 0013
Create Date: 2026-02-07
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0014"
down_revision: str | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE knowledge_bases
        SET index_config = index_config #- '{retrieval,parent_child,enabled}'
        WHERE jsonb_typeof(index_config->'retrieval') = 'object'
          AND jsonb_typeof(index_config->'retrieval'->'parent_child') = 'object'
          AND (index_config->'retrieval'->'parent_child') ? 'enabled';
        """
    )


def downgrade() -> None:
    op.execute(
        """
        UPDATE knowledge_bases
        SET index_config = jsonb_set(
            index_config,
            '{retrieval,parent_child,enabled}',
            'false'::jsonb,
            true
        )
        WHERE jsonb_typeof(index_config->'retrieval') = 'object'
          AND jsonb_typeof(index_config->'retrieval'->'parent_child') = 'object'
          AND NOT ((index_config->'retrieval'->'parent_child') ? 'enabled');
        """
    )

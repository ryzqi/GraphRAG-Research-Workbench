"""delete legacy sliding_window knowledge bases

Revision ID: 7c5f7d5b71d8
Revises: 4ec9b68f7d26
Create Date: 2026-02-11 19:30:00.000000

"""

from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "7c5f7d5b71d8"
down_revision: Union[str, Sequence[str], None] = "4ec9b68f7d26"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""

    op.execute(
        """
        WITH legacy_kb_ids AS (
            SELECT kb.id
            FROM knowledge_bases AS kb
            WHERE
                COALESCE(kb.index_config -> 'chunking', '{}'::jsonb) ? 'sliding_window'
                OR COALESCE(kb.index_config -> 'chunking' ->> 'general_strategy', '') = 'sliding_window'
            UNION
            SELECT DISTINCT snap.kb_id AS id
            FROM kb_config_snapshots AS snap
            WHERE
                COALESCE(snap.config_json -> 'chunking', '{}'::jsonb) ? 'sliding_window'
                OR COALESCE(snap.config_json -> 'chunking' ->> 'general_strategy', '') = 'sliding_window'
        )
        DELETE FROM knowledge_bases AS kb
        USING legacy_kb_ids AS legacy
        WHERE kb.id = legacy.id
        """
    )


def downgrade() -> None:
    """Downgrade schema."""

    raise RuntimeError("Irreversible migration: deleted legacy knowledge_bases rows")

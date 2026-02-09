"""Add processed_text for final chunk display content.

Revision ID: 0017
Revises: 0016
Create Date: 2026-02-09
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0017"
down_revision: str | None = "0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "document_chunks",
        sa.Column("processed_text", sa.Text(), nullable=True),
    )
    op.execute(
        """
        UPDATE document_chunks
        SET processed_text = text
        WHERE processed_text IS NULL;
        """
    )
    op.alter_column("document_chunks", "processed_text", nullable=False)


def downgrade() -> None:
    op.drop_column("document_chunks", "processed_text")

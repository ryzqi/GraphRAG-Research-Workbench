"""add chunk strategy and heading path fields to document chunks

Revision ID: 09b33ebd7c66
Revises: 7c5f7d5b71d8
Create Date: 2026-02-11 20:20:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "09b33ebd7c66"
down_revision: Union[str, Sequence[str], None] = "7c5f7d5b71d8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""

    op.add_column(
        "document_chunks",
        sa.Column(
            "chunking_strategy",
            sa.String(length=32),
            nullable=False,
            server_default=sa.text("'unknown'"),
        ),
    )
    op.add_column(
        "document_chunks",
        sa.Column("heading_path", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    """Downgrade schema."""

    op.drop_column("document_chunks", "heading_path")
    op.drop_column("document_chunks", "chunking_strategy")

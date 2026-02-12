"""add structured window/span/source fields to document_chunks

Revision ID: b52c8d9f1a10
Revises: 09b33ebd7c66
Create Date: 2026-02-12 19:40:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "b52c8d9f1a10"
down_revision: Union[str, Sequence[str], None] = "09b33ebd7c66"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""

    op.add_column(
        "document_chunks",
        sa.Column(
            "global_chunk_order",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
    )
    op.add_column(
        "document_chunks",
        sa.Column("window_id", sa.Integer(), nullable=True),
    )
    op.add_column(
        "document_chunks",
        sa.Column("window_size_tokens", sa.Integer(), nullable=True),
    )
    op.add_column(
        "document_chunks",
        sa.Column("window_overlap_tokens", sa.Integer(), nullable=True),
    )
    op.add_column(
        "document_chunks",
        sa.Column("token_start", sa.Integer(), nullable=True),
    )
    op.add_column(
        "document_chunks",
        sa.Column("token_end", sa.Integer(), nullable=True),
    )
    op.add_column(
        "document_chunks",
        sa.Column("source_kind", sa.String(length=24), nullable=True),
    )
    op.add_column(
        "document_chunks",
        sa.Column("source_page_start", sa.Integer(), nullable=True),
    )
    op.add_column(
        "document_chunks",
        sa.Column("source_page_end", sa.Integer(), nullable=True),
    )

    op.create_index(
        "ix_document_chunks_kb_material_global_order",
        "document_chunks",
        ["kb_id", "material_id", "global_chunk_order"],
        unique=False,
    )
    op.create_index(
        "ix_document_chunks_kb_material_window_token",
        "document_chunks",
        ["kb_id", "material_id", "window_id", "token_start"],
        unique=False,
    )


def downgrade() -> None:
    """Downgrade schema."""

    op.drop_index("ix_document_chunks_kb_material_window_token", table_name="document_chunks")
    op.drop_index("ix_document_chunks_kb_material_global_order", table_name="document_chunks")

    op.drop_column("document_chunks", "source_page_end")
    op.drop_column("document_chunks", "source_page_start")
    op.drop_column("document_chunks", "source_kind")
    op.drop_column("document_chunks", "token_end")
    op.drop_column("document_chunks", "token_start")
    op.drop_column("document_chunks", "window_overlap_tokens")
    op.drop_column("document_chunks", "window_size_tokens")
    op.drop_column("document_chunks", "window_id")
    op.drop_column("document_chunks", "global_chunk_order")

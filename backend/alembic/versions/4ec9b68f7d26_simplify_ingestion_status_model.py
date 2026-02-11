"""simplify ingestion status model

Revision ID: 4ec9b68f7d26
Revises: 27894051a580
Create Date: 2026-02-11 11:40:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "4ec9b68f7d26"
down_revision: Union[str, Sequence[str], None] = "27894051a580"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.drop_column("ingestion_batches", "progress_percent")

    op.execute("ALTER TABLE ingestion_batches ALTER COLUMN status TYPE text USING status::text")
    op.execute(
        """
        UPDATE ingestion_batches
        SET status = CASE
            WHEN status IN ('queued', 'running') THEN 'processing'
            ELSE 'completed'
        END
        """
    )
    op.execute("DROP TYPE ingestion_batch_status")
    op.execute("CREATE TYPE ingestion_batch_status AS ENUM ('processing', 'completed')")
    op.execute(
        "ALTER TABLE ingestion_batches ALTER COLUMN status TYPE ingestion_batch_status USING status::ingestion_batch_status"
    )

    op.execute("ALTER TABLE ingestion_batch_docs ALTER COLUMN status TYPE text USING status::text")
    op.execute(
        """
        UPDATE ingestion_batch_docs
        SET status = CASE
            WHEN status IN ('pending', 'running') THEN 'processing'
            ELSE 'completed'
        END
        """
    )
    op.execute("DROP TYPE ingestion_doc_status")
    op.execute("CREATE TYPE ingestion_doc_status AS ENUM ('processing', 'completed')")
    op.execute(
        "ALTER TABLE ingestion_batch_docs ALTER COLUMN status TYPE ingestion_doc_status USING status::ingestion_doc_status"
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("ALTER TABLE ingestion_batch_docs ALTER COLUMN status TYPE text USING status::text")
    op.execute(
        """
        UPDATE ingestion_batch_docs
        SET status = CASE
            WHEN status = 'processing' THEN 'running'
            ELSE 'succeeded'
        END
        """
    )
    op.execute("DROP TYPE ingestion_doc_status")
    op.execute(
        "CREATE TYPE ingestion_doc_status AS ENUM ('pending', 'running', 'succeeded', 'failed', 'canceled')"
    )
    op.execute(
        "ALTER TABLE ingestion_batch_docs ALTER COLUMN status TYPE ingestion_doc_status USING status::ingestion_doc_status"
    )

    op.execute("ALTER TABLE ingestion_batches ALTER COLUMN status TYPE text USING status::text")
    op.execute(
        """
        UPDATE ingestion_batches
        SET status = CASE
            WHEN status = 'processing' THEN 'running'
            ELSE 'succeeded'
        END
        """
    )
    op.execute("DROP TYPE ingestion_batch_status")
    op.execute(
        "CREATE TYPE ingestion_batch_status AS ENUM ('queued', 'running', 'succeeded', 'partial_failed', 'failed', 'canceled')"
    )
    op.execute(
        "ALTER TABLE ingestion_batches ALTER COLUMN status TYPE ingestion_batch_status USING status::ingestion_batch_status"
    )

    op.add_column(
        "ingestion_batches",
        sa.Column("progress_percent", sa.Integer(), server_default=sa.text("0"), nullable=False),
    )

"""make ingestion status semantics explicit

Revision ID: c7d8e9f0a1b2
Revises: b3c4d5e6f7a8
Create Date: 2026-04-14 22:35:00
"""

from __future__ import annotations

from alembic import op

# revision identifiers, used by Alembic.
revision = "c7d8e9f0a1b2"
down_revision = "b3c4d5e6f7a8"
branch_labels = None
depends_on = None


def _upgrade_doc_status_enum() -> None:
    op.execute("ALTER TYPE ingestion_doc_status RENAME TO ingestion_doc_status_old")
    op.execute(
        """
        CREATE TYPE ingestion_doc_status AS ENUM (
            'queued',
            'processing',
            'succeeded',
            'failed',
            'canceled'
        )
        """
    )
    op.execute(
        """
        ALTER TABLE ingestion_batch_docs
        ALTER COLUMN status TYPE ingestion_doc_status
        USING (
            CASE
                WHEN status::text = 'processing' THEN 'processing'
                WHEN status::text = 'completed' AND error_code IS NULL THEN 'succeeded'
                WHEN status::text = 'completed' AND error_code = 'DOC_CANCELED' THEN 'canceled'
                ELSE 'failed'
            END
        )::ingestion_doc_status
        """
    )
    op.execute("DROP TYPE ingestion_doc_status_old")


def _upgrade_batch_status_enum() -> None:
    op.execute(
        "ALTER TYPE ingestion_batch_status RENAME TO ingestion_batch_status_old"
    )
    op.execute(
        """
        CREATE TYPE ingestion_batch_status AS ENUM (
            'queued',
            'processing',
            'completed',
            'failed',
            'canceled'
        )
        """
    )
    op.execute(
        """
        ALTER TABLE ingestion_batches
        ALTER COLUMN status TYPE ingestion_batch_status
        USING (
            CASE
                WHEN status::text = 'processing' THEN 'processing'
                ELSE 'completed'
            END
        )::ingestion_batch_status
        """
    )
    op.execute("DROP TYPE ingestion_batch_status_old")


def _backfill_batch_rollups() -> None:
    op.execute(
        """
        WITH doc_rollups AS (
            SELECT
                d.batch_id,
                COUNT(*) AS total_docs,
                COUNT(*) FILTER (WHERE d.status = 'succeeded') AS succeeded_docs,
                COUNT(*) FILTER (WHERE d.status = 'failed') AS failed_docs,
                COUNT(*) FILTER (WHERE d.status = 'canceled') AS canceled_docs,
                COALESCE(
                    SUM(d.chunk_count) FILTER (WHERE d.status = 'succeeded'),
                    0
                ) AS succeeded_chunks
            FROM ingestion_batch_docs AS d
            GROUP BY d.batch_id
        )
        UPDATE ingestion_batches AS b
        SET
            total_docs = COALESCE(r.total_docs, 0),
            succeeded_docs = COALESCE(r.succeeded_docs, 0),
            failed_docs = COALESCE(r.failed_docs, 0),
            canceled_docs = COALESCE(r.canceled_docs, 0),
            succeeded_chunks = COALESCE(r.succeeded_chunks, 0),
            status = CASE
                WHEN EXISTS (
                    SELECT 1
                    FROM ingestion_batch_docs AS d
                    WHERE
                        d.batch_id = b.id
                        AND d.status IN ('queued', 'processing')
                ) THEN 'processing'::ingestion_batch_status
                WHEN EXISTS (
                    SELECT 1
                    FROM ingestion_batch_docs AS d
                    WHERE d.batch_id = b.id AND d.status = 'failed'
                ) THEN 'failed'::ingestion_batch_status
                WHEN EXISTS (
                    SELECT 1
                    FROM ingestion_batch_docs AS d
                    WHERE d.batch_id = b.id AND d.status = 'canceled'
                ) THEN 'canceled'::ingestion_batch_status
                ELSE 'completed'::ingestion_batch_status
            END,
            error_summary = jsonb_build_object(
                'succeeded_docs',
                COALESCE(r.succeeded_docs, 0),
                'failed_docs',
                COALESCE(r.failed_docs, 0),
                'canceled_docs',
                COALESCE(r.canceled_docs, 0),
                'reason',
                'explicit_status_migration'
            )
        FROM doc_rollups AS r
        WHERE b.id = r.batch_id
        """
    )


def _downgrade_doc_status_enum() -> None:
    op.execute("ALTER TYPE ingestion_doc_status RENAME TO ingestion_doc_status_new")
    op.execute(
        """
        CREATE TYPE ingestion_doc_status AS ENUM (
            'processing',
            'completed'
        )
        """
    )
    op.execute(
        """
        ALTER TABLE ingestion_batch_docs
        ALTER COLUMN status TYPE ingestion_doc_status
        USING (
            CASE
                WHEN status::text IN ('queued', 'processing') THEN 'processing'
                ELSE 'completed'
            END
        )::ingestion_doc_status
        """
    )
    op.execute("DROP TYPE ingestion_doc_status_new")


def _downgrade_batch_status_enum() -> None:
    op.execute(
        "ALTER TYPE ingestion_batch_status RENAME TO ingestion_batch_status_new"
    )
    op.execute(
        """
        CREATE TYPE ingestion_batch_status AS ENUM (
            'processing',
            'completed'
        )
        """
    )
    op.execute(
        """
        ALTER TABLE ingestion_batches
        ALTER COLUMN status TYPE ingestion_batch_status
        USING (
            CASE
                WHEN status::text IN ('queued', 'processing') THEN 'processing'
                ELSE 'completed'
            END
        )::ingestion_batch_status
        """
    )
    op.execute("DROP TYPE ingestion_batch_status_new")


def upgrade() -> None:
    _upgrade_doc_status_enum()
    _upgrade_batch_status_enum()
    _backfill_batch_rollups()


def downgrade() -> None:
    _downgrade_doc_status_enum()
    _downgrade_batch_status_enum()

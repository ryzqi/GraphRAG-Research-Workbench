"""Create index rebuild jobs table

Revision ID: 0013
Revises: 0012
Create Date: 2026-01-23
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0013"
down_revision: str | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    status_enum = postgresql.ENUM(
        "queued",
        "running",
        "succeeded",
        "failed",
        "canceled",
        name="index_rebuild_status",
        create_type=False,
    )
    status_enum.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "index_rebuild_jobs",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column(
            "kb_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("knowledge_bases.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "status",
            status_enum,
            nullable=False,
            server_default="queued",
        ),
        sa.Column("error_message", sa.Text, nullable=True),
        sa.Column("stats", postgresql.JSONB, nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("index_rebuild_jobs")
    op.execute("DROP TYPE IF EXISTS index_rebuild_status")

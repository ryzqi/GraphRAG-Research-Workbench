"""创建导入相关表（ingestion_jobs/ingestion_job_items）。

Revision ID: 0003_create_ingestion_tables
Revises: 0002_create_kb_chat_tables
Create Date: 2025-12-22

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0003_create_ingestion_tables"
down_revision = "0002_create_kb_chat_tables"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 导入任务表
    op.create_table(
        "ingestion_jobs",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("kb_id", sa.Uuid(as_uuid=True), sa.ForeignKey("knowledge_bases.id", ondelete="CASCADE"), nullable=False),
        sa.Column(
            "status",
            sa.Enum("queued", "running", "succeeded", "failed", "canceled", name="ingestion_status"),
            nullable=False,
            server_default="queued",
        ),
        sa.Column("requested_by", sa.String(128), nullable=True),
        sa.Column("error_message", sa.Text, nullable=True),
        sa.Column("stats", JSONB, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_ingestion_jobs_kb_id", "ingestion_jobs", ["kb_id"])

    # 导入任务条目表
    op.create_table(
        "ingestion_job_items",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("job_id", sa.Uuid(as_uuid=True), sa.ForeignKey("ingestion_jobs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("material_id", sa.Uuid(as_uuid=True), sa.ForeignKey("source_materials.id", ondelete="CASCADE"), nullable=False),
        sa.Column(
            "action",
            sa.Enum("create", "update", name="ingestion_job_item_action"),
            nullable=False,
            server_default="create",
        ),
    )
    op.create_index("ix_ingestion_job_items_job_id", "ingestion_job_items", ["job_id"])


def downgrade() -> None:
    op.drop_table("ingestion_job_items")
    op.drop_table("ingestion_jobs")

    op.execute("DROP TYPE IF EXISTS ingestion_job_item_action")
    op.execute("DROP TYPE IF EXISTS ingestion_status")

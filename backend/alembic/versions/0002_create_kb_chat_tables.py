"""创建核心业务表（知识库/资料/切片/会话/消息/运行/证据）。

Revision ID: 0002_create_kb_chat_tables
Revises: 0001_create_export_jobs
Create Date: 2025-12-22

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import ARRAY, JSONB

revision = "0002_create_kb_chat_tables"
down_revision = "0001_create_export_jobs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 知识库表
    op.create_table(
        "knowledge_bases",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("name", sa.String(64), nullable=False, unique=True),
        sa.Column("description", sa.String(500), nullable=True),
        sa.Column("tags", ARRAY(sa.Text), nullable=True),
        sa.Column(
            "status",
            sa.Enum("active", "archived", name="knowledge_base_status"),
            nullable=False,
            server_default="active",
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )

    # 资料表
    op.create_table(
        "source_materials",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("kb_id", sa.Uuid(as_uuid=True), sa.ForeignKey("knowledge_bases.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source_type", sa.Enum("upload", "url", "text", name="source_type"), nullable=False),
        sa.Column("title", sa.Text, nullable=False),
        sa.Column("uri", sa.Text, nullable=True),
        sa.Column("mime_type", sa.String(128), nullable=True),
        sa.Column("content_hash", sa.String(64), nullable=True),
        sa.Column("metadata", JSONB, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_source_materials_kb_id", "source_materials", ["kb_id"])
    op.create_index("ix_source_materials_kb_hash", "source_materials", ["kb_id", "content_hash"])

    # 文档切片表
    op.create_table(
        "document_chunks",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("kb_id", sa.Uuid(as_uuid=True), sa.ForeignKey("knowledge_bases.id", ondelete="CASCADE"), nullable=False),
        sa.Column("material_id", sa.Uuid(as_uuid=True), sa.ForeignKey("source_materials.id", ondelete="CASCADE"), nullable=False),
        sa.Column("chunk_index", sa.Integer, nullable=False),
        sa.Column("text", sa.Text, nullable=False),
        sa.Column("locator", JSONB, nullable=True),
        sa.Column("content_hash", sa.String(64), nullable=True),
        sa.Column("token_count", sa.Integer, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_document_chunks_kb_id", "document_chunks", ["kb_id"])
    op.create_index("ix_document_chunks_material_id", "document_chunks", ["material_id"])
    op.create_index("ix_document_chunks_kb_material_idx", "document_chunks", ["kb_id", "material_id", "chunk_index"])

    # 会话表
    op.create_table(
        "chat_sessions",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("session_type", sa.Enum("kb_chat", "general_chat", name="chat_session_type"), nullable=False),
        sa.Column("selected_kb_ids", ARRAY(sa.Uuid(as_uuid=True)), nullable=True),
        sa.Column("allow_external", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("mode", sa.Enum("single_agent", "multi_agent", name="agent_mode"), nullable=False),
        sa.Column("title", sa.String(256), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )

    # 消息表
    op.create_table(
        "chat_messages",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("session_id", sa.Uuid(as_uuid=True), sa.ForeignKey("chat_sessions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("role", sa.Enum("user", "assistant", "system", name="message_role"), nullable=False),
        sa.Column("content", sa.Text, nullable=False),
        sa.Column("meta", JSONB, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_chat_messages_session_id", "chat_messages", ["session_id"])

    # 智能体运行表
    op.create_table(
        "agent_runs",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("run_type", sa.Enum("kb_answer", "general_answer", "research", "evaluation_case", name="agent_run_type"), nullable=False),
        sa.Column("session_id", sa.Uuid(as_uuid=True), sa.ForeignKey("chat_sessions.id", ondelete="SET NULL"), nullable=True),
        sa.Column("question", sa.Text, nullable=False),
        sa.Column("selected_kb_ids", ARRAY(sa.Uuid(as_uuid=True)), nullable=True),
        sa.Column("allow_external", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("mode", sa.Enum("single_agent", "multi_agent", name="agent_mode", create_type=False), nullable=False),
        sa.Column("status", sa.Enum("running", "succeeded", "failed", "canceled", name="agent_run_status"), nullable=False, server_default="running"),
        sa.Column("stage_summaries", JSONB, nullable=True),
        sa.Column("final_output", sa.Text, nullable=True),
        sa.Column("metrics", JSONB, nullable=True),
        sa.Column("error_message", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_agent_runs_session_id", "agent_runs", ["session_id"])

    # 证据表
    op.create_table(
        "evidence",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("run_id", sa.Uuid(as_uuid=True), sa.ForeignKey("agent_runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source_kind", sa.Enum("kb", "external", name="evidence_source_kind"), nullable=False),
        sa.Column("kb_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("material_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("chunk_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("locator", JSONB, nullable=True),
        sa.Column("excerpt", sa.Text, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_evidence_run_id", "evidence", ["run_id"])


def downgrade() -> None:
    op.drop_table("evidence")
    op.drop_table("agent_runs")
    op.drop_table("chat_messages")
    op.drop_table("chat_sessions")
    op.drop_table("document_chunks")
    op.drop_table("source_materials")
    op.drop_table("knowledge_bases")

    op.execute("DROP TYPE IF EXISTS evidence_source_kind")
    op.execute("DROP TYPE IF EXISTS agent_run_status")
    op.execute("DROP TYPE IF EXISTS agent_run_type")
    op.execute("DROP TYPE IF EXISTS message_role")
    op.execute("DROP TYPE IF EXISTS agent_mode")
    op.execute("DROP TYPE IF EXISTS chat_session_type")
    op.execute("DROP TYPE IF EXISTS source_type")
    op.execute("DROP TYPE IF EXISTS knowledge_base_status")

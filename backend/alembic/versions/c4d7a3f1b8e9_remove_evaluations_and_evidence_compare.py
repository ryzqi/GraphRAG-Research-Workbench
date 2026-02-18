"""remove evaluations and evidence compare persistence artifacts

Revision ID: c4d7a3f1b8e9
Revises: 9b9a6f4f20d1
Create Date: 2026-02-18 20:10:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "c4d7a3f1b8e9"
down_revision = "9b9a6f4f20d1"
branch_labels = None
depends_on = None


def _replace_agent_run_type_enum(values: tuple[str, ...], temp_type_name: str) -> None:
    bind = op.get_bind()
    replacement = postgresql.ENUM(*values, name=temp_type_name)
    replacement.create(bind, checkfirst=True)

    op.execute(
        sa.text(
            f"ALTER TABLE agent_runs "
            f"ALTER COLUMN run_type TYPE {temp_type_name} "
            f"USING run_type::text::{temp_type_name}"
        )
    )

    old_enum = postgresql.ENUM(name="agent_run_type")
    old_enum.drop(bind, checkfirst=True)
    op.execute(sa.text(f"ALTER TYPE {temp_type_name} RENAME TO agent_run_type"))


def upgrade() -> None:
    bind = op.get_bind()

    op.execute(
        sa.text("DELETE FROM export_jobs WHERE run_id IN (SELECT id FROM evaluation_runs)")
    )
    op.execute(
        sa.text(
            "DELETE FROM export_jobs "
            "WHERE run_id IN (SELECT id FROM agent_runs WHERE run_type = 'evaluation_case')"
        )
    )
    op.execute(sa.text("DELETE FROM agent_runs WHERE run_type = 'evaluation_case'"))

    _replace_agent_run_type_enum(
        ("kb_answer", "general_answer", "research"),
        "agent_run_type_new",
    )

    op.drop_table("evaluation_runs")

    evaluation_status = postgresql.ENUM(
        "queued",
        "running",
        "succeeded",
        "failed",
        "canceled",
        name="evaluation_status",
    )
    evaluation_status.drop(bind, checkfirst=True)


def downgrade() -> None:
    bind = op.get_bind()

    _replace_agent_run_type_enum(
        ("kb_answer", "general_answer", "research", "evaluation_case"),
        "agent_run_type_with_evaluation_case",
    )

    evaluation_status = postgresql.ENUM(
        "queued",
        "running",
        "succeeded",
        "failed",
        "canceled",
        name="evaluation_status",
        create_type=False,
    )
    evaluation_status.create(bind, checkfirst=True)

    op.create_table(
        "evaluation_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("status", evaluation_status, nullable=False),
        sa.Column(
            "dataset",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column(
            "config",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column("related_session_ids", postgresql.ARRAY(sa.Uuid()), nullable=True),
        sa.Column("summary", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )

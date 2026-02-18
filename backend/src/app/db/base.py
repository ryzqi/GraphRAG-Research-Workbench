from __future__ import annotations

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


def import_all_models() -> None:
    """确保 Alembic 能发现所有模型。"""

    from app.models import (  # noqa: F401
        agent_run,
        chat_message,
        chat_session,
        document_chunk,
        evaluation_run,
        evidence,
        export_job,
        index_rebuild_job,
        ingestion_batch,
        ingestion_task_outbox,
        kb_bootstrap_job,
        kb_config_snapshot,
        knowledge_base,
        knowledge_update_proposal,
        research_artifact,
        research_event,
        research_session,
        research_report,
        source_material,
        tool_extension,
    )

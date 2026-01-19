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
        ingestion_job,
        knowledge_base,
        knowledge_update_proposal,
        research_report,
        source_material,
        tool_extension,
        tool_invocation,
    )

"""Research artifact store。"""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.research_artifact import ResearchArtifact
from app.models.research_session import ResearchSession


class ResearchArtifactStore:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def upsert(
        self,
        *,
        session: ResearchSession,
        artifact_key: str,
        content_text: str | None = None,
        content_json: dict[str, Any] | list[Any] | None = None,
        source_type: str | None = None,
        source_provider: str | None = None,
        retrieval_method: str | None = None,
        origin_url: str | None = None,
    ) -> ResearchArtifact:
        existing = next(
            (artifact for artifact in session.artifacts if artifact.artifact_key == artifact_key),
            None,
        )
        if existing is None:
            existing = ResearchArtifact(
                session=session,
                artifact_key=artifact_key,
            )
            self._db.add(existing)
        existing.content_text = content_text
        existing.content_json = content_json
        existing.source_type = source_type
        existing.source_provider = source_provider
        existing.retrieval_method = retrieval_method
        existing.origin_url = origin_url
        return existing

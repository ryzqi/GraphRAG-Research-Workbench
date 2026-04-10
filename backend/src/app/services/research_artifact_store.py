"""Research artifact store。"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.research_artifact import ResearchArtifact
from app.models.research_session import ResearchSession


def normalize_optional_artifact_text(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    return normalized or None


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
        artifacts_loaded = "artifacts" in session.__dict__
        existing = None
        if artifacts_loaded:
            loaded_artifacts = session.__dict__.get("artifacts") or []
            existing = next(
                (
                    artifact
                    for artifact in loaded_artifacts
                    if artifact.artifact_key == artifact_key
                ),
                None,
            )
        elif session.id is not None and callable(getattr(self._db, "execute", None)):
            stmt = select(ResearchArtifact).where(
                ResearchArtifact.session_id == session.id,
                ResearchArtifact.artifact_key == artifact_key,
            )
            existing = (await self._db.execute(stmt)).scalar_one_or_none()

        if existing is None:
            existing = ResearchArtifact(artifact_key=artifact_key)
            if (
                artifacts_loaded
                or session.id is None
                or not callable(getattr(self._db, "execute", None))
            ):
                existing.session = session
            else:
                existing.session_id = session.id
            self._db.add(existing)
        existing.content_text = normalize_optional_artifact_text(content_text)
        existing.content_json = content_json
        existing.source_type = normalize_optional_artifact_text(source_type)
        existing.source_provider = normalize_optional_artifact_text(source_provider)
        existing.retrieval_method = normalize_optional_artifact_text(
            retrieval_method
        )
        existing.origin_url = normalize_optional_artifact_text(origin_url)
        return existing

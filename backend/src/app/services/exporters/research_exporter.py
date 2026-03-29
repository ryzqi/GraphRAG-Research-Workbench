"""Research 导出器。"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.models.research_artifact import ResearchArtifact


class ResearchExporter:
    """直接从 research_artifacts 读取最终研究工件。"""

    async def export(self, session: AsyncSession, session_id: uuid.UUID) -> str:
        stmt = select(ResearchArtifact).where(ResearchArtifact.session_id == session_id)
        result = await session.execute(stmt)
        artifacts = list(result.scalars().all())
        artifact_by_key = {artifact.artifact_key: artifact for artifact in artifacts}
        available_keys = sorted(artifact_by_key.keys())

        missing_keys: list[str] = []
        report_md = artifact_by_key.get("report_md")
        report_json = artifact_by_key.get("report_json")
        if report_md is None or not str(report_md.content_text or "").strip():
            missing_keys.append("report_md")
        if report_json is None or not isinstance(report_json.content_json, dict):
            missing_keys.append("report_json")

        if missing_keys:
            raise AppError(
                code="ARTIFACT_INCOMPLETE",
                message="研究工件不完整，暂时无法导出",
                status_code=409,
                details={
                    "session_id": str(session_id),
                    "missing_artifact_keys": missing_keys,
                    "available_artifact_keys": available_keys,
                },
            )

        return str(report_md.content_text)

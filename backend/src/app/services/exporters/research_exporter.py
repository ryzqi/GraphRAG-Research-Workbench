"""Research 导出器。"""

from __future__ import annotations

from io import BytesIO
import uuid
from xml.sax.saxutils import escape

from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.platypus import Flowable, Paragraph, SimpleDocTemplate, Spacer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.models.research_artifact import ResearchArtifact

_PDF_FONT_NAME = "STSong-Light"


def _ensure_pdf_font() -> None:
    if _PDF_FONT_NAME in pdfmetrics.getRegisteredFontNames():
        return
    pdfmetrics.registerFont(UnicodeCIDFont(_PDF_FONT_NAME))


class ResearchExporter:
    """直接从 research_artifacts 读取最终研究工件。"""

    async def export(self, session: AsyncSession, session_id: uuid.UUID) -> bytes:
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

        assert report_md is not None
        return self._build_pdf(str(report_md.content_text))

    def _build_pdf(self, report_md: str) -> bytes:
        _ensure_pdf_font()
        buffer = BytesIO()
        document = SimpleDocTemplate(
            buffer,
            pagesize=A4,
            leftMargin=18 * mm,
            rightMargin=18 * mm,
            topMargin=18 * mm,
            bottomMargin=18 * mm,
        )
        styles = getSampleStyleSheet()
        body_style = ParagraphStyle(
            "ResearchExportBody",
            parent=styles["BodyText"],
            fontName=_PDF_FONT_NAME,
            fontSize=11,
            leading=17,
            wordWrap="CJK",
            spaceAfter=6,
        )
        heading_1_style = ParagraphStyle(
            "ResearchExportHeading1",
            parent=styles["Heading1"],
            fontName=_PDF_FONT_NAME,
            fontSize=19,
            leading=25,
            wordWrap="CJK",
            spaceAfter=10,
        )
        heading_2_style = ParagraphStyle(
            "ResearchExportHeading2",
            parent=styles["Heading2"],
            fontName=_PDF_FONT_NAME,
            fontSize=15,
            leading=21,
            wordWrap="CJK",
            spaceBefore=6,
            spaceAfter=8,
        )
        heading_3_style = ParagraphStyle(
            "ResearchExportHeading3",
            parent=styles["Heading3"],
            fontName=_PDF_FONT_NAME,
            fontSize=12,
            leading=18,
            wordWrap="CJK",
            spaceBefore=4,
            spaceAfter=6,
        )
        bullet_style = ParagraphStyle(
            "ResearchExportBullet",
            parent=body_style,
            leftIndent=12,
            firstLineIndent=-8,
        )

        story: list[Flowable] = []
        for raw_line in report_md.splitlines():
            line = raw_line.strip()
            if not line:
                if story and not isinstance(story[-1], Spacer):
                    story.append(Spacer(1, 4))
                continue
            if line.startswith("### "):
                story.append(Paragraph(escape(line[4:].strip()), heading_3_style))
                continue
            if line.startswith("## "):
                story.append(Paragraph(escape(line[3:].strip()), heading_2_style))
                continue
            if line.startswith("# "):
                story.append(Paragraph(escape(line[2:].strip()), heading_1_style))
                continue
            if line.startswith("- "):
                story.append(Paragraph(f"• {escape(line[2:].strip())}", bullet_style))
                continue
            story.append(Paragraph(escape(line), body_style))

        document.build(story)
        return buffer.getvalue()

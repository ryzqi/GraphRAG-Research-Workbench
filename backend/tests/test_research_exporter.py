from __future__ import annotations

from io import BytesIO
from types import SimpleNamespace
import uuid

import pytest
from pypdf import PdfReader

from app.services.exporters.research_exporter import ResearchExporter
from app.worker.tasks.export import _build_download_response_headers


class _FakeScalarResult:
    def __init__(self, artifacts: list[SimpleNamespace]) -> None:
        self._artifacts = artifacts

    def all(self) -> list[SimpleNamespace]:
        return list(self._artifacts)


class _FakeExecuteResult:
    def __init__(self, artifacts: list[SimpleNamespace]) -> None:
        self._artifacts = artifacts

    def scalars(self) -> _FakeScalarResult:
        return _FakeScalarResult(self._artifacts)


class _FakeSession:
    def __init__(self, artifacts: list[SimpleNamespace]) -> None:
        self._artifacts = artifacts

    async def execute(self, stmt: object) -> _FakeExecuteResult:
        del stmt
        return _FakeExecuteResult(self._artifacts)


def _build_artifact(
    artifact_key: str,
    *,
    content_text: str | None = None,
    content_json: dict[str, object] | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        artifact_key=artifact_key,
        content_text=content_text,
        content_json=content_json,
    )


@pytest.mark.asyncio
async def test_research_exporter_returns_pdf_bytes_with_report_content() -> None:
    session_id = uuid.uuid4()
    exporter = ResearchExporter()
    db = _FakeSession(
        [
            _build_artifact(
                "report_md",
                content_text=(
                    "# 研究报告\n\n"
                    "## 执行摘要\n"
                    "供应链压力正在向 HBM 和先进封装集中。\n\n"
                    "## 关键发现\n"
                    "- NVIDIA 仍保持生态优势。\n"
                ),
            ),
            _build_artifact(
                "report_json",
                content_json={
                    "question": "2026 年 AI 半导体供给格局",
                    "summary": "供应链压力正在向 HBM 和先进封装集中。",
                },
            ),
        ]
    )

    exported = await exporter.export(db, session_id)

    assert exported.startswith(b"%PDF-")

    extracted_text = PdfReader(BytesIO(exported)).pages[0].extract_text()
    assert "研究报告" in extracted_text
    assert "供应链压力正在向 HBM 和先进封装集中。" in extracted_text
    assert "NVIDIA 仍保持生态优势。" in extracted_text


def test_build_download_response_headers_for_research_pdf_attachment() -> None:
    session_id = uuid.UUID("11111111-2222-3333-4444-555555555555")

    headers = _build_download_response_headers(
        export_type="research",
        target_id=session_id,
        content_type="application/pdf",
        file_extension="pdf",
    )

    assert headers == {
        "response-content-type": "application/pdf",
        "response-content-disposition": (
            'attachment; filename="research-report-11111111-2222-3333-4444-555555555555.pdf"'
        ),
    }

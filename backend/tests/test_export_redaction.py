from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
import json
import uuid

from app.core.settings import Settings
from app.models.agent_run import AgentRunStatus, AgentRunType
from app.models.chat_message import MessageRole
from app.models.chat_session import AgentMode, ChatSessionType
from app.models.evidence import EvidenceSourceKind
from app.services.exporters.chat_exporter import ChatExporter
from app.services.exporters.research_exporter import ResearchExporter


def test_chat_exporter_redacts_sensitive_content() -> None:
    exporter = ChatExporter(settings=Settings(EXPORT_REDACTION_ENABLED=True))
    created_at = datetime(2026, 4, 20, tzinfo=timezone.utc)

    output = exporter._render_markdown(
        run=SimpleNamespace(
            run_type=AgentRunType.GENERAL_ANSWER,
            mode=AgentMode.SINGLE_AGENT,
            status=AgentRunStatus.SUCCEEDED,
            stage_summaries={
                "contact_email": "alice@example.com",
                "contact_phone": "13800138000",
                "credential": "secret-token",
            },
        ),
        run_id=uuid.UUID("11111111-1111-1111-1111-111111111111"),
        chat_session=SimpleNamespace(
            id=uuid.UUID("22222222-2222-2222-2222-222222222222"),
            session_type=ChatSessionType.GENERAL_CHAT,
            selected_kb_ids=None,
            allow_external=False,
        ),
        messages=[
            SimpleNamespace(
                role=MessageRole.USER,
                created_at=created_at,
                content="联系邮箱 alice@example.com，手机号 13800138000，身份证 110101199001011234",
            )
        ],
        evidence_list=[
            SimpleNamespace(
                source_kind=EvidenceSourceKind.EXTERNAL,
                kb_id=None,
                material_id=None,
                locator={
                    "email": "alice@example.com",
                    "token": "secret-token",
                },
                excerpt="请联系 13800138000",
            )
        ],
        exported_at=created_at,
    )

    assert "alice@example.com" not in output
    assert "13800138000" not in output
    assert "110101199001011234" not in output
    assert "secret-token" not in output
    assert "[REDACTED_EMAIL]" in output
    assert "[REDACTED_PHONE_NUMBER]" in output
    assert "[REDACTED_ID_CARD]" in output
    assert "***REDACTED***" in output
    summary_json = output.split("```json\n", 1)[1].split("\n```", 1)[0]
    parsed = json.loads(summary_json)
    assert parsed["contact_email"] == "[REDACTED_EMAIL]"
    assert parsed["contact_phone"] == "[REDACTED_PHONE_NUMBER]"
    assert parsed["credential"] == "***REDACTED***"


def test_research_exporter_redacts_report_markdown() -> None:
    exporter = ResearchExporter(settings=Settings(EXPORT_REDACTION_ENABLED=True))

    prepared = exporter._prepare_report_markdown(
        "# 报告\n联系方式：alice@example.com，手机号：13800138000，身份证：110101199001011234"
    )

    assert "alice@example.com" not in prepared
    assert "13800138000" not in prepared
    assert "110101199001011234" not in prepared
    assert "[REDACTED_EMAIL]" in prepared
    assert "[REDACTED_PHONE_NUMBER]" in prepared
    assert "[REDACTED_ID_CARD]" in prepared


def test_chat_exporter_redacts_phone_number_with_country_code() -> None:
    exporter = ChatExporter(settings=Settings(EXPORT_REDACTION_ENABLED=True))
    created_at = datetime(2026, 4, 20, tzinfo=timezone.utc)

    output = exporter._render_markdown(
        run=SimpleNamespace(
            run_type=AgentRunType.GENERAL_ANSWER,
            mode=AgentMode.SINGLE_AGENT,
            status=AgentRunStatus.SUCCEEDED,
            stage_summaries=None,
        ),
        run_id=uuid.UUID("33333333-3333-3333-3333-333333333333"),
        chat_session=None,
        messages=[
            SimpleNamespace(
                role=MessageRole.USER,
                created_at=created_at,
                content="请拨打 +86 13800138000 联系我",
            )
        ],
        evidence_list=[],
        exported_at=created_at,
    )

    assert "+86 13800138000" not in output
    assert "[REDACTED_PHONE_NUMBER]" in output

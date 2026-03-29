from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.schemas.research import (
    ResearchCanonicalCitation,
    ResearchEventEnvelope,
    ResearchPlanSnapshot,
    ResearchResumeRequest,
    ResearchSourceTarget,
    ResearchStreamResumeParams,
)


def test_research_plan_snapshot_supports_brief_and_target_sources() -> None:
    snapshot = ResearchPlanSnapshot(
        research_brief="对 2024-2026 年 Deep Agents 深度研究架构做对比",
        complexity="comparative",
        summary="先看论文与官方实现，再补网页上下文。",
        target_sources=[ResearchSourceTarget.PAPER, ResearchSourceTarget.WEB],
        subtasks=[
            {
                "title": "论文基线",
                "description": "收集论文系统设计",
                "target_sources": ["paper"],
            }
        ],
        budget_guidance="优先论文，必要时补网页。",
        confirmation_required=True,
    )

    assert snapshot.research_brief.startswith("对 2024-2026 年")
    assert snapshot.target_sources == [
        ResearchSourceTarget.PAPER,
        ResearchSourceTarget.WEB,
    ]
    assert snapshot.subtasks[0].target_sources == [ResearchSourceTarget.PAPER]
    assert snapshot.confirmation_required is True


def test_research_event_envelope_requires_minimum_stream_fields() -> None:
    event = ResearchEventEnvelope(
        event_id="evt-001",
        sequence=1,
        timestamp=datetime.now(timezone.utc),
        event_type="research.plan.created",
        session_id=uuid4(),
        phase="planner",
        namespace="main",
        payload={"summary": "plan ready"},
        trace_id="trace-123",
    )

    assert event.sequence == 1
    assert event.namespace == "main"

    with pytest.raises(ValidationError):
        ResearchEventEnvelope(
            event_id="evt-002",
            sequence=0,
            timestamp=datetime.now(timezone.utc),
            event_type="research.plan.created",
            session_id=uuid4(),
            phase="planner",
            namespace="",
            payload={},
            trace_id=None,
        )


def test_resume_cursor_prefers_last_event_id_over_explicit_resume_parameter() -> None:
    params = ResearchStreamResumeParams(resume_from_event_id="evt-explicit")

    assert params.effective_after_event_id(last_event_id="evt-header") == "evt-header"
    assert params.effective_after_event_id(last_event_id=None) == "evt-explicit"


def test_resume_request_requires_non_empty_idempotency_key() -> None:
    payload = ResearchResumeRequest(idempotency_key="resume-001", resume_from_event_id="evt-9")

    assert payload.idempotency_key == "resume-001"
    assert payload.resume_from_event_id == "evt-9"

    with pytest.raises(ValidationError):
        ResearchResumeRequest(idempotency_key="  ")


def test_canonical_citation_supports_provider_and_paper_metadata() -> None:
    citation = ResearchCanonicalCitation(
        source_type="paper",
        source_provider="arxiv",
        retrieval_method="fetch",
        source_id="arxiv:2501.00001",
        title="Deep Research Agents",
        url="https://arxiv.org/abs/2501.00001",
        origin_url="https://arxiv.org/abs/2501.00001",
        arxiv_id="2501.00001",
        authors=["Alice", "Bob"],
        published_at=datetime(2026, 3, 29, tzinfo=timezone.utc),
        pdf_url="https://arxiv.org/pdf/2501.00001.pdf",
    )

    assert citation.source_provider == "arxiv"
    assert citation.authors == ["Alice", "Bob"]

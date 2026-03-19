from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.models.agent_run import AgentRun, AgentRunStatus, AgentRunType
from app.models.chat_session import AgentMode
from app.services import kb_chat_service as kb_chat_service_module
from app.services.kb_chat_service import KbChatService


def _build_service() -> KbChatService:
    service = object.__new__(KbChatService)
    now = datetime.now(UTC)

    async def _refresh(obj: object) -> None:
        if getattr(obj, "id", None) is None:
            setattr(obj, "id", uuid.uuid4())
        if getattr(obj, "created_at", None) is None:
            setattr(obj, "created_at", now)

    service._db = SimpleNamespace(
        add=lambda _obj: None,
        commit=AsyncMock(),
        refresh=AsyncMock(side_effect=_refresh),
    )
    service._settings = SimpleNamespace(
        memory_enabled=False,
        kb_chat_gray_release_auto_rollback_enabled=False,
    )
    service._summary_service = SimpleNamespace(
        maybe_update_summary=AsyncMock(return_value=None)
    )
    service._compute_route_consistency = lambda **_: 1.0
    service._compute_final_state_consistency = lambda **_: 1.0
    service._compute_clarification_consistency = lambda **_: 1.0
    service._compute_p95_latency_increase_pct = AsyncMock(return_value=0.0)
    service._build_gray_release_gate = lambda _metrics: {"pass": True}
    service._persist_gray_release_anomaly_sample = lambda **_: None
    service._semantic_cache_skip_reason = lambda **_: "test_skip"
    return service


def test_append_citation_sources_uses_shared_stable_sort_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _record_sort_key(citation_id: str) -> tuple[int, str]:
        return (0 if citation_id == "S2" else 1, citation_id)

    monkeypatch.setattr(
        kb_chat_service_module,
        "stable_citation_sort_key",
        _record_sort_key,
        raising=False,
    )

    result = KbChatService._append_citation_sources(
        "结论[S2][S1]",
        citation_catalog={
            "S1": {"citation_id": "S1"},
            "S2": {"citation_id": "S2"},
        },
        include_reference_section=True,
    )

    assert result.startswith("结论[S2][S1]")
    assert "[S2] 资料1" in result
    assert "[S1] 资料2" in result


@pytest.mark.asyncio
async def test_finalize_run_does_not_fallback_to_retrieval_results_without_structured_evidence() -> None:
    service = _build_service()
    now = datetime.now(UTC)
    session = SimpleNamespace(
        id=uuid.uuid4(),
        selected_kb_ids=[],
        allow_external=False,
        mode=AgentMode.SINGLE_AGENT,
    )
    run = AgentRun(
        id=uuid.uuid4(),
        run_type=AgentRunType.KB_ANSWER,
        session_id=session.id,
        question="问题",
        selected_kb_ids=[],
        allow_external=False,
        mode=AgentMode.SINGLE_AGENT,
        status=AgentRunStatus.RUNNING,
        created_at=now,
        started_at=now,
    )
    response = await service._finalize_run(
        session=session,
        run=run,
        kb_chat_config=SimpleNamespace(),
        started_at=now,
        answer="根据现有资料无法回答该问题（未检索到相关证据）。",
        final_evidence_items=[],
        final_citation_catalog={},
        stage_summaries={},
        metrics={},
        status=AgentRunStatus.SUCCEEDED,
        terminal_reason="no_evidence",
        clarification_payload=None,
        reflection=None,
        query_strategy="direct",
        routing_decisions={},
    )

    assert response.evidence == []
    assert response.metrics["evidence_count"] == 0
    assert response.metrics["citation_ids"] == []

from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy import UniqueConstraint

from app.models.research_artifact import ResearchArtifact
from app.models.research_event import ResearchEvent
from app.models.research_session import ResearchSession, ResearchSessionStatus


def _has_unique_constraint(table, *column_names: str) -> bool:
    expected = tuple(column_names)
    for constraint in table.constraints:
        if isinstance(constraint, UniqueConstraint):
            columns = tuple(column.name for column in constraint.columns)
            if columns == expected:
                return True
    return False


def test_research_session_exposes_runtime_state_machine_fields() -> None:
    session_table = ResearchSession.__table__

    assert session_table.c.thread_id.unique is True
    assert session_table.c.thread_id.nullable is False
    assert session_table.c.planner_phase.nullable is True
    assert session_table.c.runtime_phase.nullable is True
    assert session_table.c.finalizer_phase.nullable is True
    assert session_table.c.last_event_sequence.nullable is False


def test_terminal_research_session_states_are_irreversible() -> None:
    session = ResearchSession(
        question="对比 deep agents research runtime 方案",
        selected_kb_ids=[],
        allow_external=True,
        status=ResearchSessionStatus.FINAL,
        thread_id="research-session-1",
    )

    with pytest.raises(ValueError, match="终态"):
        session.transition_to(ResearchSessionStatus.RUNNING)


def test_research_event_enforces_session_scoped_uniqueness_and_namespace_contract() -> None:
    event_table = ResearchEvent.__table__

    assert _has_unique_constraint(event_table, "session_id", "event_id")
    assert _has_unique_constraint(event_table, "session_id", "sequence")
    assert event_table.c.namespace.nullable is False
    assert event_table.c.namespace.type.length == 255


def test_research_artifact_enforces_session_scoped_artifact_key_uniqueness() -> None:
    artifact_table = ResearchArtifact.__table__

    assert _has_unique_constraint(artifact_table, "session_id", "artifact_key")


def test_research_session_transition_to_same_status_is_idempotent() -> None:
    session = ResearchSession(
        id=uuid4(),
        question="当前研究会话是否允许同态迁移",
        selected_kb_ids=[],
        allow_external=False,
        status=ResearchSessionStatus.CREATED,
        thread_id="research-session-2",
    )

    session.transition_to(ResearchSessionStatus.CREATED)

    assert session.status == ResearchSessionStatus.CREATED


def test_research_session_status_allows_clarifying_before_confirmation() -> None:
    assert ResearchSessionStatus.PLANNING.can_transition_to(ResearchSessionStatus.CLARIFYING)
    assert ResearchSessionStatus.CLARIFYING.can_transition_to(
        ResearchSessionStatus.AWAITING_CONFIRMATION
    )
    assert not ResearchSessionStatus.CLARIFYING.can_transition_to(ResearchSessionStatus.RUNNING)

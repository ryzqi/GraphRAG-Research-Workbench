"""Research 事件回放与一致性检查。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from app.models.research_session import ResearchSession, ResearchSessionStatus
from app.schemas.research import ResearchEventEnvelope


@dataclass(slots=True, frozen=True)
class ResearchReplayState:
    status: ResearchSessionStatus
    last_event_id: str | None
    last_sequence: int
    event_count: int
    sequence_gaps: list[int]
    trace_ids: list[str]
    namespaces: list[str]
    lc_agent_names: list[str]


def replay_research_session(
    events: Sequence[ResearchEventEnvelope],
) -> ResearchReplayState:
    ordered = sorted(events, key=lambda item: (item.sequence, item.event_id))
    status = ResearchSessionStatus.CREATED
    last_event_id: str | None = None
    last_sequence = 0
    sequence_gaps: list[int] = []
    trace_ids: set[str] = set()
    namespaces: set[str] = set()
    lc_agent_names: set[str] = set()

    for event in ordered:
        if event.sequence > last_sequence + 1:
            sequence_gaps.extend(range(last_sequence + 1, event.sequence))
        last_sequence = max(last_sequence, event.sequence)
        last_event_id = event.event_id
        if event.trace_id:
            trace_ids.add(event.trace_id)
        namespaces.add(event.namespace)
        if event.lc_agent_name:
            lc_agent_names.add(event.lc_agent_name)
        status = _next_status(status=status, event_type=event.event_type)

    return ResearchReplayState(
        status=status,
        last_event_id=last_event_id,
        last_sequence=last_sequence,
        event_count=len(ordered),
        sequence_gaps=sequence_gaps,
        trace_ids=sorted(trace_ids),
        namespaces=sorted(namespaces),
        lc_agent_names=sorted(lc_agent_names),
    )


def evaluate_research_replay_consistency(
    *,
    session: ResearchSession,
    events: Sequence[ResearchEventEnvelope],
) -> dict[str, object]:
    replay_state = replay_research_session(events)
    violations: list[str] = []
    if replay_state.status != session.status:
        violations.append("status_mismatch")
    if replay_state.last_sequence != int(session.last_event_sequence or 0):
        violations.append("last_sequence_mismatch")
    if replay_state.sequence_gaps:
        violations.append("sequence_gap")
    if session.trace_id and replay_state.trace_ids and replay_state.trace_ids != [session.trace_id]:
        violations.append("trace_id_mismatch")

    return {
        "pass": len(violations) == 0,
        "violations": violations,
        "replay_status": replay_state.status.value,
        "session_status": session.status.value,
        "last_event_id": replay_state.last_event_id,
        "last_sequence": replay_state.last_sequence,
        "expected_last_sequence": int(session.last_event_sequence or 0),
        "sequence_gaps": list(replay_state.sequence_gaps),
        "trace_ids": list(replay_state.trace_ids),
        "namespaces": list(replay_state.namespaces),
        "lc_agent_names": list(replay_state.lc_agent_names),
    }


def _next_status(
    *,
    status: ResearchSessionStatus,
    event_type: str,
) -> ResearchSessionStatus:
    mapping = {
        "research.plan.created": ResearchSessionStatus.PLANNING,
        "research.run.started": ResearchSessionStatus.RUNNING,
        "research.run.interrupted": ResearchSessionStatus.INTERRUPTED,
        "research.run.resume_requested": ResearchSessionStatus.RESUMING,
        "research.finalizer.started": ResearchSessionStatus.FINALIZING,
        "research.final.completed": ResearchSessionStatus.FINAL,
        "research.run.failed": ResearchSessionStatus.FAILED,
    }
    return mapping.get(event_type, status)

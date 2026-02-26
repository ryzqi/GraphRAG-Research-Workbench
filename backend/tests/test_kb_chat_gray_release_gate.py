from __future__ import annotations

from app.services.kb_chat_service import KbChatService


def test_compute_route_consistency_detects_invalid_route() -> None:
    rate = KbChatService._compute_route_consistency(
        {
            "complexity_router": {"goto": "prepare_messages"},
            "doc_grader": {"goto": "unknown"},
            "answer_subgraph": {"next_step": "finalize"},
        }
    )
    assert rate < 100.0


def test_compute_clarification_consistency_requires_clarify_force_exit() -> None:
    rate = KbChatService._compute_clarification_consistency(
        {
            "clarification_pending": {"pending": True},
            "force_exit": {"reason": "clarify", "clarification_payload": {"q": "x"}},
        }
    )
    assert rate == 100.0


def test_gray_release_gate_flags_threshold_violations() -> None:
    gate = KbChatService._build_gray_release_gate(
        {
            "route_consistency_rate": 99.4,
            "final_state_consistency_rate": 98.9,
            "clarification_consistency_rate": 100.0,
            "p95_latency_increase_pct": 12.0,
            "protocol_required_field_drift_rate": 0.1,
        }
    )
    assert gate["pass"] is False
    assert "route_consistency_rate" in gate["violations"]
    assert "final_state_consistency_rate" in gate["violations"]
    assert "p95_latency_increase_pct" in gate["violations"]
    assert "protocol_required_field_drift_rate" in gate["violations"]

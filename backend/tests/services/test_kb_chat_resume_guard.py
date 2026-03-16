from __future__ import annotations

from types import SimpleNamespace

from app.api.v1.endpoints.chats import _has_pending_kb_clarification


def test_has_pending_kb_clarification_reads_metrics_flag() -> None:
    run = SimpleNamespace(
        metrics={"clarification_pending": True},
        stage_summaries=None,
    )

    assert _has_pending_kb_clarification(run) is True


def test_has_pending_kb_clarification_does_not_fall_back_to_stage_summaries() -> None:
    run = SimpleNamespace(
        metrics={},
        stage_summaries={"clarification_pending": {"pending": True}},
    )

    assert _has_pending_kb_clarification(run) is False

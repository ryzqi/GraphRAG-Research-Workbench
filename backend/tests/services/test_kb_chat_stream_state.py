from __future__ import annotations

import uuid

from app.models.agent_run import AgentRunStatus
from app.services.kb_chat_service import KbChatService


def test_calculate_stream_progress_counts_completed_and_skipped() -> None:
    progress = KbChatService._calculate_stream_progress(
        stage_status={
            "preprocess": "completed",
            "retrieve": "skipped",
            "judge": "failed",
        },
        run_status="running",
    )

    assert progress["completed"] == 2
    assert progress["total"] == 3
    assert progress["percent"] == 66.7


def test_build_stream_state_payload_contains_stage_metadata() -> None:
    run_id = uuid.uuid4()
    payload = KbChatService._build_stream_state_payload(
        run_id=run_id,
        run_status="running",
        current_step_id="retrieve",
        current_node="retrieve",
        stage_status={
            "preprocess": "completed",
            "retrieve": "started",
        },
        stage_attempts={"retrieve": 2},
        state_version=3,
        active_path=["merge_context", "retrieve"],
        last_good_answer="candidate answer",
        degrade_reason=None,
    )

    assert payload["run_id"] == str(run_id)
    assert payload["run_status"] == "running"
    assert payload["current_step_id"] == "retrieve"
    assert payload["current_step_label"] == "知识检索"
    assert payload["current_step_status"] == "started"
    assert payload["current_node"] == "retrieve"
    assert payload["attempt"] == 2
    assert payload["state_version"] == 3
    assert payload["active_path"] == ["merge_context", "retrieve"]
    assert payload["last_good_answer"] == "candidate answer"
    assert payload["degrade_reason"] is None
    assert payload["progress"] == {"completed": 1, "total": 2, "percent": 50.0}
    assert isinstance(payload["ts"], str) and payload["ts"]


def test_resolve_terminal_run_status_marks_force_exit_without_answer_as_failed() -> None:
    status, message = KbChatService._resolve_terminal_run_status(
        stage_summaries={
            "force_exit": {
                "reason": "max_retrieval_retries",
                "answer_passed": False,
            }
        },
        answer="根据现有资料无法回答该问题（已停止重试）。",
    )

    assert status == AgentRunStatus.FAILED
    assert message == "根据现有资料无法回答该问题（已停止重试）。"


def test_resolve_terminal_run_status_keeps_success_for_valid_force_exit_answer() -> None:
    status, message = KbChatService._resolve_terminal_run_status(
        stage_summaries={
            "force_exit": {
                "reason": "max_total_rounds",
                "answer_passed": True,
            }
        },
        answer="这是基于检索证据的最终回答 [1]。",
    )

    assert status == AgentRunStatus.SUCCEEDED
    assert message is None


def test_resolve_terminal_run_status_keeps_success_for_best_answer_fallback() -> None:
    status, message = KbChatService._resolve_terminal_run_status(
        stage_summaries={
            "force_exit": {
                "reason": "max_retrieval_retries",
                "answer_passed": False,
                "used_best_answer": True,
            }
        },
        answer="这是中途校验通过的回答 [1]。",
    )

    assert status == AgentRunStatus.SUCCEEDED
    assert message is None


def test_build_node_io_summary_extracts_query_rewrite_fields() -> None:
    summary = KbChatService._build_node_io_summary(
        node="transform_query",
        update={
            "normalized_query": "新的重写查询",
            "stage_summaries": {
                "transform_query": {
                    "rewritten": True,
                    "reason": "retry",
                    "latency_ms": 31,
                }
            },
        },
    )

    assert isinstance(summary, dict)
    assert summary["rewritten"] is True
    assert summary["reason"] == "retry"
    assert summary["query"] == "新的重写查询"

from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from langchain.messages import AIMessage, HumanMessage, SystemMessage

import app.services.kb_chat_service as kb_chat_service_module
from app.agents.kb_chat_contracts import STATE_SCHEMA_V3
from app.models.agent_run import AgentRun, AgentRunStatus, AgentRunType
from app.models.chat_session import AgentMode
from app.core.checkpoint import CheckpointManager
from app.services.kb_chat_service import KbChatService
from app.services.streaming import StreamState


def test_sanitize_checkpoint_state_filters_transient_fields_and_tool_messages() -> None:
    plan = KbChatService._sanitize_checkpoint_state(
        {
            "messages": [
                SystemMessage(content="system"),
                HumanMessage(content="question"),
                AIMessage(
                    content="tool-call",
                    additional_kwargs={"tool_calls": [{"id": "call-1"}]},
                ),
                AIMessage(content="clarification"),
            ],
            "user_input": "stale question",
            "pending_tool_calls": [{"name": "kb_retrieve"}],
            "reflection": {"action": "clarify"},
            "preprocess_next": "force_exit",
            "answer_review_runs": [{"judge": "stale"}],
        }
    )

    assert [message.content for message in plan.messages] == [
        "system",
        "question",
        "clarification",
    ]
    assert set(plan.reset_fields) >= {
        "user_input",
        "pending_tool_calls",
        "reflection",
        "preprocess_next",
        "answer_review_runs",
    }
    assert set(plan.legacy_fields) == {"messages_filtered", "schema_version"}


def test_checkpoint_state_summary_redacts_raw_channel_values() -> None:
    summary = CheckpointManager.summarize_channel_values(
        {
            "schema_version": STATE_SCHEMA_V3,
            "messages": [HumanMessage(content="q"), AIMessage(content="a")],
            "stage_summaries": {
                "checkpoint_restore": {
                    "checkpoint_restore_applied": True,
                    "checkpoint_restore_source_checkpoint_id": "cp-1",
                    "checkpoint_restore_reset_fields": ["reflection"],
                    "checkpoint_restore_legacy_fields": [],
                },
                "force_exit": {"reason": "clarify"},
            },
            "metrics": {"context": {"history": 2}},
            "loop_counts": {
                "total_rounds": 1,
                "retrieval_retries": 0,
                "generation_retries": 0,
            },
            "final_answer": "should not leak",
        }
    )

    assert summary["message_count"] == 2
    assert summary["schema_version"] == STATE_SCHEMA_V3
    assert "final_answer" in summary["field_names"]
    assert "force_exit" in summary["stage_summary_keys"]
    assert summary["checkpoint_restore"]["checkpoint_restore_source_checkpoint_id"] == "cp-1"
    assert "final_answer" not in summary


def test_build_node_io_summary_for_answer_subgraph_prefers_canonical_routing() -> None:
    summary = KbChatService._build_node_io_summary(
        node="answer_subgraph",
        update={
            "degrade_reason": "review_failed",
            "routing_decisions": {
                "answer_subgraph": {
                    "next_node": "transform_query",
                    "reason": "missing_citations",
                }
            },
            "stage_summaries": {
                "answer_subgraph": {
                    "next_step": "force_exit",
                    "reason": "stale_stage_reason",
                }
            },
        },
    )

    assert summary == {
        "next_node": "transform_query",
        "reason": "missing_citations",
        "degrade_reason": "review_failed",
    }


def test_stream_state_apply_update_tracks_kb_chat_canonical_fields() -> None:
    state = StreamState()

    state.apply_update(
        {
            "draft_answer": "草稿答案",
            "final_answer": "最终答案",
            "clarification_payload": {"question": "请补充时间范围"},
            "confidence_score": 0.72,
            "confidence_level": "medium",
            "reflection": {"action": "force_exit", "reason": "severe_conflict"},
            "degrade_reason": "review_failed",
            "routing_decisions": {
                "answer_subgraph": {"next_node": "force_exit", "reason": "review_failed"}
            },
        }
    )

    assert state.draft_answer == "草稿答案"
    assert state.final_answer == "最终答案"
    assert state.clarification_payload == {"question": "请补充时间范围"}
    assert state.confidence_score == 0.72
    assert state.confidence_level == "medium"
    assert state.reflection == {"action": "force_exit", "reason": "severe_conflict"}
    assert state.degrade_reason == "review_failed"
    assert state.routing_decisions == {
        "answer_subgraph": {"next_node": "force_exit", "reason": "review_failed"}
    }


def test_extract_clarification_pending_uses_canonical_payload() -> None:
    message, payload = KbChatService._extract_clarification_pending(
        clarification_payload={
            "question": "请补充时间范围",
            "reason_code": "missing_time",
            "confidence": 0.91,
            "model_reason": None,
            "slots": [],
            "suggested_answers": [],
        },
        answer="",
        reflection={"action": "clarify", "reason": "ambiguous_query"},
    )

    assert message == "请补充时间范围"
    assert payload is not None
    assert payload.question == "请补充时间范围"
    assert payload.reason_code == "missing_time"


def test_resolve_preferred_evidence_round_uses_best_answer_meta_over_stage_summary() -> None:
    result = KbChatService._resolve_preferred_evidence_round(
        best_answer_meta={"retrieval_round": 2},
        loop_counts={"retrieval_retries": 5},
    )

    assert result == 2


def test_extract_last_good_answer_prefers_stream_state_canonical_answer_fields() -> None:
    stream_state = StreamState(
        final_answer="最终答案 [S1]",
        draft_answer="草稿答案 [S1]",
        best_answer="最佳答案 [S1]",
    )

    answer, source = KbChatService._extract_last_good_answer(
        answer="",
        stream_state=stream_state,
    )

    assert answer == "最终答案 [S1]"
    assert source == "stream_state.final_answer"


def test_semantic_cache_skip_reason_uses_canonical_reflection_reason() -> None:
    reason = KbChatService._semantic_cache_skip_reason(
        clarification_payload=None,
        routing_decisions={
            "answer_subgraph": {"next_node": "force_exit", "reason": "severe_conflict"}
        },
        reflection={"action": "none", "reason": "passed", "review_passed": True},
        degrade_reason=None,
        answer="这是一个普通回答。",
    )

    assert reason == "severe_conflict"


def test_compute_route_consistency_uses_canonical_query_strategy_and_routing() -> None:
    score = KbChatService._compute_route_consistency(
        query_strategy="decomposition",
        routing_decisions={
            "doc_gate": {"next_node": "answer_subgraph"},
            "answer_subgraph": {"next_node": "confidence_calibrate"},
        },
    )

    assert score == 100.0


def test_compute_final_state_consistency_uses_canonical_terminal_reason() -> None:
    score = KbChatService._compute_final_state_consistency(
        routing_decisions={"answer_subgraph": {"next_node": "force_exit"}},
        terminal_reason="severe_conflict",
    )

    assert score == 100.0


def test_compute_final_state_consistency_accepts_preprocess_force_exit_route() -> None:
    score = KbChatService._compute_final_state_consistency(
        routing_decisions={
            "preprocess": {
                "next_node": "force_exit",
                "action": "clarify",
                "reason": "clarify",
            }
        },
        terminal_reason="clarify",
    )

    assert score == 100.0


def test_resolve_terminal_reason_ignores_non_terminal_pass_reason() -> None:
    reason = KbChatService._resolve_terminal_reason(
        reflection={"action": "none", "reason": "passed", "review_passed": True},
    )

    assert reason is None


def test_resolve_terminal_reason_prefers_canonical_routing_reason() -> None:
    reason = KbChatService._resolve_terminal_reason(
        routing_decisions={
            "answer_subgraph": {
                "next_node": "force_exit",
                "action": "force_exit",
                "reason": "severe_conflict",
            }
        },
        reflection={"action": "none", "reason": "passed", "review_passed": True},
    )

    assert reason == "severe_conflict"


def test_resolve_terminal_run_status_ignores_stale_review_passed_for_force_exit() -> None:
    status, message = KbChatService._resolve_terminal_run_status(
        answer="候选答案 [S1]",
        routing_decisions={
            "answer_subgraph": {
                "next_node": "force_exit",
                "action": "force_exit",
                "reason": "severe_conflict",
            }
        },
        reflection={"action": "none", "reason": "passed", "review_passed": True},
        best_answer="候选答案 [S1]",
    )

    assert status == AgentRunStatus.FAILED
    assert message == kb_chat_service_module.resolve_kb_refusal_answer(
        reason="severe_conflict"
    )


def test_compute_clarification_consistency_uses_metrics_and_canonical_payload() -> None:
    score = KbChatService._compute_clarification_consistency(
        metrics={"clarification_pending": True},
        clarification_payload={"question": "请补充时间范围"},
        terminal_reason="clarify",
    )

    assert score == 100.0


def test_clarification_round_count_reads_metrics_instead_of_stage_summary() -> None:
    round_count = KbChatService._clarification_round_count(
        {"clarification_round": 2, "clarification_pending": True}
    )

    assert round_count == 2


@pytest.mark.asyncio
async def test_refresh_semantic_cache_hit_metrics_recomputes_gray_gate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _build_service(monkeypatch)
    service._compute_p95_latency_increase_pct = AsyncMock(return_value=-5.0)

    stage_summaries, metrics = await service._refresh_semantic_cache_hit_metrics(
        stage_summaries={
            "gray_release_gate": {
                "pass": False,
                "violations": ["final_state_consistency_rate"],
            }
        },
        metrics={
            "route_consistency_rate": 100.0,
            "final_state_consistency_rate": 0.0,
            "clarification_consistency_rate": 100.0,
            "protocol_required_field_drift_rate": 0.0,
        },
    )

    assert metrics["final_state_consistency_rate"] == 100.0
    assert metrics["p95_latency_increase_pct"] == -5.0
    assert metrics["gray_release_gate"]["pass"] is True
    assert stage_summaries["gray_release_gate"]["pass"] is True


class _FakeConfig:
    def model_dump(self, *, mode: str = "json") -> dict[str, int]:
        assert mode == "json"
        return {"retrieval_top_k": 5}


class _FakeGraph:
    def make_run_context(
        self,
        *,
        thread_id: str,
        state: dict[str, object],
        user_id: str | None = None,
        kb_ids: list[str] | None = None,
        runtime_config: dict[str, object] | None = None,
    ) -> dict[str, object]:
        return {
            "thread_id": thread_id,
            "user_id": user_id or "",
            "kb_ids": kb_ids or [],
            "runtime_config": runtime_config or {},
        }

    def compile(self, **_: object) -> object:
        return object()


def _build_service(monkeypatch: pytest.MonkeyPatch) -> KbChatService:
    service = object.__new__(KbChatService)
    service._db = SimpleNamespace(
        add=lambda _obj: None,
        flush=AsyncMock(),
        commit=AsyncMock(),
    )
    service._settings = SimpleNamespace(
        context_history_max_messages=8,
        memory_enabled=False,
    )
    service._summary_service = SimpleNamespace(load_latest_summary=AsyncMock(return_value=None))
    service._load_history = AsyncMock(return_value=[])
    service._context_builder = SimpleNamespace(
        build_history_messages=lambda **_: ([], {}, {}),
        build_metrics=lambda **_: {"history_messages": 0},
    )
    service._resolve_session_kb_chat_config = lambda _session: _FakeConfig()
    service._apply_gray_release_rollback_policy = AsyncMock(return_value=(_FakeConfig(), None))
    service._to_retrieval_overrides = lambda _config: {}
    service._retrieval = object()
    service._prompts = SimpleNamespace(render_with_few_shot=lambda _name: "system prompt")
    service._build_graph = lambda **_: _FakeGraph()

    monkeypatch.setattr(kb_chat_service_module, "build_kb_retrieve_tool", lambda **_: object())
    monkeypatch.setattr(
        kb_chat_service_module,
        "build_tool_registry",
        AsyncMock(return_value=([], {})),
    )
    monkeypatch.setattr(kb_chat_service_module, "create_chat_model", lambda **_: object())
    monkeypatch.setattr(kb_chat_service_module.StoreManager, "get_store", lambda: None)
    monkeypatch.setattr(kb_chat_service_module.CheckpointManager, "get_checkpointer", lambda: object())
    return service


@pytest.mark.asyncio
async def test_prepare_kb_chat_execution_rebuilds_fresh_state_without_checkpoint_transients(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _build_service(monkeypatch)
    session = SimpleNamespace(
        id=uuid.uuid4(),
        selected_kb_ids=[],
        allow_external=False,
        mode=AgentMode.SINGLE_AGENT,
        kb_chat_config=None,
    )
    checkpoint_tuple = SimpleNamespace(
        checkpoint={
            "id": "cp-fresh",
            "channel_values": {
                "messages": [
                    SystemMessage(content="stale system"),
                    HumanMessage(content="stale question"),
                    AIMessage(content="stale clarification"),
                ],
                "user_input": "stale question",
                "reflection": {"action": "clarify"},
                "preprocess_next": "force_exit",
            },
        }
    )
    monkeypatch.setattr(
        kb_chat_service_module.CheckpointManager,
        "get_state",
        AsyncMock(return_value=checkpoint_tuple),
    )

    execution = await service._prepare_kb_chat_execution(
        session=session,
        user_content="new question",
    )

    assert execution.state["user_input"] == "new question"
    assert [message.content for message in execution.state["messages"]] == [
        "system prompt",
        "new question",
    ]
    restore_audit = execution.state["stage_summaries"]["checkpoint_restore"]
    assert restore_audit["checkpoint_restore_applied"] is False
    assert restore_audit["checkpoint_restore_schema_supported"] is False
    assert set(restore_audit["checkpoint_restore_reset_fields"]) >= {
        "messages",
        "preprocess_next",
        "reflection",
        "user_input",
    }
    assert "memory_keys" not in execution.state
    assert "runtime_config" not in execution.state
    assert execution.run_context["user_id"] == f"anonymous:{session.id}"
    assert execution.resume_checkpoint_id is None


@pytest.mark.asyncio
async def test_prepare_kb_chat_execution_uses_checkpoint_messages_for_resume(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _build_service(monkeypatch)
    session = SimpleNamespace(
        id=uuid.uuid4(),
        selected_kb_ids=[],
        allow_external=False,
        mode=AgentMode.SINGLE_AGENT,
        kb_chat_config=None,
    )
    run = AgentRun(
        id=uuid.uuid4(),
        run_type=AgentRunType.KB_ANSWER,
        question="original question",
        mode=AgentMode.SINGLE_AGENT,
        status=AgentRunStatus.RUNNING,
    )
    checkpoint_tuple = SimpleNamespace(
        checkpoint={
            "id": "cp-resume",
            "channel_values": {
                "schema_version": STATE_SCHEMA_V3,
                "messages": [
                    SystemMessage(content="system prompt"),
                    HumanMessage(content="original question"),
                    AIMessage(content="请补充目标对象"),
                ],
                "pending_tool_calls": [{"name": "stale"}],
            },
        }
    )
    monkeypatch.setattr(
        kb_chat_service_module.CheckpointManager,
        "get_state",
        AsyncMock(return_value=checkpoint_tuple),
    )

    execution = await service._prepare_kb_chat_execution(
        session=session,
        user_content="目标对象是 A 产品",
        run=run,
    )

    assert [message.content for message in execution.state["messages"]] == [
        "system prompt",
        "original question",
        "请补充目标对象",
        "目标对象是 A 产品",
    ]
    restore_audit = execution.state["stage_summaries"]["checkpoint_restore"]
    assert restore_audit["checkpoint_restore_applied"] is True
    assert restore_audit["checkpoint_restore_schema_supported"] is True
    assert "pending_tool_calls" in restore_audit["checkpoint_restore_reset_fields"]
    assert execution.resume_checkpoint_id == str(run.id)


@pytest.mark.asyncio
async def test_prepare_kb_chat_execution_rejects_resume_from_unsupported_checkpoint_schema(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _build_service(monkeypatch)
    session = SimpleNamespace(
        id=uuid.uuid4(),
        selected_kb_ids=[],
        allow_external=False,
        mode=AgentMode.SINGLE_AGENT,
        kb_chat_config=None,
    )
    run = AgentRun(
        id=uuid.uuid4(),
        run_type=AgentRunType.KB_ANSWER,
        question="original question",
        mode=AgentMode.SINGLE_AGENT,
        status=AgentRunStatus.RUNNING,
    )
    checkpoint_tuple = SimpleNamespace(
        checkpoint={
            "id": "cp-unsupported",
            "channel_values": {
                "schema_version": "kb_chat_state_v999",
                "messages": [
                    SystemMessage(content="system prompt"),
                    HumanMessage(content="original question"),
                    AIMessage(content="请补充目标对象"),
                ],
            },
        }
    )
    monkeypatch.setattr(
        kb_chat_service_module.CheckpointManager,
        "get_state",
        AsyncMock(return_value=checkpoint_tuple),
    )

    execution = await service._prepare_kb_chat_execution(
        session=session,
        user_content="目标对象是 A 产品",
        run=run,
    )

    assert [message.content for message in execution.state["messages"]] == [
        "system prompt",
        "目标对象是 A 产品",
    ]
    restore_audit = execution.state["stage_summaries"]["checkpoint_restore"]
    assert restore_audit["checkpoint_restore_applied"] is False
    assert restore_audit["checkpoint_restore_schema_supported"] is False
    assert "schema_version" in restore_audit["checkpoint_restore_legacy_fields"]
    assert execution.resume_checkpoint_id == str(run.id)

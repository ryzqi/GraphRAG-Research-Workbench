import types
import uuid
from datetime import datetime, timezone

import pytest
from langchain.messages import AIMessage

from app.services import kb_chat_service as kb_chat_service_module
from app.services.kb_chat_service import KbChatService


class _DummyGraph:
    def __init__(self, result: dict):
        self._result = result

    async def run(self, *_args, **_kwargs):
        return self._result


def _build_service(*, max_rounds: int, graph_result: dict, run_stage_summaries: dict | None):
    service = KbChatService.__new__(KbChatService)
    service._settings = types.SimpleNamespace(kb_chat_max_clarification_rounds=max_rounds)

    async def _noop_commit():
        return None

    service._db = types.SimpleNamespace(commit=_noop_commit)

    run = types.SimpleNamespace(stage_summaries=run_stage_summaries)
    exec_ctx = types.SimpleNamespace(
        started_at=datetime.now(timezone.utc),
        thread_id="thread-1",
        run=run,
        kb_chat_config=types.SimpleNamespace(),
        history_usage={},
        history_truncation={},
        retrieval_results=[],
        evidence_draft_items_by_round={},
        retrieval_meta={},
        graph=_DummyGraph(graph_result),
        state={},
    )

    async def _fake_prepare(self, *, session, user_content, run=None):
        _ = (session, user_content, run)
        return exec_ctx

    def _fake_build_observability(
        self,
        *,
        kb_chat_config,
        history_usage,
        history_truncation,
        retrieval_meta,
        retrieval_results,
        base_metrics,
        base_stage_summaries,
    ):
        _ = (
            kb_chat_config,
            history_usage,
            history_truncation,
            retrieval_meta,
            retrieval_results,
        )
        return (
            base_metrics if isinstance(base_metrics, dict) else {},
            base_stage_summaries if isinstance(base_stage_summaries, dict) else {},
        )

    def _fake_apply_guardrail_metrics(self, *, metrics, stage_summaries, kb_scope):
        _ = (stage_summaries, kb_scope)
        return metrics

    def _fake_resolve_preferred_evidence_round(self, *, stage_summaries, loop_counts):
        _ = (stage_summaries, loop_counts)
        return None

    service._prepare_kb_chat_execution = types.MethodType(_fake_prepare, service)
    service._build_observability = types.MethodType(_fake_build_observability, service)
    service._apply_guardrail_metrics = types.MethodType(
        _fake_apply_guardrail_metrics, service
    )
    service._resolve_preferred_evidence_round = types.MethodType(
        _fake_resolve_preferred_evidence_round, service
    )
    return service, exec_ctx


def _clarify_stage_summary() -> dict:
    return {
        "force_exit": {
            "reason": "clarify",
            "clarification_payload": {
                "question": "请确认你指的是哪个对象？",
                "reason_code": "missing_entity",
                "confidence": 0.83,
                "model_reason": "missing target entity",
                "slots": [
                    {
                        "key": "entity",
                        "label": "对象",
                        "required": True,
                        "options": ["A", "B"],
                    }
                ],
                "suggested_answers": ["对象A", "对象B"],
            },
        }
    }


@pytest.mark.asyncio
async def test_answer_returns_pending_clarification_before_round_cap(monkeypatch):
    class _FakeCheckpointManager:
        @staticmethod
        def get_checkpointer():
            return object()

    monkeypatch.setattr(
        kb_chat_service_module, "CheckpointManager", _FakeCheckpointManager
    )

    graph_result = {
        "messages": [AIMessage(content="")],
        "metrics": {},
        "stage_summaries": _clarify_stage_summary(),
        "pending_tool_calls": None,
        "__interrupt__": None,
    }
    service, _exec_ctx = _build_service(
        max_rounds=1,
        graph_result=graph_result,
        run_stage_summaries=None,
    )

    captured: dict[str, object] = {}

    async def _fake_persist(
        self,
        *,
        session,
        run,
        started_at,
        message,
        pending_clarification,
        stage_summaries,
        metrics,
    ):
        _ = (session, run, started_at, stage_summaries, metrics)
        captured["message"] = message
        captured["pending_clarification"] = pending_clarification
        return "pending"

    async def _should_not_finalize(self, **_kwargs):
        raise AssertionError("_finalize_run should not be called before cap is reached")

    service._persist_clarification_pending = types.MethodType(_fake_persist, service)
    service._finalize_run = types.MethodType(_should_not_finalize, service)

    session = types.SimpleNamespace(id=uuid.uuid4(), selected_kb_ids=[])
    response = await service.answer(session=session, user_content="这个怎么做？")

    assert response == "pending"
    assert captured["message"] == "请确认你指的是哪个对象？"
    pending_payload = captured["pending_clarification"]
    assert pending_payload is not None
    assert pending_payload.reason_code == "missing_entity"
    assert pending_payload.question == "请确认你指的是哪个对象？"


@pytest.mark.asyncio
async def test_answer_degrades_when_clarification_round_cap_reached(monkeypatch):
    class _FakeCheckpointManager:
        @staticmethod
        def get_checkpointer():
            return object()

    monkeypatch.setattr(
        kb_chat_service_module, "CheckpointManager", _FakeCheckpointManager
    )

    graph_result = {
        "messages": [AIMessage(content="")],
        "metrics": {},
        "stage_summaries": _clarify_stage_summary(),
        "pending_tool_calls": None,
        "__interrupt__": None,
    }
    service, exec_ctx = _build_service(
        max_rounds=1,
        graph_result=graph_result,
        run_stage_summaries={"clarification_pending": {"round": 1}},
    )

    async def _should_not_persist(self, **_kwargs):
        raise AssertionError("_persist_clarification_pending should not be called at cap")

    captured: dict[str, object] = {}

    async def _fake_finalize(self, **kwargs):
        captured.update(kwargs)
        return "finalized"

    service._persist_clarification_pending = types.MethodType(_should_not_persist, service)
    service._finalize_run = types.MethodType(_fake_finalize, service)

    session = types.SimpleNamespace(id=uuid.uuid4(), selected_kb_ids=[])
    response = await service.answer(session=session, user_content="这个怎么做？")

    assert response == "finalized"
    assert captured["run"] is exec_ctx.run
    assert "关键歧义" in str(captured["answer"])
    stage_summaries = captured["stage_summaries"]
    assert isinstance(stage_summaries, dict)
    clarification_pending = stage_summaries.get("clarification_pending")
    assert isinstance(clarification_pending, dict)
    assert clarification_pending.get("max_rounds_reached") is True
    assert clarification_pending.get("round") == 1

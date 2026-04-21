from __future__ import annotations

import json

import pytest
from langchain.agents.middleware.types import ToolCallRequest
from langchain_core.messages import ToolMessage
from langgraph.prebuilt import ToolRuntime

from app.schemas.research_workspace import ResearchClaimMap, ResearchEvidenceLedger
from app.services.research_runtime_gate import build_breadth_gate_middleware
from app.services.research_runtime_types import ResearchRuntimeContext


def _build_request(*, tool_name: str, args: dict[str, object]) -> ToolCallRequest:
    runtime = ToolRuntime(
        state={},
        context=ResearchRuntimeContext(
            session_id="session-1",
            thread_id="thread-1",
            trace_id=None,
            target_sources=("web",),
            subagent_route=("claim-verifier",),
            workspace_root="/workspace",
            scratch_root="/scratch",
            plan_complexity="simple",
        ),
        config={"configurable": {"thread_id": "thread-1"}},
        stream_writer=lambda *_args, **_kwargs: None,
        tool_call_id="call-1",
        store=None,
    )
    return ToolCallRequest(
        tool_call={"id": "call-1", "name": tool_name, "args": args, "type": "tool_call"},
        tool=None,
        state={},
        runtime=runtime,
    )


@pytest.mark.asyncio
async def test_breadth_gate_async_passthrough_uses_async_handler() -> None:
    middleware = build_breadth_gate_middleware()
    request = _build_request(tool_name="web_search", args={"query": "latest papers"})
    observed_calls: list[str] = []

    async def handler(tool_request: ToolCallRequest) -> ToolMessage:
        observed_calls.append(str(tool_request.tool_call["name"]))
        return ToolMessage(
            content="ok",
            tool_call_id=str(tool_request.tool_call["id"]),
            name=str(tool_request.tool_call["name"]),
        )

    result = await middleware.awrap_tool_call(request, handler)

    assert observed_calls == ["web_search"]
    assert result.status == "success"
    assert result.content == "ok"


@pytest.mark.asyncio
async def test_breadth_gate_async_blocks_gated_subagent_before_handler(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    middleware = build_breadth_gate_middleware()
    request = _build_request(
        tool_name="task",
        args={"subagent_name": "section-writer"},
    )
    handler_called = False

    claim_map = ResearchClaimMap.model_validate(
        {
            "generated_at": "2026-01-01T00:00:00Z",
            "claims": [
                {
                    "claim_id": "claim-1",
                    "claim": "Need more evidence",
                    "status": "pending",
                    "confidence": "medium",
                    "independence_providers": [],
                    "supporting_evidence_ids": [],
                    "counter_evidence_ids": [],
                    "limitations": [],
                    "open_questions": [],
                }
            ],
        }
    )
    ledger = ResearchEvidenceLedger.model_validate(
        {"generated_at": "2026-01-01T00:00:00Z", "evidences": []}
    )

    monkeypatch.setattr(
        "app.services.research_runtime_gate._load_breadth_gate_inputs",
        lambda _runtime_context: (claim_map, ledger, "simple"),
    )

    async def handler(_tool_request: ToolCallRequest) -> ToolMessage:
        nonlocal handler_called
        handler_called = True
        return ToolMessage(content="should not run", tool_call_id="call-1")

    result = await middleware.awrap_tool_call(request, handler)

    assert handler_called is False
    assert result.status == "error"
    payload = json.loads(result.content)
    assert payload["ok"] is False
    assert payload["error"]["code"] == "BREADTH_GATE_NOT_READY"

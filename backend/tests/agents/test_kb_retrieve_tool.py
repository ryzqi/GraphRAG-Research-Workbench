from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.agents.kb_chat_agentic.reflection import _invoke_kb_retrieve
from app.agents.tools import kb_retrieve as kb_retrieve_tool_module
from app.agents.tools.kb_retrieve import KbRetrieveArgs


def _settings(**overrides: object) -> SimpleNamespace:
    defaults: dict[str, object] = {
        "app_env": "test",
        "kb_chat_json_safe_policy": "stringify",
        "memory_enabled": False,
        "retrieval_default_top_k": 5,
        "retrieval_max_top_k": 50,
        "kb_chat_max_total_rounds": 3,
        "kb_chat_parallel_retrieval_min_queries": 2,
        "kb_chat_parallel_retrieval_max_branches": 6,
        "kb_chat_parallel_retrieval_include_main": True,
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def _runtime_context(
    *,
    kb_ids: list[str] | None = None,
    runtime_config: dict[str, object] | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        context={
            "thread_id": "thread-ctx",
            "user_id": "user-ctx",
            "kb_ids": kb_ids or [],
            "runtime_config": runtime_config or {},
        },
        store=None,
    )


def test_kb_retrieve_args_schema_hides_private_request_id() -> None:
    schema = KbRetrieveArgs.model_json_schema()

    assert "request_id" not in schema.get("properties", {})


@pytest.mark.asyncio
async def test_invoke_kb_retrieve_keeps_request_id_private_while_recovering_meta() -> None:
    class _FakeKbTool:
        def __init__(self) -> None:
            self.calls: list[dict[str, object]] = []
            self._kb_invocation_meta_by_request_id: dict[str, dict[str, object]] = {}

        async def ainvoke(self, payload: dict[str, object]) -> str:
            self.calls.append(payload)
            current_request_id = getattr(
                kb_retrieve_tool_module,
                "current_kb_invocation_request_id",
            )()
            self._kb_invocation_meta_by_request_id[current_request_id] = {
                "evidence_items": [
                    {
                        "citation_id": "S1",
                        "excerpt": "命中证据。",
                    }
                ],
                "citation_catalog": [
                    {
                        "citation_id": "S1",
                        "title": "资料1",
                    }
                ],
            }
            return "[S1] 命中证据。"

    kb_tool = _FakeKbTool()

    context, reason, meta = await _invoke_kb_retrieve(
        state={
            "user_input": "问题",
            "loop_counts": {
                "total_rounds": 0,
                "retrieval_retries": 0,
                "generation_retries": 0,
            },
            "metrics": {},
            "stage_summaries": {},
        },
        query="问题",
        settings=_settings(),
        kb_tool=kb_tool,
        retrieval_round=0,
        runtime=_runtime_context(
            kb_ids=["kb-live"],
            runtime_config={"retrieval_top_k": 7},
        ),
    )

    assert reason is None
    assert context == "[S1] 命中证据。"
    assert meta["evidence_items"][0]["citation_id"] == "S1"
    assert "request_id" not in kb_tool.calls[0]

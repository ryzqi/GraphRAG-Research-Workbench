import types

import pytest
from langchain.messages import AIMessage, HumanMessage

from app.agents.kb_chat_agentic import preprocess, reflection
from app.agents.kb_chat_agentic.schemas import DocGraderDecision


class _Runtime:
    store = None


class _DummyKbTool:
    def __init__(self) -> None:
        self.payloads: list[dict] = []

    async def ainvoke(self, payload: dict):
        self.payloads.append(payload)
        return "[S1] evidence"


class _FakeRewriteService:
    seen_query: str | None = None

    def __init__(self, settings=None):
        _ = settings

    async def coref_rewrite(self, query: str, *, enabled: bool = True, timeout_seconds: float | None = None):
        _ = (enabled, timeout_seconds)
        type(self).seen_query = query
        return types.SimpleNamespace(query=query, reason=None)

    async def normalize_rewrite(self, query: str):
        return types.SimpleNamespace(query=query, rewritten=False)

    async def transform_query(
        self,
        query: str,
        *,
        reason: str,
        hint: str | None,
        timeout_seconds: float,
        enabled: bool,
    ):
        _ = (reason, hint, timeout_seconds, enabled)
        type(self).seen_query = query
        return types.SimpleNamespace(query=f"{query} refined")

    async def hyde(self, query: str, *, enabled: bool):
        _ = (query, enabled)
        return types.SimpleNamespace(queries=[], reason="disabled")


@pytest.fixture
def settings():
    return types.SimpleNamespace(
        app_env="test",
        kb_chat_json_safe_policy="fail_fast",
        memory_enabled=False,
        retrieval_query_rewrite_enabled=True,
        kb_chat_ambiguity_check_enabled=True,
        kb_chat_hyde_enabled=False,
        kb_chat_max_total_rounds=3,
        kb_chat_max_retrieval_retries=2,
        kb_chat_max_generation_retries=2,
        retrieval_default_top_k=5,
        kb_chat_grader_fail_policy="closed",
    )


@pytest.mark.asyncio
async def test_merge_context_structured_output_avoids_duplicate_user_question(settings):
    question = "What is the difference between CoT and ToT"
    state = {
        "messages": [
            HumanMessage(content=question),
            AIMessage(content="previous answer"),
            HumanMessage(content=question),
        ],
        "user_input": question,
        "metrics": {},
        "stage_summaries": {},
        "memory_keys": {},
    }

    result = await preprocess.merge_context(state, runtime=_Runtime(), settings=settings)

    assert result["rewrite_input_query"] == question
    assert isinstance(result["context_frame"], dict)
    assert result["context_frame"]["current_question"] == question
    merged = result["merged_context"]
    assert merged.count(question) == 1


@pytest.mark.asyncio
async def test_coref_rewrite_reads_rewrite_input_query_not_merged_context(monkeypatch, settings):
    monkeypatch.setattr(preprocess, "QueryRewriteService", _FakeRewriteService)

    state = {
        "rewrite_input_query": "plain query",
        "merged_context": "Recent dialogue\nUser: plain query\n\nUser question: plain query",
        "user_input": "fallback",
        "stage_summaries": {},
    }

    result = await preprocess.coref_rewrite(state, settings=settings)

    assert _FakeRewriteService.seen_query == "plain query"
    assert result["coref_query"] == "plain query"


@pytest.mark.asyncio
async def test_kb_retrieve_context_prefers_normalized_or_rewrite_query(monkeypatch, settings):
    monkeypatch.setattr(reflection, "get_settings", lambda: settings)
    kb_tool = _DummyKbTool()

    state = {
        "loop_counts": {"total_rounds": 0, "retrieval_retries": 0, "generation_retries": 0},
        "normalized_query": "normalized text",
        "coref_query": "coref text",
        "rewrite_input_query": "rewrite text",
        "merged_context": "should_not_use",
        "user_input": "fallback",
        "metrics": {},
        "stage_summaries": {},
        "memory_keys": {"kb_ids": ["kb1"]},
        "runtime_config": {},
    }

    _ = await reflection.kb_retrieve_context(state, settings=settings, kb_tool=kb_tool)

    assert kb_tool.payloads
    assert kb_tool.payloads[0]["query"] == "normalized text"


@pytest.mark.asyncio
async def test_doc_grader_uses_plain_query_not_merged_context(monkeypatch, settings):
    monkeypatch.setattr(reflection, "get_settings", lambda: settings)

    captured: dict[str, str] = {}

    async def _fake_judge_structured(*, chat_model, schema, system, user):
        _ = (chat_model, schema, system)
        captured["user"] = user
        return DocGraderDecision(
            passed=True,
            reason="passed",
            missing_constraints=[],
        ), None

    monkeypatch.setattr(reflection, "_judge_structured", _fake_judge_structured)

    state = {
        "normalized_query": "plain question",
        "merged_context": "should_not_use",
        "user_input": "fallback",
        "final_context": "[S1] evidence body",
        "reflection": {},
        "stage_summaries": {},
    }

    result = await reflection.doc_grader(state, settings=settings, chat_model=object())

    assert result["reflection"]["relevance_passed"] is True
    assert "Question: plain question" in captured["user"]


@pytest.mark.asyncio
async def test_transform_query_retry_uses_rewrite_input_query_when_needed(monkeypatch, settings):
    monkeypatch.setattr(reflection, "get_settings", lambda: settings)
    monkeypatch.setattr(reflection, "QueryRewriteService", _FakeRewriteService)

    state = {
        "loop_counts": {"total_rounds": 0, "retrieval_retries": 0, "generation_retries": 0},
        "rewrite_input_query": "rewrite source",
        "merged_context": "should_not_use",
        "user_input": "fallback",
        "reflection": {"reason": "retry"},
        "stage_summaries": {},
        "runtime_config": {},
    }

    result = await reflection.transform_query_for_retry(state, settings=settings)

    assert _FakeRewriteService.seen_query == "rewrite source"
    assert result["normalized_query"] == "rewrite source refined"


@pytest.mark.asyncio
async def test_answer_review_citation_failure_routes_to_transform_query(settings):
    state = {
        "loop_counts": {"total_rounds": 1, "retrieval_retries": 0, "generation_retries": 0},
        "normalized_query": "question",
        "final_context": "[S1] evidence body",
        "draft_answer": "answer without citation",
        "reflection": {},
        "stage_summaries": {},
    }

    result = await reflection.answer_review(state, settings=settings, chat_model=object())

    assert result["reflection"]["review_passed"] is False
    assert result["reflection"]["reason"] == "missing_citations"
    assert result["reflection"]["action"] == "transform_query"
    assert result["loop_counts"]["generation_retries"] == 0


def test_route_after_answer_review_citation_failure_prefers_transform_query(settings):
    state = {
        "loop_counts": {"total_rounds": 1, "retrieval_retries": 0, "generation_retries": 1},
        "reflection": {"review_passed": False, "reason": "missing_citations"},
    }

    next_node = reflection.route_after_answer_review(state, settings)

    assert next_node == "transform_query"


@pytest.mark.asyncio
async def test_prepare_messages_uses_hyde_docs_only(settings):
    state = {
        "normalized_query": "main question",
        "sub_queries": [],
        "multi_queries": [],
        "hyde_docs": ["hypothesis A", "hypothesis B"],
        "stage_summaries": {},
    }

    result = await preprocess.prepare_messages(state, settings=settings)
    hyde_items = [item for item in result["query_items"] if item.get("kind") == "hyde"]

    assert len(hyde_items) == 1
    assert hyde_items[0]["query"] == "hypothesis A"
    assert hyde_items[0]["hyde_queries"] == ["hypothesis A", "hypothesis B"]

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
    resolve_called = False
    seen_recent_turns: list[dict[str, str]] | None = None
    seen_coref_meta: dict[str, object] | None = None

    def __init__(self, settings=None):
        _ = settings

    async def coref_rewrite(
        self,
        query: str,
        *,
        enabled: bool = True,
        timeout_seconds: float | None = None,
        recent_turns: list[dict[str, str]] | None = None,
        summary_text: str | None = None,
        memory_snippet: str | None = None,
    ):
        _ = (enabled, timeout_seconds, summary_text, memory_snippet)
        type(self).seen_query = query
        type(self).seen_recent_turns = recent_turns
        return types.SimpleNamespace(
            query=query,
            reason=None,
            meta={
                "triggered": True,
                "confidence": 0.92,
                "candidate_count": 2,
                "selected_mention": "target mention",
                "resolution_source": "recent_turns_user",
                "needs_clarification": False,
            },
        )

    async def normalize_rewrite(
        self,
        query: str,
        *,
        llm_enabled: bool | None = None,
        alias_limit: int | None = None,
        timeout_seconds: float | None = None,
    ):
        _ = (llm_enabled, alias_limit, timeout_seconds)
        return types.SimpleNamespace(
            query=query,
            rewritten=False,
            meta={
                "source": "rule_only",
                "fallback_reason": "",
                "aliases": ["query alias"],
                "recall_risk": "high",
                "constraint_preserved": True,
                "drift_risk": False,
                "has_multi_target": False,
                "is_comparison": False,
            },
        )

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

    async def classify_complexity(
        self,
        query: str,
        *,
        recall_risk: str | None = None,
        has_multi_target: bool = False,
        is_comparison: bool = False,
    ):
        _ = (query, recall_risk, has_multi_target, is_comparison)
        return types.SimpleNamespace(
            strategy="direct", success=True, reasoning="single-hop"
        )

    async def ambiguity_check(
        self,
        query: str,
        *,
        enabled: bool | None = None,
        timeout_seconds: float | None = None,
        coref_meta: dict[str, object] | None = None,
    ):
        _ = (enabled, timeout_seconds)
        type(self).seen_query = query
        type(self).seen_coref_meta = coref_meta
        needs_clarification = bool(
            isinstance(coref_meta, dict) and coref_meta.get("needs_clarification")
        )
        if needs_clarification:
            return types.SimpleNamespace(
                ambiguous=True,
                reverse_question="请确认你指的是哪个具体对象？",
                reason="model_structured",
                reason_code="coref_uncertain",
                confidence=0.81,
                model_reason="coref confidence low",
                fallback_used=False,
                clarification_payload={
                    "question": "请确认你指的是哪个具体对象？",
                    "reason_code": "coref_uncertain",
                    "confidence": 0.81,
                    "model_reason": "coref confidence low",
                    "slots": [
                        {"key": "entity", "label": "对象", "required": True, "options": []}
                    ],
                    "suggested_answers": ["对象A", "对象B"],
                },
            )
        return types.SimpleNamespace(
            ambiguous=False,
            reverse_question=None,
            reason="model_structured",
            reason_code=None,
            confidence=None,
            model_reason=None,
            fallback_used=False,
            clarification_payload=None,
        )

    async def resolve_merge_context_conflict(
        self, *, question: str, summary_text: str, memory_snippet: str
    ):
        _ = (question, summary_text, memory_snippet)
        type(self).resolve_called = True
        return types.SimpleNamespace(
            summary_text=summary_text,
            keep_memory=True,
            notes=["resolved"],
            success=True,
            reason="ok",
            latency_ms=1,
        )


@pytest.fixture
def settings():
    return types.SimpleNamespace(
        app_env="test",
        kb_chat_json_safe_policy="fail_fast",
        memory_enabled=False,
        retrieval_query_rewrite_enabled=True,
        kb_chat_ambiguity_check_enabled=True,
        kb_chat_ambiguity_timeout_seconds=0.5,
        kb_chat_normalize_llm_enabled=True,
        kb_chat_normalize_alias_max=4,
        kb_chat_normalize_timeout_seconds=0.8,
        kb_chat_hyde_enabled=False,
        kb_chat_max_total_rounds=3,
        kb_chat_max_retrieval_retries=2,
        kb_chat_max_generation_retries=2,
        retrieval_default_top_k=5,
        kb_chat_grader_fail_policy="closed",
        summary_max_tokens=128,
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
    assert result["context_frame"]["merge_strategy"] == "builtin_summary_first"
    assert result["context_frame"]["summary_source"] in {"generated", "none"}
    merged = result["merged_context"]
    assert merged.count(question) == 1
    assert "compression_ratio" in result["stage_summaries"]["merge_context"]


@pytest.mark.asyncio
async def test_merge_context_conflict_resolution_fallback(monkeypatch, settings):
    monkeypatch.setattr(preprocess, "QueryRewriteService", _FakeRewriteService)
    settings.memory_enabled = True

    state = {
        "messages": [
            HumanMessage(content="What was 2024 revenue?"),
            AIMessage(content="It was 100."),
            # persisted summary with number disjoint from memory snippet
            preprocess.SystemMessage(content="对话摘要：\n2024 revenue was 100"),
        ],
        "user_input": "And what changed in 2025?",
        "metrics": {},
        "stage_summaries": {},
        "memory_keys": {},
    }

    class _RuntimeWithStore:
        store = object()

    async def _fake_get_memory(*, store, user_id, thread_id, kb_ids):
        _ = (store, user_id, thread_id, kb_ids)
        return {
            "entries": [{"q": "target", "a": "2025 revenue was 200"}],
            "schema": "kb_chat_user_memory_v1",
        }

    monkeypatch.setattr(preprocess, "aget_kb_chat_memory", _fake_get_memory)

    result = await preprocess.merge_context(
        state, runtime=_RuntimeWithStore(), settings=settings
    )

    summary = result["stage_summaries"]["merge_context"]
    assert summary["llm_resolve_used"] is True
    assert summary["fallback_used"] is False
    assert result["context_frame"]["merge_notes"] == ["resolved"]


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
    assert result["coref_meta"]["confidence"] == 0.92
    assert result["stage_summaries"]["coref_rewrite"]["confidence"] == 0.92


@pytest.mark.asyncio
async def test_ambiguity_check_uses_model_result_with_coref_meta(monkeypatch, settings):
    monkeypatch.setattr(preprocess, "QueryRewriteService", _FakeRewriteService)
    state = {
        "coref_query": "这个怎么做",
        "coref_meta": {
            "needs_clarification": True,
            "clarification_hint": "请确认对象",
        },
        "stage_summaries": {},
    }

    result = await preprocess.ambiguity_check(state, settings=settings)

    assert result["reflection"]["action"] == "clarify"
    assert result["reflection"]["reason"] == "ambiguous_query"
    assert result["reflection"]["reason_code"] == "coref_uncertain"
    assert result["final_answer"] == "请确认你指的是哪个具体对象？"
    assert result["stage_summaries"]["ambiguity_check"]["reason"] == "model_structured"
    assert result["stage_summaries"]["ambiguity_check"]["slot_count"] == 1
    assert _FakeRewriteService.seen_coref_meta is not None


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
    assert "plain question" in captured["user"]


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


@pytest.mark.asyncio
async def test_normalize_rewrite_persists_normalized_meta(monkeypatch, settings):
    monkeypatch.setattr(preprocess, "QueryRewriteService", _FakeRewriteService)
    state = {"coref_query": "original query", "stage_summaries": {}, "runtime_config": {}}

    result = await preprocess.normalize_rewrite(state, settings=settings)

    assert result["normalized_query"] == "original query"
    assert isinstance(result["normalized_meta"], dict)
    assert result["normalized_meta"]["source"] == "rule_only"
    assert result["stage_summaries"]["normalize_rewrite"]["alias_count"] == 1


@pytest.mark.asyncio
async def test_complexity_router_biases_multi_query_for_high_recall_risk(monkeypatch, settings):
    monkeypatch.setattr(preprocess, "QueryRewriteService", _FakeRewriteService)
    state = {
        "normalized_query": "short query",
        "normalized_meta": {"recall_risk": "high", "has_multi_target": False, "is_comparison": False},
        "stage_summaries": {},
    }

    result = await preprocess.complexity_router(state, settings=settings)

    assert result["query_strategy"] == "multi_query"
    assert result["stage_summaries"]["complexity_router"]["strategy_adjusted"] is True

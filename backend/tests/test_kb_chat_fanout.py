import uuid

import pytest

from app.agents.kb_chat_agentic.preprocess import prepare_messages
from app.agents.kb_chat_agentic.reflection import kb_retrieve_context
from app.agents.tools.kb_retrieve import build_kb_retrieve_tool
from app.core.settings import Settings
from app.services.retrieval_service import (
    RetrievalLayerDraft,
    RetrievalResult,
    RetrievedChunk,
)


@pytest.mark.asyncio
async def test_prepare_messages_builds_query_items_with_fanout_and_hyde() -> None:
    settings = Settings()
    state = {
        "messages": [],
        "normalized_query": "main query",
        "sub_queries": ["sub 1", "sub 2"],
        # Should be ignored when `sub_queries` is present (decomposition vs multi-query are exclusive).
        "multi_queries": ["variant 1", "variant 2"],
        "hyde_doc": "hyp doc",
        "stage_summaries": {},
    }

    result = await prepare_messages(state, settings)
    query_items = result.get("query_items")
    assert isinstance(query_items, list)

    kinds = [it.get("kind") for it in query_items if isinstance(it, dict)]
    assert "main" in kinds
    assert kinds.count("subquery") == 2
    assert "hyde" in kinds

    hyde_item = next(
        it for it in query_items if isinstance(it, dict) and it.get("kind") == "hyde"
    )
    assert hyde_item.get("use_dense") is True
    assert hyde_item.get("use_bm25") is False


class _CaptureTool:
    name = "kb_retrieve"

    def __init__(self) -> None:
        self.last_payload: dict | None = None

    async def ainvoke(self, payload: dict) -> str:
        self.last_payload = payload
        return "[1] foo\n\n[2] bar"


@pytest.mark.asyncio
async def test_kb_retrieve_context_passes_query_items_to_tool_payload() -> None:
    tool = _CaptureTool()
    settings = Settings()
    state = {
        "normalized_query": "main query",
        "memory_keys": {"kb_ids": ["00000000-0000-0000-0000-000000000000"]},
        "query_items": [
            {"kind": "main", "query": "main query", "use_dense": True, "use_bm25": True}
        ],
    }

    updates = await kb_retrieve_context(state, settings=settings, kb_tool=tool)  # type: ignore[arg-type]

    assert tool.last_payload is not None
    assert tool.last_payload["query"] == "main query"
    assert tool.last_payload["kb_ids"] == ["00000000-0000-0000-0000-000000000000"]
    assert tool.last_payload["query_items"] == state["query_items"]
    assert isinstance(tool.last_payload.get("timeout_seconds"), (int, float))

    assert updates["final_context"].startswith("[1]")
    assert updates["metrics"]["retrieval_layer"]["evidence_count"] == 2


class _FakeRetrievalService:
    def __init__(self) -> None:
        self.retrieve_layer_calls: list[dict] = []
        self.retrieve_calls: list[dict] = []
        self._last_layer_draft: RetrievalLayerDraft | None = None

    @property
    def last_layer_draft(self) -> RetrievalLayerDraft | None:
        return self._last_layer_draft

    async def retrieve_layer(
        self,
        *,
        query_items: list[dict],
        kb_ids: list[uuid.UUID],
        top_n: int,
        per_query_top_k: int | None = None,
        **_kwargs: object,
    ) -> RetrievalLayerDraft:
        self.retrieve_layer_calls.append(
            {
                "query_items": query_items,
                "kb_ids": kb_ids,
                "top_n": top_n,
                "per_query_top_k": per_query_top_k,
            }
        )

        chunk_id = uuid.uuid4()
        kb_id = kb_ids[0]
        material_id = uuid.uuid4()
        chunk = RetrievedChunk(
            id=chunk_id,
            kb_id=kb_id,
            material_id=material_id,
            content="content",
            context=None,
            locator=None,
            metadata=None,
            chunk_role=None,
            parent_chunk_id=None,
            child_seq=None,
        )
        result = RetrievalResult(chunk=chunk, score=1.0, context_text="ctx")
        draft = RetrievalLayerDraft(
            retrieval_candidates=[],
            reranked_candidates=[],
            evidence_items=[
                {
                    "source_kind": "kb",
                    "kb_id": str(kb_id),
                    "material_id": str(material_id),
                    "chunk_id": str(chunk_id),
                    "locator": None,
                    "excerpt": "ctx",
                    "score": 1.0,
                    "hits": [],
                }
            ],
            results=[result],
            stats={},
        )
        self._last_layer_draft = draft
        return draft

    async def retrieve(
        self,
        *,
        query: str,
        kb_ids: list[uuid.UUID],
        top_k: int | None,
        timeout_seconds: float | None = None,
    ) -> list[RetrievalResult]:
        self.retrieve_calls.append(
            {
                "query": query,
                "kb_ids": kb_ids,
                "top_k": top_k,
                "timeout_seconds": timeout_seconds,
            }
        )
        return []


class _CaptureRetrieval:
    def __init__(self) -> None:
        self.calls: list[list[uuid.UUID]] = []
        self._last_layer_draft = None

    @property
    def last_layer_draft(self):  # pragma: no cover - API compatibility
        return self._last_layer_draft

    async def retrieve(
        self,
        *,
        query: str,
        kb_ids: list[uuid.UUID],
        top_k: int | None = None,
        timeout_seconds: float | None = None,
    ) -> list[RetrievalResult]:
        _ = (query, top_k, timeout_seconds)
        self.calls.append(kb_ids)
        return []


@pytest.mark.asyncio
async def test_kb_retrieve_tool_applies_kb_scope_intersection() -> None:
    fake = _CaptureRetrieval()
    allowed = [uuid.uuid4(), uuid.uuid4()]
    requested = [allowed[1], uuid.uuid4(), allowed[0]]
    captured_meta: dict[str, object] = {}

    def _on_results(_included: list, meta: dict[str, object]) -> None:
        captured_meta.update(meta)

    tool = build_kb_retrieve_tool(
        retrieval=fake,  # type: ignore[arg-type]
        default_kb_ids=allowed,
        context_builder=None,
        on_results=_on_results,
    )

    await tool.ainvoke({"query": "q", "kb_ids": [str(k) for k in requested]})

    assert fake.calls[0] == [allowed[1], allowed[0]]
    kb_scope = captured_meta.get("kb_scope")
    assert isinstance(kb_scope, dict)
    assert kb_scope["requested_count"] == 3
    assert kb_scope["applied_count"] == 2
    assert kb_scope["denied_count"] == 1


@pytest.mark.asyncio
async def test_kb_retrieve_tool_fallbacks_on_empty_intersection() -> None:
    fake = _CaptureRetrieval()
    allowed = [uuid.uuid4()]
    requested = [uuid.uuid4()]
    captured_meta: dict[str, object] = {}

    def _on_results(_included: list, meta: dict[str, object]) -> None:
        captured_meta.update(meta)

    tool = build_kb_retrieve_tool(
        retrieval=fake,  # type: ignore[arg-type]
        default_kb_ids=allowed,
        context_builder=None,
        on_results=_on_results,
    )

    await tool.ainvoke({"query": "q", "kb_ids": [str(k) for k in requested]})

    assert fake.calls[0] == allowed
    kb_scope = captured_meta.get("kb_scope")
    assert isinstance(kb_scope, dict)
    assert kb_scope["fallback_to_allowed"] is True


@pytest.mark.asyncio
async def test_kb_retrieve_tool_uses_retrieve_layer_when_query_items_provided() -> None:
    fake = _FakeRetrievalService()
    default_kb_id = uuid.uuid4()

    tool = build_kb_retrieve_tool(
        retrieval=fake,  # type: ignore[arg-type]
        default_kb_ids=[default_kb_id],
        context_builder=None,
    )

    query_items = [{"kind": "main", "query": "q", "use_dense": True, "use_bm25": True}]
    output = await tool.ainvoke(
        {
            "query": "ignored",
            "kb_ids": [str(default_kb_id)],
            "top_k": 3,
            "query_items": query_items,
        }
    )

    assert fake.retrieve_calls == []
    assert len(fake.retrieve_layer_calls) == 1
    call = fake.retrieve_layer_calls[0]
    assert call["query_items"] == query_items
    assert call["top_n"] == 3
    assert call["per_query_top_k"] == 3
    assert "[1]" in output

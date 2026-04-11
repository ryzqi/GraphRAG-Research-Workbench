from __future__ import annotations

import uuid

from app.services import retrieval_service
from app.services.retrieval_service_contracts import (
    RetrievedChunk,
    RetrievalLayerDraft,
    RetrievalResult,
)


def test_retrieval_helper_contracts_and_service_reexports() -> None:
    chunk = RetrievedChunk(
        id=uuid.uuid4(),
        kb_id=uuid.uuid4(),
        material_id=uuid.uuid4(),
        content="chunk body",
        context=None,
        locator={"filename": "docs/rag-guide.md"},
        metadata={"heading": "RAG"},
        chunk_role="default",
        parent_chunk_id=None,
        child_seq=None,
    )
    result = RetrievalResult(chunk=chunk, score=0.91, context_text="expanded context")
    draft = RetrievalLayerDraft(
        retrieval_candidates=[result],
        reranked_candidates=[result],
        evidence_items=[{"chunk_id": str(chunk.id), "score": result.score}],
        results=[result],
        stats={"reason": "timeout"},
    )

    assert draft.results[0].chunk.id == chunk.id
    assert draft.evidence_items[0]["chunk_id"] == str(chunk.id)
    assert retrieval_service.RetrievalResult is RetrievalResult
    assert retrieval_service.RetrievedChunk is RetrievedChunk
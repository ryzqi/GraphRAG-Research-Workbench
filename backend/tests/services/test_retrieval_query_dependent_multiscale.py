from __future__ import annotations

import uuid

import pytest

from app.schemas.knowledge_bases import IndexConfig
from app.services.retrieval_service import RetrievalResult, RetrievedChunk, RetrievalService


class _DummyMilvus:
    pass


class _DummyEmbedding:
    pass


def _build_result(
    *,
    chunk_id: str,
    kb_id: uuid.UUID,
    material_id: uuid.UUID,
    score: float,
    window_size_tokens: int | None,
    window_overlap_tokens: int | None,
) -> RetrievalResult:
    metadata: dict | None = None
    if window_size_tokens is not None and window_overlap_tokens is not None:
        metadata = {
            'window_size_tokens': window_size_tokens,
            'window_overlap_tokens': window_overlap_tokens,
        }
    return RetrievalResult(
        chunk=RetrievedChunk(
            id=uuid.UUID(chunk_id),
            kb_id=kb_id,
            material_id=material_id,
            content=f'chunk-{chunk_id}',
            context=None,
            locator=None,
            metadata=metadata,
            chunk_role=None,
            parent_chunk_id=None,
            child_seq=None,
        ),
        score=score,
    )


@pytest.mark.asyncio
async def test_multiscale_strategy_prefers_documents_supported_by_multiple_windows() -> None:
    ms_kb = uuid.uuid4()
    other_kb = uuid.uuid4()
    material_a = uuid.uuid4()
    material_b = uuid.uuid4()
    material_c = uuid.uuid4()

    service = RetrievalService(
        db=None,  # type: ignore[arg-type]
        milvus=_DummyMilvus(),  # type: ignore[arg-type]
        embedding=_DummyEmbedding(),  # type: ignore[arg-type]
    )

    ms_config = IndexConfig.model_validate(
        {
            'chunking': {
                'general_strategy': 'query_dependent_multiscale',
                'query_dependent_multiscale': {
                    'windows': [
                        {'chunk_size_tokens': 100, 'chunk_overlap_tokens': 20},
                        {'chunk_size_tokens': 200, 'chunk_overlap_tokens': 40},
                    ]
                },
            },
            'retrieval': {
                'query_dependent_multiscale': {
                    'rrf_k': 60,
                    'per_window_top_k': 10,
                    'max_documents': 1,
                    'max_chunks_per_document': 1,
                }
            },
        }
    )
    other_config = IndexConfig.model_validate({'chunking': {'general_strategy': 'parent_child'}})

    results = [
        _build_result(
            chunk_id='00000000-0000-0000-0000-000000000001',
            kb_id=ms_kb,
            material_id=material_a,
            score=0.90,
            window_size_tokens=100,
            window_overlap_tokens=20,
        ),
        _build_result(
            chunk_id='00000000-0000-0000-0000-000000000002',
            kb_id=ms_kb,
            material_id=material_b,
            score=0.85,
            window_size_tokens=100,
            window_overlap_tokens=20,
        ),
        _build_result(
            chunk_id='00000000-0000-0000-0000-000000000003',
            kb_id=ms_kb,
            material_id=material_b,
            score=0.95,
            window_size_tokens=200,
            window_overlap_tokens=40,
        ),
        _build_result(
            chunk_id='00000000-0000-0000-0000-000000000004',
            kb_id=other_kb,
            material_id=material_c,
            score=0.70,
            window_size_tokens=None,
            window_overlap_tokens=None,
        ),
    ]

    ranked = await service._apply_query_dependent_multiscale_strategy(
        results,
        {
            ms_kb: ms_config,
            other_kb: other_config,
        },
    )

    # For multiscale KB, material_b is selected because it appears in two windows.
    assert len([row for row in ranked if row.chunk.kb_id == ms_kb]) == 1
    assert ranked[0].chunk.material_id == material_b
    assert ranked[0].context_text == ranked[0].chunk.content

    # Non-multiscale KB results are preserved.
    assert any(row.chunk.kb_id == other_kb for row in ranked)


@pytest.mark.asyncio
async def test_multiscale_strategy_keeps_original_results_when_no_window_metadata() -> None:
    kb_id = uuid.uuid4()
    material_id = uuid.uuid4()

    service = RetrievalService(
        db=None,  # type: ignore[arg-type]
        milvus=_DummyMilvus(),  # type: ignore[arg-type]
        embedding=_DummyEmbedding(),  # type: ignore[arg-type]
    )

    config = IndexConfig.model_validate(
        {
            'chunking': {
                'general_strategy': 'query_dependent_multiscale',
                'query_dependent_multiscale': {
                    'windows': [{'chunk_size_tokens': 100, 'chunk_overlap_tokens': 20}]
                },
            }
        }
    )

    results = [
        _build_result(
            chunk_id='00000000-0000-0000-0000-000000000010',
            kb_id=kb_id,
            material_id=material_id,
            score=0.8,
            window_size_tokens=None,
            window_overlap_tokens=None,
        )
    ]

    ranked = await service._apply_query_dependent_multiscale_strategy(results, {kb_id: config})

    assert ranked == results

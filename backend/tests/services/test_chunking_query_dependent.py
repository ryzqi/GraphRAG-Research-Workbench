from __future__ import annotations

import pytest

from app.schemas.knowledge_bases import IndexConfig, SemanticThresholdMode
from app.services.chunking import (
    ChunkingEngine,
    _resolve_semantic_threshold,
    _split_sentences,
)
from app.services.parsing.types import ParsedChunk, ParsedDocument
from app.utils.token_counter import count_tokens, split_text_by_token_windows


class _FailingEmbedding:
    async def embed(self, *, texts: list[str]) -> list[list[float]]:
        raise RuntimeError(f'boom: {len(texts)}')


class _UniformEmbedding:
    async def embed(self, *, texts: list[str]) -> list[list[float]]:
        return [[1.0, 0.0] for _ in texts]


@pytest.mark.asyncio
async def test_query_dependent_multiscale_emits_chunks_for_each_window() -> None:
    engine = ChunkingEngine()
    document = ParsedDocument(text='a' * 1200, metadata={'source': 'unit'})
    index_config = IndexConfig.model_validate(
        {
            'chunking': {
                'general_strategy': 'query_dependent_multiscale',
                'query_dependent_multiscale': {
                    'windows': [
                        {'chunk_size_tokens': 100, 'chunk_overlap_tokens': 0},
                        {'chunk_size_tokens': 200, 'chunk_overlap_tokens': 0},
                    ]
                },
            }
        }
    )

    chunks = await engine.split(document, index_config)

    expected_window_zero = split_text_by_token_windows(
        document.text or '',
        chunk_size_tokens=100,
        chunk_overlap_tokens=0,
        model=engine._settings.embedding_model,
    )
    expected_window_one = split_text_by_token_windows(
        document.text or '',
        chunk_size_tokens=200,
        chunk_overlap_tokens=0,
        model=engine._settings.embedding_model,
    )

    assert len(chunks) == len(expected_window_zero) + len(expected_window_one)
    assert {item.metadata['window_id'] for item in chunks} == {0, 1}
    assert all(item.metadata['chunking_strategy'] == 'query_dependent_multiscale' for item in chunks)
    assert chunks[0].metadata['window_size_tokens'] == 100
    assert chunks[0].metadata['window_overlap_tokens'] == 0
    assert chunks[0].metadata['token_start'] == 0
    assert chunks[0].metadata['token_end'] == int(expected_window_zero[0]['token_end'])


@pytest.mark.asyncio
async def test_default_non_markdown_path_uses_multiscale_windows() -> None:
    engine = ChunkingEngine()
    index_config = IndexConfig.model_validate(
        {
            'chunking': {
                'general_strategy': 'query_dependent_multiscale',
                'query_dependent_multiscale': {
                    'windows': [
                        {'chunk_size_tokens': 100, 'chunk_overlap_tokens': 20},
                        {'chunk_size_tokens': 200, 'chunk_overlap_tokens': 40},
                        {'chunk_size_tokens': 500, 'chunk_overlap_tokens': 100},
                    ]
                },
            }
        }
    )

    chunks = await engine.split(ParsedDocument(text='hello world'), index_config)

    assert len(chunks) == 3
    assert [item.metadata['window_id'] for item in chunks] == [0, 1, 2]
    assert all(item.content == 'hello world' for item in chunks)


@pytest.mark.asyncio
async def test_semantic_fallback_uses_first_multiscale_window() -> None:
    engine = ChunkingEngine(embedding=_FailingEmbedding())  # type: ignore[arg-type]
    index_config = IndexConfig.model_validate(
        {
            'chunking': {
                'general_strategy': 'max_min_semantic',
                'query_dependent_multiscale': {
                    'windows': [
                        {'chunk_size_tokens': 100, 'chunk_overlap_tokens': 10},
                        {'chunk_size_tokens': 200, 'chunk_overlap_tokens': 20},
                    ]
                },
            }
        }
    )

    chunks = await engine.split(ParsedDocument(text='a' * 1200), index_config)

    expected_windows = split_text_by_token_windows(
        'a' * 1200,
        chunk_size_tokens=100,
        chunk_overlap_tokens=10,
        model=engine._settings.embedding_model,
    )
    assert [item.content for item in chunks] == [str(window['text']) for window in expected_windows]

    for item in chunks:
        assert item.metadata is not None
        assert item.metadata['chunking_strategy'] == 'max_min_semantic'
        assert item.metadata['semantic_fallback'] is True
        assert item.metadata['semantic_fallback_reason'] == 'RuntimeError'
        assert item.metadata['fallback_window_size_tokens'] == 100
        assert item.metadata['fallback_window_overlap_tokens'] == 10
        assert item.metadata['threshold_mode'] == 'percentile'
        assert 'window_id' not in item.metadata


@pytest.mark.asyncio
async def test_pdf_blocks_multiscale_keeps_window_token_metadata() -> None:
    engine = ChunkingEngine()
    document = ParsedDocument(
        text='',
        mime_type='application/pdf',
        chunks=[
            ParsedChunk(text='first', locator={'kind': 'pdf', 'page_start': 1, 'page_end': 1}),
            ParsedChunk(text='second', locator={'kind': 'pdf', 'page_start': 1, 'page_end': 1}),
        ],
    )
    index_config = IndexConfig.model_validate(
        {
            'chunking': {
                'general_strategy': 'query_dependent_multiscale',
                'query_dependent_multiscale': {
                    'windows': [{'chunk_size_tokens': 100, 'chunk_overlap_tokens': 0}]
                },
            }
        }
    )

    chunks = await engine.split(document, index_config)

    assert [item.content for item in chunks] == ['first\n\nsecond']
    assert chunks[0].metadata['chunking_strategy'] == 'query_dependent_multiscale'
    assert chunks[0].metadata['window_id'] == 0
    assert chunks[0].metadata['window_size_tokens'] == 100
    assert chunks[0].metadata['window_overlap_tokens'] == 0


@pytest.mark.asyncio
async def test_pdf_blocks_apply_each_multiscale_window_across_full_document() -> None:
    engine = ChunkingEngine()
    document = ParsedDocument(
        text='',
        mime_type='application/pdf',
        chunks=[
            ParsedChunk(
                text='A' * 60,
                locator={
                    'kind': 'pdf',
                    'page_start': 1,
                    'page_end': 1,
                    'blocks': [{'id': 'p1_b1'}],
                },
                metadata={'mineru_block_type': 'text'},
            ),
            ParsedChunk(
                text='B' * 60,
                locator={
                    'kind': 'pdf',
                    'page_start': 2,
                    'page_end': 2,
                    'blocks': [{'id': 'p2_b1'}],
                },
                metadata={'mineru_block_type': 'text'},
            ),
            ParsedChunk(
                text='C' * 60,
                locator={
                    'kind': 'pdf',
                    'page_start': 3,
                    'page_end': 3,
                    'blocks': [{'id': 'p3_b1'}],
                },
                metadata={'mineru_block_type': 'text'},
            ),
            ParsedChunk(
                text='D' * 60,
                locator={
                    'kind': 'pdf',
                    'page_start': 4,
                    'page_end': 4,
                    'blocks': [{'id': 'p4_b1'}],
                },
                metadata={'mineru_block_type': 'text'},
            ),
        ],
    )
    index_config = IndexConfig.model_validate(
        {
            'chunking': {
                'general_strategy': 'query_dependent_multiscale',
                'query_dependent_multiscale': {
                    'windows': [
                        {'chunk_size_tokens': 32, 'chunk_overlap_tokens': 0},
                        {'chunk_size_tokens': 50, 'chunk_overlap_tokens': 0},
                    ]
                },
            }
        }
    )

    chunks = await engine.split(document, index_config)

    window_zero = [item for item in chunks if item.metadata['window_id'] == 0]
    window_one = [item for item in chunks if item.metadata['window_id'] == 1]

    assert len(window_zero) == 2
    assert [len(item.locator['blocks']) for item in window_zero] == [3, 1]
    assert len(window_one) == 1
    assert window_one[0].locator['page_start'] == 1
    assert window_one[0].locator['page_end'] == 4
    assert len(window_one[0].locator['blocks']) == 4
    assert window_one[0].metadata['mineru_block_types'] == ['text', 'text', 'text', 'text']
    assert window_one[0].metadata['chunking_strategy'] == 'query_dependent_multiscale'
    assert window_one[0].metadata['window_id'] == 1
    assert window_one[0].metadata['window_size_tokens'] == 50
    assert window_one[0].metadata['window_overlap_tokens'] == 0
    assert window_one[0].metadata['token_start'] == 0
    assert window_one[0].metadata['token_end'] == count_tokens(
        window_one[0].content,
        model=engine._settings.embedding_model,
    )
    assert window_one[0].metadata['index'] == 0


def test_split_sentences_keeps_common_english_abbreviations() -> None:
    text = 'Use e.g. this example. Keep U.S. references. Then split here.'

    sentences = _split_sentences(text)

    assert sentences == [
        'Use e.g. this example.',
        'Keep U.S. references.',
        'Then split here.',
    ]


@pytest.mark.asyncio
async def test_semantic_hard_caps_chunk_token_budget_for_long_single_sentence() -> None:
    engine = ChunkingEngine(embedding=_UniformEmbedding())  # type: ignore[arg-type]
    index_config = IndexConfig.model_validate(
        {
            'chunking': {
                'general_strategy': 'max_min_semantic',
                'semantic': {
                    'min_tokens': 16,
                    'max_tokens': 32,
                    'threshold_mode': 'fixed',
                    'similarity_threshold': 0.0,
                    'overlap_chars': 0,
                    'embedding_batch_size': 8,
                },
            }
        }
    )

    text = 'semantic ' * 600
    chunks = await engine.split(ParsedDocument(text=text), index_config)

    assert len(chunks) > 1
    for item in chunks:
        assert (
            count_tokens(item.content, model=engine._settings.embedding_model)
            <= index_config.chunking.semantic.max_tokens
        )
        assert item.metadata is not None
        assert item.metadata['chunking_strategy'] == 'max_min_semantic'
        assert item.metadata['semantic_fallback'] is False


def test_resolve_semantic_threshold_supports_percentile_fixed_and_hybrid() -> None:
    similarities = [0.1, 0.5, 0.9]

    percentile_threshold = _resolve_semantic_threshold(
        similarities=similarities,
        threshold_mode=SemanticThresholdMode.PERCENTILE,
        breakpoint_percentile=50,
        fixed_threshold=None,
    )
    fixed_threshold = _resolve_semantic_threshold(
        similarities=similarities,
        threshold_mode=SemanticThresholdMode.FIXED,
        breakpoint_percentile=50,
        fixed_threshold=0.7,
    )
    hybrid_threshold = _resolve_semantic_threshold(
        similarities=similarities,
        threshold_mode=SemanticThresholdMode.HYBRID,
        breakpoint_percentile=50,
        fixed_threshold=0.7,
    )

    assert percentile_threshold == pytest.approx(0.5)
    assert fixed_threshold == pytest.approx(0.7)
    assert hybrid_threshold == pytest.approx(0.5)


@pytest.mark.asyncio
async def test_pdf_semantic_chunks_do_not_depend_on_multiscale_window_settings() -> None:
    engine = ChunkingEngine(embedding=_UniformEmbedding())  # type: ignore[arg-type]
    document = ParsedDocument(
        text='',
        mime_type='application/pdf',
        chunks=[
            ParsedChunk(
                text='Alpha one. Alpha two.',
                locator={'kind': 'pdf', 'page_start': 1, 'page_end': 1},
            ),
            ParsedChunk(
                text='Beta one. Beta two.',
                locator={'kind': 'pdf', 'page_start': 2, 'page_end': 2},
            ),
            ParsedChunk(
                text='Gamma one. Gamma two.',
                locator={'kind': 'pdf', 'page_start': 3, 'page_end': 3},
            ),
        ],
    )

    base_semantic = {
        'min_tokens': 16,
        'max_tokens': 32,
        'threshold_mode': 'fixed',
        'similarity_threshold': 0.0,
        'overlap_chars': 0,
        'embedding_batch_size': 8,
    }
    config_small_windows = IndexConfig.model_validate(
        {
            'chunking': {
                'general_strategy': 'max_min_semantic',
                'query_dependent_multiscale': {
                    'windows': [{'chunk_size_tokens': 24, 'chunk_overlap_tokens': 4}]
                },
                'semantic': base_semantic,
            }
        }
    )
    config_large_windows = IndexConfig.model_validate(
        {
            'chunking': {
                'general_strategy': 'max_min_semantic',
                'query_dependent_multiscale': {
                    'windows': [{'chunk_size_tokens': 300, 'chunk_overlap_tokens': 30}]
                },
                'semantic': base_semantic,
            }
        }
    )

    chunks_small = await engine.split(document, config_small_windows)
    chunks_large = await engine.split(document, config_large_windows)

    assert [item.content for item in chunks_small] == [item.content for item in chunks_large]
    assert [item.locator for item in chunks_small] == [item.locator for item in chunks_large]
    for item in chunks_small + chunks_large:
        assert item.metadata is not None
        assert item.metadata['chunking_strategy'] == 'max_min_semantic'
        assert item.metadata['semantic_fallback'] is False
        assert 'window_id' not in item.metadata

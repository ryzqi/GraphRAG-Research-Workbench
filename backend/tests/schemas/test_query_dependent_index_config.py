from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.schemas.knowledge_bases import ChunkingStrategy, IndexConfig


def test_index_config_accepts_query_dependent_chunking_payload() -> None:
    config = IndexConfig.model_validate(
        {
            "chunking": {
                "general_strategy": "query_dependent_chunking",
                "query_dependent_chunking": {
                    "windows": [
                        {"chunk_size": 512, "chunk_overlap": 64},
                        {"chunk_size": 1024, "chunk_overlap": 128},
                    ]
                },
            },
            "retrieval": {
                "query_dependent": {
                    "rrf_k": 50,
                    "max_chunks_per_document": 3,
                }
            },
        }
    )

    assert config.chunking.general_strategy == ChunkingStrategy.QUERY_DEPENDENT_CHUNKING
    assert len(config.chunking.query_dependent_chunking.windows) == 2
    assert config.chunking.query_dependent_chunking.windows[1].chunk_size == 1024
    assert config.retrieval.query_dependent.rrf_k == 50
    assert config.retrieval.query_dependent.max_chunks_per_document == 3


def test_index_config_has_query_dependent_retrieval_defaults() -> None:
    config = IndexConfig()

    assert config.retrieval.query_dependent.rrf_k == 60
    assert config.retrieval.query_dependent.max_chunks_per_document == 2


def test_index_config_rejects_legacy_sliding_window_payload() -> None:
    with pytest.raises(ValidationError, match="sliding_window"):
        IndexConfig.model_validate(
            {
                "chunking": {
                    "general_strategy": "sliding_window",
                    "sliding_window": {
                        "chunk_size": 512,
                        "chunk_overlap": 64,
                    },
                }
            }
        )


def test_index_config_rejects_query_dependent_window_with_invalid_overlap() -> None:
    with pytest.raises(ValidationError, match="chunk_overlap"):
        IndexConfig.model_validate(
            {
                "chunking": {
                    "query_dependent_chunking": {
                        "windows": [{"chunk_size": 256, "chunk_overlap": 256}]
                    }
                }
            }
        )


@pytest.mark.parametrize(
    "windows",
    [
        [],
        [
            {"chunk_size": 256, "chunk_overlap": 64},
            {"chunk_size": 384, "chunk_overlap": 96},
            {"chunk_size": 512, "chunk_overlap": 128},
            {"chunk_size": 640, "chunk_overlap": 160},
            {"chunk_size": 768, "chunk_overlap": 192},
            {"chunk_size": 896, "chunk_overlap": 224},
        ],
    ],
)
def test_index_config_rejects_query_dependent_window_count_out_of_range(
    windows: list[dict[str, int]],
) -> None:
    with pytest.raises(ValidationError, match="windows"):
        IndexConfig.model_validate(
            {
                "chunking": {
                    "query_dependent_chunking": {
                        "windows": windows,
                    }
                }
            }
        )

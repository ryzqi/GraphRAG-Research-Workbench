from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.schemas.knowledge_bases import ChunkingStrategy, IndexConfig


def _valid_multiscale_windows() -> list[dict[str, int]]:
    return [
        {"chunk_size_tokens": 100, "chunk_overlap_tokens": 20},
        {"chunk_size_tokens": 200, "chunk_overlap_tokens": 40},
    ]


def test_index_config_accepts_query_dependent_multiscale_payload() -> None:
    config = IndexConfig.model_validate(
        {
            "chunking": {
                "general_strategy": "query_dependent_multiscale",
                "query_dependent_multiscale": {
                    "windows": _valid_multiscale_windows(),
                },
            },
            "retrieval": {
                "query_dependent_multiscale": {
                    "rrf_k": 50,
                    "per_window_top_k": 30,
                    "max_documents": 6,
                    "max_chunks_per_document": 3,
                }
            },
        }
    )

    assert config.chunking.general_strategy == ChunkingStrategy.QUERY_DEPENDENT_MULTISCALE
    assert len(config.chunking.query_dependent_multiscale.windows) == 2
    assert config.chunking.query_dependent_multiscale.windows[1].chunk_size_tokens == 200
    assert config.retrieval.query_dependent_multiscale.rrf_k == 50
    assert config.retrieval.query_dependent_multiscale.per_window_top_k == 30
    assert config.retrieval.query_dependent_multiscale.max_documents == 6
    assert config.retrieval.query_dependent_multiscale.max_chunks_per_document == 3


def test_index_config_retrieval_defaults_are_stable_with_explicit_windows() -> None:
    config = IndexConfig.model_validate(
        {
            "chunking": {
                "general_strategy": "query_dependent_multiscale",
                "query_dependent_multiscale": {"windows": _valid_multiscale_windows()},
            }
        }
    )

    assert config.retrieval.query_dependent_multiscale.rrf_k == 60
    assert config.retrieval.query_dependent_multiscale.per_window_top_k == 20
    assert config.retrieval.query_dependent_multiscale.max_documents == 8
    assert config.retrieval.query_dependent_multiscale.max_chunks_per_document == 2


def test_index_config_requires_windows_for_query_dependent_multiscale_strategy() -> None:
    with pytest.raises(ValidationError, match="query_dependent_multiscale.windows is required"):
        IndexConfig.model_validate({"chunking": {"general_strategy": "query_dependent_multiscale"}})


def test_index_config_rejects_legacy_query_dependent_chunking_payload() -> None:
    with pytest.raises(ValidationError, match="query_dependent_chunking"):
        IndexConfig.model_validate(
            {
                "chunking": {
                    "general_strategy": "query_dependent_chunking",
                    "query_dependent_chunking": {
                        "windows": [{"chunk_size": 512, "chunk_overlap": 64}]
                    },
                }
            }
        )


def test_index_config_rejects_multiscale_window_with_invalid_overlap() -> None:
    with pytest.raises(ValidationError, match="chunk_overlap_tokens"):
        IndexConfig.model_validate(
            {
                "chunking": {
                    "general_strategy": "query_dependent_multiscale",
                    "query_dependent_multiscale": {
                        "windows": [{"chunk_size_tokens": 128, "chunk_overlap_tokens": 128}]
                    },
                }
            }
        )


def test_index_config_rejects_duplicate_multiscale_windows() -> None:
    with pytest.raises(ValidationError, match="duplicate windows"):
        IndexConfig.model_validate(
            {
                "chunking": {
                    "general_strategy": "query_dependent_multiscale",
                    "query_dependent_multiscale": {
                        "windows": [
                            {"chunk_size_tokens": 100, "chunk_overlap_tokens": 20},
                            {"chunk_size_tokens": 100, "chunk_overlap_tokens": 20},
                        ]
                    },
                }
            }
        )


def test_index_config_rejects_unsorted_multiscale_windows() -> None:
    with pytest.raises(ValidationError, match="sorted by chunk_size_tokens"):
        IndexConfig.model_validate(
            {
                "chunking": {
                    "general_strategy": "query_dependent_multiscale",
                    "query_dependent_multiscale": {
                        "windows": [
                            {"chunk_size_tokens": 200, "chunk_overlap_tokens": 40},
                            {"chunk_size_tokens": 100, "chunk_overlap_tokens": 20},
                        ]
                    },
                }
            }
        )


@pytest.mark.parametrize(
    "windows",
    [
        [
            {"chunk_size_tokens": 64, "chunk_overlap_tokens": 8},
            {"chunk_size_tokens": 96, "chunk_overlap_tokens": 12},
            {"chunk_size_tokens": 128, "chunk_overlap_tokens": 16},
            {"chunk_size_tokens": 160, "chunk_overlap_tokens": 20},
            {"chunk_size_tokens": 192, "chunk_overlap_tokens": 24},
            {"chunk_size_tokens": 224, "chunk_overlap_tokens": 28},
        ],
    ],
)
def test_index_config_rejects_multiscale_window_count_out_of_range(
    windows: list[dict[str, int]],
) -> None:
    with pytest.raises(ValidationError, match="windows"):
        IndexConfig.model_validate(
            {
                "chunking": {
                    "general_strategy": "query_dependent_multiscale",
                    "query_dependent_multiscale": {
                        "windows": windows,
                    },
                }
            }
        )


@pytest.mark.parametrize(
    ("threshold_mode", "breakpoint_percentile", "similarity_threshold"),
    [
        ("percentile", 30, None),
        ("fixed", None, 0.55),
        ("hybrid", 30, 0.55),
    ],
)
def test_index_config_accepts_semantic_threshold_modes(
    threshold_mode: str,
    breakpoint_percentile: int | None,
    similarity_threshold: float | None,
) -> None:
    config = IndexConfig.model_validate(
        {
            "chunking": {
                "general_strategy": "max_min_semantic",
                "semantic": {
                    "min_tokens": 64,
                    "max_tokens": 256,
                    "threshold_mode": threshold_mode,
                    "breakpoint_percentile": breakpoint_percentile,
                    "similarity_threshold": similarity_threshold,
                    "overlap_chars": 64,
                    "embedding_batch_size": 64,
                },
            }
        }
    )

    assert config.chunking.semantic.threshold_mode.value == threshold_mode
    assert config.chunking.semantic.breakpoint_percentile == breakpoint_percentile
    assert config.chunking.semantic.similarity_threshold == similarity_threshold


@pytest.mark.parametrize("threshold_mode", ["percentile", "hybrid"])
def test_index_config_rejects_semantic_missing_breakpoint_percentile(
    threshold_mode: str,
) -> None:
    with pytest.raises(ValidationError, match="breakpoint_percentile is required"):
        IndexConfig.model_validate(
            {
                "chunking": {
                    "general_strategy": "max_min_semantic",
                    "semantic": {
                        "threshold_mode": threshold_mode,
                        "breakpoint_percentile": None,
                        "similarity_threshold": 0.6,
                    },
                }
            }
        )


@pytest.mark.parametrize("threshold_mode", ["fixed", "hybrid"])
def test_index_config_rejects_semantic_missing_similarity_threshold(
    threshold_mode: str,
) -> None:
    with pytest.raises(ValidationError, match="similarity_threshold is required"):
        IndexConfig.model_validate(
            {
                "chunking": {
                    "general_strategy": "max_min_semantic",
                    "semantic": {
                        "threshold_mode": threshold_mode,
                        "breakpoint_percentile": 25,
                        "similarity_threshold": None,
                    },
                }
            }
        )


def test_index_config_rejects_semantic_when_max_tokens_less_than_min_tokens() -> None:
    with pytest.raises(ValidationError, match="max_tokens must be greater than or equal"):
        IndexConfig.model_validate(
            {
                "chunking": {
                    "general_strategy": "max_min_semantic",
                    "semantic": {
                        "min_tokens": 128,
                        "max_tokens": 64,
                    },
                }
            }
        )

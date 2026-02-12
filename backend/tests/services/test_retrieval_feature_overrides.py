from __future__ import annotations

from app.services.retrieval_service import RetrievalService


class _DummyMilvus:
    pass


class _DummyEmbedding:
    pass


def test_resolve_feature_flags_uses_settings_defaults() -> None:
    service = RetrievalService(
        db=None,  # type: ignore[arg-type]
        milvus=_DummyMilvus(),  # type: ignore[arg-type]
        embedding=_DummyEmbedding(),  # type: ignore[arg-type]
    )

    flags = service._resolve_feature_flags(None)

    assert flags.query_rewrite_enabled == service._settings.retrieval_query_rewrite_enabled
    assert flags.hybrid_enabled == service._settings.retrieval_hybrid_enabled
    assert flags.rerank_enabled == service._settings.retrieval_rerank_enabled


def test_resolve_feature_flags_applies_runtime_overrides() -> None:
    service = RetrievalService(
        db=None,  # type: ignore[arg-type]
        milvus=_DummyMilvus(),  # type: ignore[arg-type]
        embedding=_DummyEmbedding(),  # type: ignore[arg-type]
    )

    flags = service._resolve_feature_flags(
        {
            "query_rewrite_enabled": False,
            "hybrid_retrieval_enabled": False,
            "rerank_enabled": False,
        }
    )

    assert flags.query_rewrite_enabled is False
    assert flags.hybrid_enabled is False
    assert flags.rerank_enabled is False

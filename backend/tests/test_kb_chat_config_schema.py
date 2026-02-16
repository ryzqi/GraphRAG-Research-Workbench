from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.schemas.chats import KbChatConfig


def _base_payload() -> dict[str, object]:
    return {
        "query_rewrite_enabled": True,
        "ambiguity_check_enabled": True,
        "decomposition_enabled": False,
        "multi_query_enabled": False,
        "hyde_enabled": False,
        "hybrid_retrieval_enabled": True,
        "rerank_enabled": True,
        "decomposition_max_sub_questions": 3,
        "multi_query_max_variants": 3,
        "retrieval_top_k": 8,
        "retrieval_rerank_top_k": 12,
        "retrieval_hybrid_ranker": "weighted",
        "retrieval_hybrid_dense_weight": 0.6,
        "retrieval_hybrid_sparse_weight": 0.4,
        "retrieval_hybrid_rrf_k": 50,
        "retrieval_parent_max_parents": 6,
        "retrieval_parent_max_children_per_parent": 2,
        "retrieval_multiscale_per_window_top_k": 20,
        "retrieval_multiscale_rrf_k": 60,
        "retrieval_multiscale_max_documents": 8,
        "retrieval_multiscale_max_chunks_per_document": 2,
    }


def test_kb_chat_config_accepts_extended_runtime_retrieval_fields() -> None:
    cfg = KbChatConfig.model_validate(_base_payload())
    assert cfg.decomposition_max_sub_questions == 3
    assert cfg.multi_query_max_variants == 3
    assert cfg.retrieval_hybrid_ranker == "weighted"


@pytest.mark.parametrize("value", [1, 5])
def test_kb_chat_config_rejects_decomposition_count_out_of_range(value: int) -> None:
    payload = _base_payload()
    payload["decomposition_max_sub_questions"] = value
    with pytest.raises(ValidationError):
        KbChatConfig.model_validate(payload)


@pytest.mark.parametrize("value", [1, 5])
def test_kb_chat_config_rejects_multi_query_count_out_of_range(value: int) -> None:
    payload = _base_payload()
    payload["multi_query_max_variants"] = value
    with pytest.raises(ValidationError):
        KbChatConfig.model_validate(payload)


def test_kb_chat_config_rejects_weighted_ranker_when_weights_do_not_sum_to_one() -> None:
    payload = _base_payload()
    payload["retrieval_hybrid_dense_weight"] = 0.8
    payload["retrieval_hybrid_sparse_weight"] = 0.4
    with pytest.raises(ValidationError):
        KbChatConfig.model_validate(payload)


from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.agents.retrieval_subgraph import _compress_context
from app.agents.kb_chat_agentic.schemas import ContextCompressDecision


class _StructuredCompressModel:
    def __init__(self, decision: ContextCompressDecision) -> None:
        self._decision = decision

    async def ainvoke(self, _messages):
        return {"parsed": self._decision}


class _FakeChatModel:
    def __init__(self, decision: ContextCompressDecision) -> None:
        self._decision = decision

    def with_structured_output(self, *_args, **_kwargs):
        return _StructuredCompressModel(self._decision)


def _evidence_item(citation_id: str, excerpt: str) -> dict[str, str]:
    return {
        "citation_id": citation_id,
        "excerpt": excerpt,
        "citation_title": citation_id,
        "citation_source": "kb",
    }


@pytest.mark.asyncio
async def test_context_compress_enforces_budget_cap_when_keep_all_exceeds_target() -> None:
    result = await _compress_context(
        {
            "normalized_query": "问题",
            "final_context": "[S1] AAAAAAAA\n\n[S2] BBBBBBBB",
            "evidence_items": [
                _evidence_item("S1", "A" * 8),
                _evidence_item("S2", "B" * 8),
            ],
            "citation_catalog": {},
            "stage_summaries": {},
        },
        SimpleNamespace(),
        settings=SimpleNamespace(context_retrieval_max_tokens=4),
        chat_model=_FakeChatModel(ContextCompressDecision(decision="keep_all", items=[])),
    )

    assert result["compression_stats"]["fallback_reason"] == "budget_cap_enforced"
    assert result["compression_stats"]["output_tokens"] <= 4
    assert result["final_context"].count("[S") == 1
    assert list(result["citation_catalog"]) == ["S1"]


@pytest.mark.asyncio
async def test_context_compress_budget_cap_prunes_oversized_subset_by_rank_order() -> None:
    result = await _compress_context(
        {
            "normalized_query": "问题",
            "final_context": "[S1] AAAAAAAA\n\n[S2] BBBBBBBB\n\n[S3] CCCCCCCC",
            "evidence_items": [
                _evidence_item("S1", "A" * 8),
                _evidence_item("S2", "B" * 8),
                _evidence_item("S3", "C" * 8),
            ],
            "citation_catalog": {},
            "stage_summaries": {},
        },
        SimpleNamespace(),
        settings=SimpleNamespace(context_retrieval_max_tokens=4),
        chat_model=_FakeChatModel(
            ContextCompressDecision(
                decision="subset",
                items=[
                    {"citation_id": "S1", "excerpt": "A" * 8},
                    {"citation_id": "S2", "excerpt": "B" * 8},
                    {"citation_id": "S3", "excerpt": "C" * 8},
                ],
            )
        ),
    )

    assert result["compression_stats"]["fallback_reason"] == "budget_cap_enforced"
    assert result["compression_stats"]["output_tokens"] <= 4
    assert list(result["citation_catalog"]) == ["S1"]
    assert "[S3]" not in result["final_context"]

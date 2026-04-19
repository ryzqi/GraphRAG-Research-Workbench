"""DeepResearchStructuredResponse 要求 citations[*].excerpts。"""

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from app.services.research_runtime_recovery import (
    DeepResearchStructuredResponseDraft,
    _normalize_structured_response_payload,
)


def _draft_citation(**overrides) -> dict:
    base = {
        "source_type": "web",
        "source_provider": "tavily",
        "retrieval_method": "web_search",
        "source_id": "https://example.com/a",
        "url": "https://example.com/a",
        "origin_url": "https://example.com/a",
        "retrieved_at": datetime.now(timezone.utc).isoformat(),
        "excerpts": [{"text": "x" * 60, "locator": "p1", "lang": "en"}],
    }
    base.update(overrides)
    return base


def test_structured_response_rejects_citation_without_excerpts() -> None:
    payload = {
        "findings": ["a", "b"],
        "citations": [
            _draft_citation(excerpts=[]),
            _draft_citation(),
        ],
    }
    with pytest.raises(ValidationError):
        DeepResearchStructuredResponseDraft.model_validate(payload)


def test_structured_response_accepts_minimal_valid_payload() -> None:
    payload = {
        "findings": ["a", "b"],
        "citations": [_draft_citation(), _draft_citation()],
    }
    draft = DeepResearchStructuredResponseDraft.model_validate(payload)
    assert len(draft.citations) == 2
    assert draft.citations[0].excerpts[0].text.startswith("x")


def test_structured_response_rejects_missing_retrieved_at() -> None:
    payload = {
        "findings": ["a", "b"],
        "citations": [
            _draft_citation(retrieved_at=None),
            _draft_citation(),
        ],
    }
    with pytest.raises(ValidationError):
        DeepResearchStructuredResponseDraft.model_validate(payload)


def test_normalize_payload_backfills_retrieved_at_only() -> None:
    payload = {
        "findings": ["a", "b"],
        "citations": [
            {
                "source_type": "web",
                "source_provider": "tavily",
                "retrieval_method": "web_search",
                "source_id": "https://example.com/a",
                "url": "https://example.com/a",
                "origin_url": "https://example.com/a",
            }
        ],
    }
    normalized = _normalize_structured_response_payload(payload)
    assert normalized["citations"][0]["retrieved_at"]
    assert "excerpts" not in normalized["citations"][0]

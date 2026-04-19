"""ResearchCanonicalCitation excerpt 契约测试。"""

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from app.schemas import research as research_schema


def _excerpt_cls():
    excerpt_cls = getattr(research_schema, "ResearchCitationExcerpt", None)
    assert excerpt_cls is not None, "ResearchCitationExcerpt 未定义"
    return excerpt_cls


def _citation_cls():
    citation_cls = getattr(research_schema, "ResearchCanonicalCitation", None)
    assert citation_cls is not None, "ResearchCanonicalCitation 未定义"
    return citation_cls


def _minimal_web_payload() -> dict:
    return {
        "source_type": research_schema.ResearchSourceType.WEB,
        "source_provider": "tavily",
        "retrieval_method": "web_search",
        "source_id": "https://example.com/a",
        "url": "https://example.com/a",
        "origin_url": "https://example.com/a",
        "retrieved_at": datetime.now(timezone.utc),
        "excerpts": [
            {
                "text": "x" * 60,
                "locator": "para 1",
                "lang": "en",
            }
        ],
    }


def test_excerpt_min_length_rejects_short_text() -> None:
    excerpt_cls = _excerpt_cls()
    with pytest.raises(ValidationError):
        excerpt_cls(text="short", locator=None, lang="en")


def test_excerpt_max_length_rejects_too_long() -> None:
    excerpt_cls = _excerpt_cls()
    with pytest.raises(ValidationError):
        excerpt_cls(text="x" * 401, locator=None, lang="en")


def test_citation_requires_at_least_one_excerpt() -> None:
    payload = _minimal_web_payload()
    payload["excerpts"] = []
    citation_cls = _citation_cls()
    with pytest.raises(ValidationError):
        citation_cls.model_validate(payload)


def test_citation_accepts_up_to_five_excerpts() -> None:
    payload = _minimal_web_payload()
    payload["excerpts"] = [{"text": "y" * 80, "lang": "en"}] * 5
    citation_cls = _citation_cls()
    citation = citation_cls.model_validate(payload)
    assert len(citation.excerpts) == 5


def test_citation_rejects_six_excerpts() -> None:
    payload = _minimal_web_payload()
    payload["excerpts"] = [{"text": "y" * 80, "lang": "en"}] * 6
    citation_cls = _citation_cls()
    with pytest.raises(ValidationError):
        citation_cls.model_validate(payload)


def test_citation_requires_retrieved_at() -> None:
    payload = _minimal_web_payload()
    del payload["retrieved_at"]
    citation_cls = _citation_cls()
    with pytest.raises(ValidationError):
        citation_cls.model_validate(payload)

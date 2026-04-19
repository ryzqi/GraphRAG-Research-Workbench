"""ResearchClaimMap / ResearchEvidenceLedger 契约测试。"""

from datetime import datetime, timezone
import importlib

import pytest
from pydantic import ValidationError


def _workspace_module():
    try:
        return importlib.import_module("app.schemas.research_workspace")
    except ModuleNotFoundError as exc:
        pytest.fail(f"app.schemas.research_workspace 未定义: {exc}")


def _claim_entry_cls():
    return getattr(_workspace_module(), "ResearchClaimEntry")


def _claim_map_cls():
    return getattr(_workspace_module(), "ResearchClaimMap")


def _evidence_entry_cls():
    return getattr(_workspace_module(), "ResearchEvidenceEntry")


def _evidence_ledger_cls():
    return getattr(_workspace_module(), "ResearchEvidenceLedger")


def _claim(**overrides):
    base = {
        "claim_id": "claim-01",
        "section_id": "section-1",
        "claim": "Claude 3.5 Sonnet 在 HumanEval 基准上取得了 92% 的通过率。",
        "status": "pending",
        "confidence": "medium",
        "independence_providers": [],
        "supporting_evidence_ids": [],
        "counter_evidence_ids": [],
        "limitations": [],
        "open_questions": [],
    }
    base.update(overrides)
    return _claim_entry_cls().model_validate(base)


def test_claim_supported_requires_two_independent_providers() -> None:
    with pytest.raises(ValidationError):
        _claim(status="supported", independence_providers=["tavily"])


def test_claim_supported_rejects_workspace_only() -> None:
    with pytest.raises(ValidationError):
        _claim(
            status="supported",
            independence_providers=["workspace", "workspace"],
        )


def test_claim_supported_accepts_two_distinct_non_workspace_providers() -> None:
    claim = _claim(
        status="supported",
        independence_providers=["tavily", "arxiv"],
        supporting_evidence_ids=["e-001", "e-002"],
    )
    assert claim.status == "supported"


def test_evidence_entry_rejects_unknown_relation() -> None:
    with pytest.raises(ValidationError):
        _evidence_entry_cls().model_validate(
            {
                "evidence_id": "e-001",
                "claim_ids": ["claim-01"],
                "citation_index": 0,
                "excerpt_ref": 0,
                "relation": "unknown",
                "confidence": "high",
            }
        )


def test_claim_map_and_ledger_roundtrip() -> None:
    claim_map = _claim_map_cls()(
        claims=[_claim()],
        generated_at=datetime.now(timezone.utc),
    )
    ledger = _evidence_ledger_cls()(
        evidences=[
            _evidence_entry_cls()(
                evidence_id="e-001",
                claim_ids=["claim-01"],
                citation_index=0,
                excerpt_ref=0,
                relation="supports",
                confidence="high",
            )
        ],
        generated_at=datetime.now(timezone.utc),
    )
    assert (
        _claim_map_cls().model_validate_json(claim_map.model_dump_json()).claims[0].claim_id
        == "claim-01"
    )
    assert (
        _evidence_ledger_cls()
        .model_validate_json(ledger.model_dump_json())
        .evidences[0]
        .evidence_id
        == "e-001"
    )

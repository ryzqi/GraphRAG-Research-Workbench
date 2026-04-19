"""breadth gate：证据够了才允许锁定 outline / 派 section-writer / citation-steward。"""

from datetime import datetime, timezone

from app.schemas.research_workspace import (
    ResearchClaimEntry,
    ResearchClaimMap,
    ResearchEvidenceEntry,
    ResearchEvidenceLedger,
)
from app.services.research_runtime_gate import (
    DEFAULT_BREADTH_GATED_TOOL_NAMES,
    evaluate_breadth_gate_status,
    tool_requires_breadth_gate,
)


def _claim(claim_id: str, status: str = "pending") -> ResearchClaimEntry:
    return ResearchClaimEntry.model_validate(
        {
            "claim_id": claim_id,
            "section_id": "section-1",
            "claim": "a" * 10,
            "status": status,
            "confidence": "medium",
        }
    )


def _evidence(claim_id: str) -> ResearchEvidenceEntry:
    return ResearchEvidenceEntry.model_validate(
        {
            "evidence_id": f"e-{claim_id}",
            "claim_ids": [claim_id],
            "citation_index": 0,
            "relation": "supports",
            "confidence": "high",
        }
    )


def test_breadth_gate_blocks_when_pending_claim_has_no_evidence() -> None:
    claim_map = ResearchClaimMap(
        claims=[_claim("c1"), _claim("c2")],
        generated_at=datetime.now(timezone.utc),
    )
    ledger = ResearchEvidenceLedger(
        evidences=[_evidence("c1")],
        generated_at=datetime.now(timezone.utc),
    )
    allowed, reason = evaluate_breadth_gate_status(
        claim_map=claim_map,
        evidence_ledger=ledger,
        plan_complexity="simple",
    )
    assert allowed is False
    assert reason and "breadth gate" in reason


def test_breadth_gate_passes_when_all_pending_claims_have_evidence() -> None:
    claim_map = ResearchClaimMap(
        claims=[_claim("c1")],
        generated_at=datetime.now(timezone.utc),
    )
    ledger = ResearchEvidenceLedger(
        evidences=[_evidence("c1")],
        generated_at=datetime.now(timezone.utc),
    )
    allowed, _ = evaluate_breadth_gate_status(
        claim_map=claim_map,
        evidence_ledger=ledger,
        plan_complexity="simple",
    )
    assert allowed is True


def test_gated_tool_names_target_writer_and_citation() -> None:
    assert tool_requires_breadth_gate("task")
    assert "task" in DEFAULT_BREADTH_GATED_TOOL_NAMES

"""Phase 1 接受性测试。"""

import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any

from app.schemas.research import (
    ResearchCanonicalCitation,
    ResearchCitationExcerpt,
    ResearchSourceTarget,
    ResearchSourceType,
)
from app.services.research_alignment_judge import ClaimAlignmentVerdict
from app.services.research_finalizer import ResearchFinalizer
from app.services.research_observability import build_quality_snapshot
from app.services.research_runtime_context import ResearchRuntimeContextSnapshot
from app.services.research_service_execution import (
    persist_final_report_artifacts,
    persist_metrics_artifacts,
)
from app.services.research_service_session_ops import (
    _quality_findings_from_snapshot,
    _quality_orphan_citation_indices,
)
from app.services.research_source_bundle import ResearchSourceBundle
from tests.integration.fixtures.deep_research.golden_sessions import (
    GOLDEN_G_01,
    GOLDEN_G_04,
)


def _citation(text: str) -> ResearchCanonicalCitation:
    return ResearchCanonicalCitation.model_validate(
        {
            "source_type": ResearchSourceType.WEB,
            "source_provider": "tavily",
            "retrieval_method": "web_search",
            "source_id": "https://example.com/claude-35",
            "url": "https://example.com/claude-35",
            "origin_url": "https://example.com/claude-35",
            "retrieved_at": datetime.now(timezone.utc),
            "excerpts": [ResearchCitationExcerpt(text=text, locator="p1", lang="en")],
        }
    )


class _FixedJudge:
    def __init__(self, verdict: str) -> None:
        self._verdict = verdict

    async def judge_all(self, **_: object) -> list[ClaimAlignmentVerdict]:
        return [
            ClaimAlignmentVerdict(
                claim_id="claim-01",
                verdict=self._verdict,
                supporting_evidence_ids=["e-001"]
                if self._verdict == "supported"
                else [],
                conflicting_evidence_ids=[],
                missing_aspects=[] if self._verdict == "supported" else ["关键事实缺证据"],
                reason="固定裁决",
            )
        ]


class _MemoryArtifactStore:
    def __init__(self) -> None:
        self.json_by_key: dict[str, Any] = {}
        self.text_by_key: dict[str, str | None] = {}

    async def upsert(
        self,
        *,
        session: object,
        artifact_key: str,
        content_text: str | None = None,
        content_json: dict[str, Any] | list[Any] | None = None,
        **_: object,
    ) -> None:
        del session
        if content_json is not None:
            self.json_by_key[artifact_key] = content_json
            return
        self.text_by_key[artifact_key] = content_text


def _snapshot(
    *,
    claim_text: str,
    claim_status: str,
    counter_searched: bool,
    orphan_citations: list[int] | None = None,
) -> ResearchRuntimeContextSnapshot:
    return ResearchRuntimeContextSnapshot(
        claim_map_json={
            "claims": [
                {
                    "claim_id": "claim-01",
                    "claim": claim_text,
                    "status": claim_status,
                    "confidence": "high",
                    "independence_providers": ["tavily", "arxiv"],
                    "supporting_evidence_ids": ["e-001"],
                    "counter_evidence_ids": [],
                    "limitations": [],
                    "open_questions": [],
                }
            ],
            "generated_at": "2026-04-19T00:00:00Z",
        },
        evidence_ledger_json={
            "evidences": [
                {
                    "evidence_id": "e-001",
                    "claim_ids": ["claim-01"],
                    "citation_index": 0,
                    "excerpt_ref": 0,
                    "relation": "supports",
                    "confidence": "high",
                }
            ],
            "generated_at": "2026-04-19T00:00:00Z",
        },
        coverage_critique_json={
            "counter_search_status": [
                {
                    "claim_id": "claim-01",
                    "counter_searched": counter_searched,
                }
            ],
            "orphan_citations": list(orphan_citations or []),
        },
    )


def _persist_artifacts(
    *,
    result: Any,
    runtime_context_snapshot: ResearchRuntimeContextSnapshot,
) -> tuple[_MemoryArtifactStore, dict[str, object]]:
    quality_snapshot = build_quality_snapshot(
        claim_map=list(result.report_json.get("claim_map") or []),
        citations=list(result.report_json.get("citations") or []),
        findings=_quality_findings_from_snapshot(runtime_context_snapshot),
        orphan_citation_indices=_quality_orphan_citation_indices(
            runtime_context_snapshot
        ),
    )
    store = _MemoryArtifactStore()
    session = SimpleNamespace(metrics=None)
    asyncio.run(
        persist_final_report_artifacts(
            artifact_store=store,
            session=session,
            final_result=result,
        )
    )
    asyncio.run(
        persist_metrics_artifacts(
            artifact_store=store,
            session=session,
            metrics={
                "quality_snapshot": quality_snapshot,
                "gate": {"pass": True, "violations": []},
            },
        )
    )
    return store, quality_snapshot


def test_g01_supported_with_excerpt_present() -> None:
    snapshot = _snapshot(
        claim_text="Claude 3.5 Sonnet 在 HumanEval 达 92%。",
        claim_status="supported",
        counter_searched=True,
    )
    bundle = ResearchSourceBundle(
        target_sources=(ResearchSourceTarget.WEB,),
        citations=[_citation("Claude 3.5 Sonnet achieves 92% on HumanEval benchmark.")],
        findings=["Claude 3.5 Sonnet 在 HumanEval 上达到 92%。"],
        interim_summary="",
        coverage_gaps=[],
        provider_counts={"tavily": 1},
    )
    finalizer = ResearchFinalizer(judge=_FixedJudge("supported"))
    result = asyncio.run(
        finalizer.finalize_async(
            question=GOLDEN_G_01.question,
            target_sources=[ResearchSourceTarget.WEB],
            source_bundle=bundle,
            runtime_context_snapshot=snapshot,
        )
    )
    store, quality_snapshot = _persist_artifacts(
        result=result,
        runtime_context_snapshot=snapshot,
    )
    assert result.report_json["claim_map"][0]["verdict"] == "supported"
    assert GOLDEN_G_01.expected_claim_id == result.report_json["claim_map"][0]["claim_id"]
    assert GOLDEN_G_01.expected_citation_excerpt_keyword in (
        result.report_json["citations"][0]["excerpts"][0]["text"]
    )
    assert store.json_by_key["claim_map_json"] == result.report_json["claim_map"]
    assert (
        store.json_by_key["coverage_matrix_json"]
        == result.report_json["coverage_matrix"]
    )
    assert store.json_by_key["source_ledger_json"] == result.report_json["source_ledger"]
    assert store.json_by_key["quality_snapshot"] == quality_snapshot
    assert quality_snapshot["claim_alignment_rate"] == 1.0
    assert quality_snapshot["citation_excerpt_presence"] == 1.0
    assert quality_snapshot["independence_source_ratio"] == 1.0
    assert quality_snapshot["counter_evidence_exposure"] == 1.0
    assert quality_snapshot["citation_orphan_rate"] == 0.0
    assert store.json_by_key["source_ledger_json"][0]["excerpt_count"] == 1


def test_g04_speculative_claim_rejected_as_insufficient() -> None:
    snapshot = _snapshot(
        claim_text="2030 年量子芯片已取代 GPU。",
        claim_status="pending",
        counter_searched=False,
    )
    bundle = ResearchSourceBundle(
        target_sources=(ResearchSourceTarget.WEB,),
        citations=[
            _citation("Quantum chips are still speculative in 2026 with limited deployment.")
        ],
        findings=["量子芯片 2030 年已取代 GPU。"],
        interim_summary="",
        coverage_gaps=[],
        provider_counts={"tavily": 1},
    )
    finalizer = ResearchFinalizer(judge=_FixedJudge("insufficient"))
    result = asyncio.run(
        finalizer.finalize_async(
            question=GOLDEN_G_04.question,
            target_sources=[ResearchSourceTarget.WEB],
            source_bundle=bundle,
            runtime_context_snapshot=snapshot,
        )
    )
    store, quality_snapshot = _persist_artifacts(
        result=result,
        runtime_context_snapshot=snapshot,
    )
    assert result.report_json["claim_map"][0]["verdict"] == "insufficient"
    assert result.report_json["coverage_matrix"]["alignment_pass_rate"] == 0.0
    assert GOLDEN_G_04.expected_claim_id == result.report_json["claim_map"][0]["claim_id"]
    assert GOLDEN_G_04.expected_citation_excerpt_keyword in (
        result.report_json["citations"][0]["excerpts"][0]["text"]
    )
    assert store.json_by_key["claim_map_json"] == result.report_json["claim_map"]
    assert (
        store.json_by_key["coverage_matrix_json"]
        == result.report_json["coverage_matrix"]
    )
    assert store.json_by_key["quality_snapshot"] == quality_snapshot
    assert quality_snapshot["claim_alignment_rate"] == 0.0
    assert quality_snapshot["citation_excerpt_presence"] == 1.0
    assert quality_snapshot["independence_source_ratio"] == 1.0
    assert quality_snapshot["counter_evidence_exposure"] == 0.0
    assert quality_snapshot["citation_orphan_rate"] == 0.0
    assert store.json_by_key["source_ledger_json"][0]["excerpt_count"] == 1

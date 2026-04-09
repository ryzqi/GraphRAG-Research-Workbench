from __future__ import annotations

from app.schemas.research import (
    ResearchCanonicalCitation,
    ResearchSourceTarget,
    ResearchSourceType,
)
from app.services.research_finalizer import ResearchFinalizer
from app.services.research_runtime_context import ResearchRuntimeContextSnapshot
from app.services.research_source_bundle import ResearchSourceBundle


def _build_source_bundle() -> ResearchSourceBundle:
    citations = [
        ResearchCanonicalCitation(
            source_type=ResearchSourceType.WEB,
            source_provider="tavily",
            retrieval_method="search",
            source_id="src-web-1",
            title="供应链分析",
            origin_url="https://example.com/web-1",
        ),
        ResearchCanonicalCitation(
            source_type=ResearchSourceType.PAPER,
            source_provider="arxiv",
            retrieval_method="search",
            source_id="src-paper-1",
            title="HBM 供需论文",
            arxiv_id="2401.12345",
            pdf_url="https://arxiv.org/pdf/2401.12345.pdf",
        ),
    ]
    return ResearchSourceBundle(
        target_sources=(ResearchSourceTarget.WEB, ResearchSourceTarget.PAPER),
        citations=citations,
        findings=["HBM 供应仍然紧张。", "扩产节奏受先进封装与资本开支约束。"],
        interim_summary="已形成基础研究结论。",
        coverage_gaps=["成本拐点时间仍未闭合"],
        provider_counts={"tavily": 1, "arxiv": 1},
    )


def test_research_finalizer_prefers_runtime_context_for_rich_report() -> None:
    finalizer = ResearchFinalizer()
    source_bundle = _build_source_bundle()
    runtime_context = ResearchRuntimeContextSnapshot(
        claim_map_md="# 核心主张\n- Claim A",
        evidence_ledger_md="# 证据账本\n- [1] 官方白皮书支持 Claim A",
        analysis_notes_md="# 中间分析\n- 存在成本侧限制",
        report_outline_md="# 报告提纲\n## 核心结论\n## 证据与反证",
        report_draft_md="# 报告草稿\n## 核心结论\nClaim A 得到部分支持。",
        report_context_json={
            "executive_summary": "Claim A 得到部分支持，但存在成本侧限制。",
            "open_questions": ["成本拐点时间仍未闭合"],
            "has_conflicts": True,
            "confidence_level": "partial",
        },
    )

    result = finalizer.finalize(
        question="HBM 供应链瓶颈是否会持续到 2027 年？",
        target_sources=[ResearchSourceTarget.WEB, ResearchSourceTarget.PAPER],
        source_bundle=source_bundle,
        runtime_context_snapshot=runtime_context,
    )

    assert "## 核心结论" in result.report_md
    assert "## 分主题分析" in result.report_md
    assert "## 结论与建议" in result.report_md
    assert result.report_json["metadata"]["confidence_level"] == "partial"
    assert result.report_json["runtime_context"]["executive_summary"].startswith(
        "Claim A"
    )

from __future__ import annotations

from datetime import datetime, timezone

from app.schemas.research import ResearchCanonicalCitation, ResearchSourceTarget, ResearchSourceType
from app.services.research_report_compiler import compile_report_from_runtime_context
from app.services.research_runtime_context import ResearchRuntimeContextSnapshot
from app.services.research_source_bundle import ResearchSourceBundle


def _build_source_bundle() -> ResearchSourceBundle:
    citation = ResearchCanonicalCitation.model_validate(
        {
            "source_type": ResearchSourceType.WEB,
            "source_provider": "web",
            "retrieval_method": "search",
            "source_id": "source-1",
            "title": "官方说明",
            "url": "https://example.com/report",
            "origin_url": "https://example.com/report",
            "retrieved_at": datetime.now(timezone.utc).isoformat(),
                "excerpts": [
                    {
                        "text": "这是已经核验过的来源摘录，用于支撑最终研究结论与章节论证，同时保留足够上下文以满足最小长度契约要求。",
                        "locator": "section-1",
                        "lang": "zh",
                    }
                ],
        }
    )
    return ResearchSourceBundle(
        target_sources=(ResearchSourceTarget.WEB,),
        citations=[citation],
        findings=["来源显示该方案已经上线，并给出了可核验的效果指标。"],
        interim_summary="已完成首轮证据收集。",
        coverage_gaps=[],
        provider_counts={"web": 1},
    )


def test_compile_report_ignores_outline_scaffold_without_publishable_body() -> None:
    source_bundle = _build_source_bundle()
    runtime_context_snapshot = ResearchRuntimeContextSnapshot(
        report_outline_md=(
            "# Report Outline\n\n"
            "## [section-1] 市场背景\n"
            "- 本节目的：待补充\n"
            "- 计划内容：待补充\n"
            "- 证据要求：待补充\n"
        ),
        report_draft_md="",
        section_briefs_json=[
            {
                "section_id": "section-1",
                "title": "市场背景",
                "description": "先形成章节结构，再等待补证。",
                "summary": "",
                "brief_markdown": "",
                "must_cover": ["章节主结论", "直接证据与 citation 索引"],
                "open_questions": [],
                "citation_indices": [],
            }
        ],
        report_context_json={
            "executive_summary": "研究已经收敛到可验证结论。",
            "confidence_level": "sufficient",
        },
    )

    compiled = compile_report_from_runtime_context(
        question="该方案是否已经落地？",
        source_bundle=source_bundle,
        runtime_context_snapshot=runtime_context_snapshot,
    )

    assert compiled is not None
    assert "## 市场背景" not in compiled.report_md
    assert "待补充" not in compiled.report_md
    assert "## 核心结论" in compiled.report_md
    assert "研究已经收敛到可验证结论。" in compiled.report_md


def test_compile_report_uses_dynamic_sections_when_section_has_real_body() -> None:
    source_bundle = _build_source_bundle()
    runtime_context_snapshot = ResearchRuntimeContextSnapshot(
        report_outline_md=(
            "# Report Outline\n\n"
            "## [section-1] 市场背景\n"
            "- 本节目的：解释为什么该问题值得研究\n"
        ),
        report_draft_md=(
            "# 报告草稿\n\n"
            "## [section-1] 市场背景\n"
            "该方案已在公开资料中明确上线时间、适用范围与效果指标，"
            "并且这些信息之间不存在直接冲突。\n"
        ),
        section_briefs_json=[
            {
                "section_id": "section-1",
                "title": "市场背景",
                "description": "解释研究背景。",
                "summary": "公开资料能够说明该方案的落地背景与实施范围。",
                "brief_markdown": "",
                "must_cover": [],
                "open_questions": [],
                "citation_indices": [1],
            }
        ],
        report_context_json={
            "executive_summary": "研究已经收敛到可验证结论。",
            "confidence_level": "sufficient",
        },
    )

    compiled = compile_report_from_runtime_context(
        question="该方案是否已经落地？",
        source_bundle=source_bundle,
        runtime_context_snapshot=runtime_context_snapshot,
    )

    assert compiled is not None
    assert "## 市场背景" in compiled.report_md
    assert "公开资料能够说明该方案的落地背景与实施范围。" not in compiled.report_md
    assert "该方案已在公开资料中明确上线时间、适用范围与效果指标" in compiled.report_md

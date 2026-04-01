from __future__ import annotations

import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from app.prompts import get_prompt_loader
from app.schemas.research import ResearchCanonicalCitation, ResearchSourceTarget, ResearchSourceType
from app.services.research_finalizer import ResearchFinalizer
from app.services.research_source_bundle import ResearchSourceBundle


def _build_source_bundle() -> ResearchSourceBundle:
    return ResearchSourceBundle(
        target_sources=(ResearchSourceTarget.WEB,),
        citations=[
            ResearchCanonicalCitation(
                source_type=ResearchSourceType.WEB,
                source_provider="workspace",
                retrieval_method="read_file",
                source_id="/workspace/context/research_design.md",
                title="Deep Research 设计稿",
                url="file:///workspace/context/research_design.md",
                origin_url="file:///workspace/context/research_design.md",
                authors=[],
            )
        ],
        findings=[
            "首页输入区应保留居中的英雄式布局。",
            "最终报告正文必须统一按 Markdown 渲染，不能直接裸露 JSON。",
        ],
        interim_summary="已完成页面布局、中文化与正文渲染链路分析。",
        coverage_gaps=["仍需补充一条最终态视觉回归用例。"],
        provider_counts={"workspace": 1},
    )


def test_research_finalizer_outputs_chinese_report_markdown() -> None:
    result = ResearchFinalizer().finalize(
        question="如何把 Deep Research 页面改成 Gemini 风格？",
        target_sources=[ResearchSourceTarget.WEB],
        source_bundle=_build_source_bundle(),
    )

    assert "# 研究报告" in result.report_md
    assert "## 问题" in result.report_md
    assert "## 执行摘要" in result.report_md
    assert "## 关键发现" in result.report_md
    assert "## 证据与反证" in result.report_md
    assert "## 覆盖缺口" in result.report_md
    assert "## 参考来源" in result.report_md
    assert "Research Report" not in result.report_md
    assert "Executive Summary" not in result.report_md
    assert "References" not in result.report_md


def test_research_workspace_templates_are_fully_localized_for_user_visible_markdown() -> None:
    prompts = get_prompt_loader()

    mission_md = prompts.render(
        "research/mission_md",
        session_slug="session-1",
        question="测试问题",
        research_brief="测试摘要",
        target_sources_line="网页",
        budget_guidance="优先官方来源",
    )
    plan_md = prompts.render(
        "research/plan_md",
        summary="先做事实收集，再做交叉验证。",
        subtasks_block="- 子任务一",
    )
    coverage_md = prompts.render("research/coverage_md")
    report_draft_md = prompts.render("research/report_draft_md")

    assert "# 研究任务" in mission_md
    assert "## 研究目标" in mission_md
    assert "## 研究边界" in mission_md
    assert "# 研究计划" in plan_md
    assert "## 摘要" in plan_md
    assert "## 执行规则" in plan_md
    assert "# 覆盖情况" in coverage_md
    assert "## 已覆盖来源" in coverage_md
    assert "## 覆盖标准" in coverage_md
    assert "# 报告草稿" in report_draft_md
    assert "## 执行摘要" in report_draft_md
    assert "## 关键发现" in report_draft_md
    assert "## 证据与反证" in report_draft_md
    assert "## 参考来源" in report_draft_md
    assert "Research Goal" not in mission_md
    assert "Execution Rules" not in plan_md
    assert "Coverage Standards" not in coverage_md
    assert "Executive Summary" not in report_draft_md

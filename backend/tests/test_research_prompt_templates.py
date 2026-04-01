
from __future__ import annotations

from uuid import uuid4

from app.prompts import get_prompt_loader
from app.schemas.research import (
    ResearchCanonicalCitation,
    ResearchComplexity,
    ResearchPlanSnapshot,
    ResearchPlanSubtask,
    ResearchSourceTarget,
    ResearchSourceType,
)
from app.services.research_finalizer import ResearchFinalizer
from app.services.research_query_mesh import build_research_query_mesh
from app.services.research_source_bundle import ResearchSourceBundle
from app.services.research_workspace_files import build_workspace_bootstrap_artifacts


def _loader():
    loader = get_prompt_loader()
    loader.reload()
    return loader


def _plan_snapshot() -> ResearchPlanSnapshot:
    return ResearchPlanSnapshot(
        research_brief="评估当前主流深度研究产品的提示词设计，并输出可执行模板优化建议。",
        complexity=ResearchComplexity.COMPLEX,
        summary="先界定研究范围，再做证据收集、交叉验证与风险梳理。",
        subtasks=[
            ResearchPlanSubtask(
                title="收集主流方案事实",
                description="盘点 OpenAI、Google、Perplexity 等方案的 planning、search、citation 设计。",
                target_sources=[ResearchSourceTarget.WEB],
            ),
            ResearchPlanSubtask(
                title="验证证据与争议",
                description="核对官方资料、限制、冲突点与适用边界。",
                target_sources=[ResearchSourceTarget.WEB, ResearchSourceTarget.PAPER],
            ),
        ],
        target_sources=[ResearchSourceTarget.WEB, ResearchSourceTarget.PAPER],
        budget_guidance="优先官方资料，再补一手论文或原始材料。",
    )


def test_scoper_and_runtime_prompts_encode_research_boundaries_and_verification_rules():
    loader = _loader()

    scoper_system = loader.render("research/scoper_system")
    runtime_system = loader.render("research/runtime_system")
    runtime_user = loader.render(
        "research/runtime_user",
        question="比较热门深度研究提示词",
        research_brief="聚焦 planning、evidence、citations 设计。",
        target_sources="web, paper",
        route_hint="web_search, paper_search",
        workspace_paths_block="- /workspace/context/README.md",
    )

    assert "对象、时间范围、比较维度、成功指标、受众/用途、输出形态" in scoper_system
    assert "默认保守假设" in scoper_system
    assert "先列出拟验证的核心主张" in runtime_system
    assert "主动搜索反证、限制、争议" in runtime_system
    assert "引用优先级" in runtime_user
    assert "结论 -> 证据 -> 冲突/限制 -> 缺口" in runtime_user


def test_workspace_bootstrap_artifacts_render_auditable_mission_and_plan():
    artifacts = build_workspace_bootstrap_artifacts(
        session_id=uuid4(),
        question="调研各热门深度研究的提示词设计",
        plan_snapshot=_plan_snapshot(),
    )

    mission_md = artifacts["mission_md"].content_text
    plan_md = artifacts["plan_md"].content_text
    coverage_md = artifacts["coverage_md"].content_text

    assert mission_md is not None
    assert "## Research Goal" in mission_md
    assert "## Boundaries" in mission_md
    assert "## Default Assumptions" in mission_md
    assert "## Target Sources" in mission_md

    assert plan_md is not None
    assert "### 1. 收集主流方案事实" in plan_md
    assert "- 任务目的：" in plan_md
    assert "- 预期证据：" in plan_md
    assert "- 验证动作：" in plan_md

    assert coverage_md is not None
    assert "未覆盖关键维度" in coverage_md
    assert "补证方向" in coverage_md


def test_query_mesh_templates_generate_research_intent_instead_of_keyword_suffixes():
    mesh = build_research_query_mesh(
        question="热门深度研究提示词设计",
        plan_snapshot=_plan_snapshot(),
    )

    assert any("官方资料" in item and "差异" in item for item in mesh.breadth_queries)
    assert any("核心证据" in item and "原始来源" in item for item in mesh.depth_queries)
    assert any("交叉验证" in item and "一手资料" in item for item in mesh.verification_queries)
    assert any("反例" in item or "限制" in item for item in mesh.verification_queries)


def test_finalizer_report_markdown_uses_auditable_research_sections():
    result = ResearchFinalizer().finalize(
        question="热门深度研究提示词设计有哪些共性",
        target_sources=[ResearchSourceTarget.WEB],
        source_bundle=ResearchSourceBundle(
            target_sources=(ResearchSourceTarget.WEB,),
            citations=[
                ResearchCanonicalCitation(
                    source_type=ResearchSourceType.WEB,
                    source_provider="openai",
                    retrieval_method="web_search",
                    source_id="openai/deep-research",
                    title="OpenAI Deep Research Guide",
                    url="https://developers.openai.com/api/docs/guides/deep-research",
                    origin_url="https://developers.openai.com/api/docs/guides/deep-research",
                )
            ],
            findings=["热门方案普遍采用 planning -> search -> verify -> report 的闭环。"],
            interim_summary="现有证据支持深度研究先做范围收敛，再做多轮检索与验证。",
            coverage_gaps=["仍需补充更多论文型一手资料。"],
            provider_counts={"openai": 1},
        ),
    )

    assert "## Executive Summary" in result.report_md
    assert "## Findings" in result.report_md
    assert "## Evidence and Counter-Evidence" in result.report_md
    assert "## Coverage Gaps" in result.report_md
    assert "## References" in result.report_md


def test_report_generate_prompt_requires_evidence_labels_and_conflict_handling():
    loader = _loader()

    prompt = loader.render_with_few_shot(
        "tools/report_generate",
        question="比较方案 A 与方案 B 的研究能力",
        findings="- 方案 A 覆盖更广",
        evidence_summary='{"confidence_level":"partial","has_conflicts":true}',
        citations="[1] official-doc: excerpt...",
        format_instruction="标准模式",
    )

    assert "已证实" in prompt
    assert "部分支持" in prompt
    assert "证据不足" in prompt
    assert "has_conflicts=true" in prompt
    assert "按 citation 序号组织" in prompt



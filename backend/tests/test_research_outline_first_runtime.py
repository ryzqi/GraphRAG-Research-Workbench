from __future__ import annotations

from types import SimpleNamespace
import uuid

from app.config.runtime_contract import RESEARCH_RUNTIME_REQUEST_CONTEXT
from app.models.research_session import ResearchSession, ResearchSessionStatus
from app.schemas.research import (
    ResearchCanonicalCitation,
    ResearchArtifactRead,
    ResearchComplexity,
    ResearchEventEnvelope,
    ResearchPlanSnapshot,
    ResearchPlanSubtask,
    ResearchSourceTarget,
    ResearchSourceType,
)
from app.services.research_presentation_snapshot import (
    build_research_presentation_snapshot,
)
from app.services.research_report_compiler import compile_report_from_runtime_context
from app.services.research_runtime_context import (
    ResearchRuntimeContextSnapshot,
    build_runtime_context_guide,
)
from app.services.research_runtime_gate import (
    evaluate_outline_gate_status,
    tool_requires_outline_gate,
)
from app.services.research_runtime_skills import build_research_runtime_skill_files
from app.services.research_runtime_types import DEFAULT_RESEARCH_LARGE_RESULT_POLICY
from app.services.research_runtime_workspace import (
    build_runtime_prompt,
    build_runtime_request_files,
    build_session_bootstrap_workspace_files,
)
from app.services.research_source_bundle import ResearchSourceBundle
from app.services.research_workspace_files import (
    build_research_workspace_layout,
    build_runtime_orchestration_scaffold_files,
    build_runtime_report_context_payload,
    build_runtime_section_briefs_payload,
)


def _plan_snapshot() -> ResearchPlanSnapshot:
    return ResearchPlanSnapshot(
        research_brief=(
            "聚焦企业 AI 趋势，综合用户补充的范围与目标受众，"
            "先形成章节提纲，再按章节补证与扩写。"
        ),
        complexity=ResearchComplexity.COMPLEX,
        summary="先梳理技术演进，再分析应用落地与风险边界。",
        subtasks=[
            ResearchPlanSubtask(
                title="技术演进主线",
                description="梳理关键技术路线、驱动因素与最新进展。",
                target_sources=[ResearchSourceTarget.WEB, ResearchSourceTarget.PAPER],
            ),
            ResearchPlanSubtask(
                title="应用与风险边界",
                description="分析落地场景、约束条件与潜在风险。",
                target_sources=[ResearchSourceTarget.WEB],
            ),
        ],
        target_sources=[ResearchSourceTarget.WEB, ResearchSourceTarget.PAPER],
        budget_guidance="优先补齐官方资料与论文，再做综合分析。",
    )


def _session() -> ResearchSession:
    return ResearchSession(
        id=uuid.uuid4(),
        thread_id="thread-1",
        question="当前 AI 领域的最新趋势是什么？",
        status=ResearchSessionStatus.RUNNING,
    )


def _source_bundle() -> ResearchSourceBundle:
    return ResearchSourceBundle(
        target_sources=(ResearchSourceTarget.WEB, ResearchSourceTarget.PAPER),
        citations=[
            ResearchCanonicalCitation(
                source_type=ResearchSourceType.WEB,
                source_provider="tavily",
                retrieval_method="search",
                source_id="src-1",
                title="AI trend report",
                origin_url="https://example.com/ai-trend-report",
                authors=["Example Research"],
            )
        ],
        findings=["企业 AI 正从试验转向流程级落地。"],
        interim_summary="当前证据显示企业 AI 已进入运营化阶段。",
        coverage_gaps=["缺少更多官方财报交叉验证。"],
        provider_counts={"tavily": 1},
    )


def test_section_briefs_expose_outline_first_contract_fields() -> None:
    briefs = build_runtime_section_briefs_payload(plan_snapshot=_plan_snapshot())

    first = briefs[0]

    assert first["description"] == "梳理关键技术路线、驱动因素与最新进展。"
    assert first["writing_goal"]
    assert first["required_inputs"] == [
        "question",
        "research_brief",
        "clarification_context",
        "claim_bundles",
        "evidence_ledger",
    ]
    assert first["owner"] == "section-writer"


def test_report_context_tracks_outline_gate_state() -> None:
    payload = build_runtime_report_context_payload(
        question="当前 AI 领域的最新趋势是什么？",
        plan_snapshot=_plan_snapshot(),
    )

    assert payload["outline_ready"] is False
    assert payload["outline_status"] == "pending"
    assert payload["active_section_id"] is None


def test_runtime_prompt_requires_outline_before_search_and_delegation() -> None:
    prompt = build_runtime_prompt(
        session=_session(),
        plan_snapshot=_plan_snapshot(),
        workspace_paths=("/workspace/research/outline.md",),
    )

    assert "先创建动态全文大纲" in prompt
    assert "在调用 `web_search`、`arxiv_search`、`arxiv_fetch` 或 `task` 之前" in prompt


def test_runtime_context_guide_prioritizes_outline_file() -> None:
    layout = build_research_workspace_layout(uuid.uuid4())
    workspace_files = build_runtime_orchestration_scaffold_files(
        question="当前 AI 领域的最新趋势是什么？",
        plan_snapshot=_plan_snapshot(),
        layout=layout,
    )

    guide = build_runtime_context_guide(
        workspace_files=workspace_files,
        layout=layout,
    )

    assert layout.report_outline_path in guide.priority_paths


def test_compile_report_from_runtime_context_uses_dynamic_outline_sections() -> None:
    compiled = compile_report_from_runtime_context(
        question="当前 AI 领域的最新趋势是什么？",
        source_bundle=_source_bundle(),
        runtime_context_snapshot=ResearchRuntimeContextSnapshot(
            report_outline_md=(
                "# 报告提纲\n\n"
                "## 技术演进主线\n"
                "- 本节说明核心技术路线与驱动因素。\n\n"
                "## 应用与风险边界\n"
                "- 本节说明落地场景、约束与风险。"
            ),
            report_draft_md=(
                "# 报告草稿\n\n"
                "## 技术演进主线\n"
                "企业更关注效率、推理成本与长上下文能力。\n\n"
                "## 应用与风险边界\n"
                "落地重点转向治理、数据安全和供应商依赖。"
            ),
            report_context_json={
                "executive_summary": "报告按动态章节组织。",
                "confidence_level": "partial",
                "section_status": [
                    {
                        "section_id": "section-1",
                        "title": "技术演进主线",
                        "status": "drafted",
                        "owner": "section-writer",
                    },
                    {
                        "section_id": "section-2",
                        "title": "应用与风险边界",
                        "status": "drafted",
                        "owner": "section-writer",
                    },
                ],
            },
            section_briefs_json=[
                {
                    "section_id": "section-1",
                    "title": "技术演进主线",
                    "description": "聚焦核心技术路线。",
                    "summary": "解释路线变化。",
                    "writing_goal": "给出技术脉络。",
                    "required_inputs": ["claim_bundles", "evidence_ledger"],
                    "citation_indices": [1],
                },
                {
                    "section_id": "section-2",
                    "title": "应用与风险边界",
                    "description": "聚焦落地与风险。",
                    "summary": "解释场景与边界。",
                    "writing_goal": "给出应用限制。",
                    "required_inputs": ["claim_bundles", "evidence_ledger"],
                    "citation_indices": [1],
                },
            ],
        ),
    )

    assert compiled is not None
    assert [section["title"] for section in compiled.sections[:2]] == [
        "技术演进主线",
        "应用与风险边界",
    ]
    assert [section["id"] for section in compiled.sections[:2]] == [
        "section-1",
        "section-2",
    ]
    assert "## 技术演进主线" in compiled.report_md
    assert "## 应用与风险边界" in compiled.report_md


def test_runtime_skill_file_requires_outline_gate() -> None:
    skill_text = build_research_runtime_skill_files()[
        "/skills/research-runtime/SKILL.md"
    ]

    assert "先创建动态全文大纲" in skill_text
    assert "先写好 `report-outline`" in skill_text


def test_outline_gate_blocks_search_until_outline_is_ready() -> None:
    allowed, reason = evaluate_outline_gate_status(
        report_outline_md=(
            "# Report Outline\n\n"
            "## <待补章节标题>\n"
            "- 本节目的：待补充\n"
            "- 计划内容：待补充\n"
        ),
        report_context_json={
            "outline_ready": False,
            "outline_status": "pending",
        },
        section_briefs_json=[
            {
                "section_id": "section-1",
                "title": "技术演进主线",
                "summary": "",
                "brief_markdown": "",
            }
        ],
    )

    assert allowed is False
    assert reason is not None
    assert "report-outline" in reason


def test_outline_gate_blocks_when_only_part_of_the_outline_is_ready() -> None:
    allowed, reason = evaluate_outline_gate_status(
        report_outline_md=(
            "# Report Outline\n\n"
            "## 技术演进主线\n"
            "- 本节目的：说明关键技术路线\n"
        ),
        report_context_json={
            "outline_ready": True,
            "outline_status": "ready",
        },
        section_briefs_json=[
            {
                "section_id": "section-1",
                "title": "技术演进主线",
                "summary": "先写技术主线，再补证据。",
                "brief_markdown": "## 技术演进主线\n- 说明驱动因素",
            },
            {
                "section_id": "section-2",
                "title": "应用与风险边界",
                "summary": "",
                "brief_markdown": "",
            },
        ],
    )

    assert allowed is False
    assert reason is not None
    assert "section briefs" in reason


def test_outline_gate_allows_search_after_full_outline_and_section_briefs_exist() -> None:
    allowed, reason = evaluate_outline_gate_status(
        report_outline_md=(
            "# Report Outline\n\n"
            "## 技术演进主线\n"
            "- 本节目的：说明关键技术路线\n"
            "\n"
            "## 应用与风险边界\n"
            "- 本节目的：说明应用场景与风险边界\n"
        ),
        report_context_json={
            "outline_ready": True,
            "outline_status": "ready",
        },
        section_briefs_json=[
            {
                "section_id": "section-1",
                "title": "技术演进主线",
                "summary": "先写技术主线，再补证据。",
                "brief_markdown": "## 技术演进主线\n- 说明驱动因素",
            },
            {
                "section_id": "section-2",
                "title": "应用与风险边界",
                "summary": "先写应用与风险边界，再补证据。",
                "brief_markdown": "## 应用与风险边界\n- 说明场景与限制",
            }
        ],
    )

    assert allowed is True
    assert reason is None
    assert tool_requires_outline_gate("task") is True
    assert tool_requires_outline_gate("web_search") is True
    assert tool_requires_outline_gate("record_runtime_activity") is False


def test_outline_gate_blocks_when_placeholder_sections_remain() -> None:
    allowed, reason = evaluate_outline_gate_status(
        report_outline_md=(
            "# Report Outline\n\n"
            "## 技术演进主线\n"
            "- 本节目的：说明关键技术路线\n"
            "\n"
            "## 应用与风险边界\n"
            "- 本节目的：说明应用场景与风险边界\n"
            "\n"
            "## <待补章节标题>\n"
            "- 本节目的：待补充\n"
        ),
        report_context_json={
            "outline_ready": True,
            "outline_status": "ready",
        },
        section_briefs_json=[
            {
                "section_id": "section-1",
                "title": "技术演进主线",
                "summary": "先写技术主线，再补证据。",
                "brief_markdown": "## 技术演进主线\n- 说明驱动因素",
            },
            {
                "section_id": "section-2",
                "title": "应用与风险边界",
                "summary": "先写应用与风险边界，再补证据。",
                "brief_markdown": "## 应用与风险边界\n- 说明场景与限制",
            },
        ],
    )

    assert allowed is False
    assert reason is not None
    assert "完整" in reason


def test_build_runtime_request_files_always_includes_clarification_context() -> None:
    session = _session()

    request_files = build_runtime_request_files(
        workspace_files={},
        session=session,
        plan_snapshot=_plan_snapshot(),
    )

    clarification_path = RESEARCH_RUNTIME_REQUEST_CONTEXT.clarification_context_path
    assert clarification_path in request_files
    assert "原始问题" in request_files[clarification_path]["content"]
    assert "暂无" in request_files[clarification_path]["content"]


def test_build_runtime_request_files_includes_clarification_context() -> None:
    session = _session()
    session.__dict__["artifacts"] = [
        SimpleNamespace(
            artifact_key="clarification_request",
            content_text=(
                "澄清摘要：聚焦企业场景\n"
                "- q1 当前更关心技术趋势还是落地建议？"
            ),
        ),
        SimpleNamespace(
            artifact_key="clarification_answer",
            content_text="更关注企业落地建议与风险边界。",
        ),
    ]
    workspace_files = build_session_bootstrap_workspace_files(
        session=session,
        large_result_policy=DEFAULT_RESEARCH_LARGE_RESULT_POLICY,
    )

    request_files = build_runtime_request_files(
        workspace_files=workspace_files,
        session=session,
        plan_snapshot=_plan_snapshot(),
    )

    clarification_path = RESEARCH_RUNTIME_REQUEST_CONTEXT.clarification_context_path
    assert clarification_path in request_files
    assert "企业落地建议与风险边界" in request_files[clarification_path]["content"]


def test_compile_report_from_runtime_context_does_not_use_index_fallback_for_section_identity() -> None:
    compiled = compile_report_from_runtime_context(
        question="当前 AI 领域的最新趋势是什么？",
        source_bundle=_source_bundle(),
        runtime_context_snapshot=ResearchRuntimeContextSnapshot(
            report_outline_md=(
                "# 报告提纲\n\n"
                "## 已漂移标题 A\n"
                "- 不应映射到 section-1。\n\n"
                "## 已漂移标题 B\n"
                "- 不应映射到 section-2。"
            ),
            report_draft_md=(
                "# 报告草稿\n\n"
                "## 已漂移标题 A\n"
                "错误正文 A\n\n"
                "## 已漂移标题 B\n"
                "错误正文 B"
            ),
            report_context_json={
                "executive_summary": "报告按动态章节组织。",
                "confidence_level": "partial",
                "section_status": [
                    {
                        "section_id": "section-1",
                        "title": "技术演进主线",
                        "status": "drafted",
                        "owner": "section-writer",
                    },
                    {
                        "section_id": "section-2",
                        "title": "应用与风险边界",
                        "status": "drafted",
                        "owner": "section-writer",
                    },
                ],
            },
            section_briefs_json=[
                {
                    "section_id": "section-1",
                    "title": "技术演进主线",
                    "description": "聚焦核心技术路线。",
                    "summary": "解释路线变化。",
                    "writing_goal": "给出技术脉络。",
                    "required_inputs": ["claim_bundles", "evidence_ledger"],
                    "citation_indices": [1],
                },
                {
                    "section_id": "section-2",
                    "title": "应用与风险边界",
                    "description": "聚焦落地与风险。",
                    "summary": "解释场景与边界。",
                    "writing_goal": "给出应用限制。",
                    "required_inputs": ["claim_bundles", "evidence_ledger"],
                    "citation_indices": [1],
                },
            ],
        ),
    )

    assert compiled is not None
    assert compiled.sections[0]["id"] == "section-1"
    assert compiled.sections[0]["title"] == "技术演进主线"
    assert "错误正文 A" not in compiled.sections[0]["content"]
    assert "解释路线变化。" in compiled.sections[0]["content"]
    assert compiled.sections[1]["id"] == "section-2"
    assert compiled.sections[1]["title"] == "应用与风险边界"
    assert "错误正文 B" not in compiled.sections[1]["content"]
    assert "解释场景与边界。" in compiled.sections[1]["content"]


def test_compile_report_from_runtime_context_prefers_section_id_headings_when_titles_drift() -> None:
    compiled = compile_report_from_runtime_context(
        question="当前 AI 领域的最新趋势是什么？",
        source_bundle=_source_bundle(),
        runtime_context_snapshot=ResearchRuntimeContextSnapshot(
            report_outline_md=(
                "# 报告提纲\n\n"
                "## [section-1] 已漂移标题 A\n"
                "- 与 section-1 对齐。\n\n"
                "## [section-2] 已漂移标题 B\n"
                "- 与 section-2 对齐。"
            ),
            report_draft_md=(
                "# 报告草稿\n\n"
                "## [section-1] 已漂移标题 A\n"
                "正确正文 A\n\n"
                "## [section-2] 已漂移标题 B\n"
                "正确正文 B"
            ),
            report_context_json={
                "executive_summary": "报告按动态章节组织。",
                "confidence_level": "partial",
            },
            section_briefs_json=[
                {
                    "section_id": "section-1",
                    "title": "技术演进主线",
                    "description": "聚焦核心技术路线。",
                    "summary": "解释路线变化。",
                    "writing_goal": "给出技术脉络。",
                    "required_inputs": ["claim_bundles", "evidence_ledger"],
                    "citation_indices": [1],
                },
                {
                    "section_id": "section-2",
                    "title": "应用与风险边界",
                    "description": "聚焦落地与风险。",
                    "summary": "解释场景与边界。",
                    "writing_goal": "给出应用限制。",
                    "required_inputs": ["claim_bundles", "evidence_ledger"],
                    "citation_indices": [1],
                },
            ],
        ),
    )

    assert compiled is not None
    assert compiled.sections[0]["id"] == "section-1"
    assert compiled.sections[0]["title"] == "技术演进主线"
    assert "正确正文 A" in compiled.sections[0]["content"]
    assert compiled.sections[1]["id"] == "section-2"
    assert compiled.sections[1]["title"] == "应用与风险边界"
    assert "正确正文 B" in compiled.sections[1]["content"]


def test_presentation_snapshot_prefers_structured_section_ids_over_markdown_titles() -> None:
    session = ResearchSession(
        id=uuid.uuid4(),
        thread_id="thread-1",
        question="当前 AI 领域的最新趋势是什么？",
        status=ResearchSessionStatus.FINAL,
    )
    artifacts = [
        ResearchArtifactRead(
            artifact_key="report_json",
            content_json={
                "summary": "报告摘要",
                "sections": [
                    {
                        "id": "section-1",
                        "title": "技术演进主线",
                        "content": "正文 A",
                        "level": 2,
                    },
                    {
                        "id": "section-2",
                        "title": "应用与风险边界",
                        "content": "正文 B",
                        "level": 2,
                    },
                ],
                "metadata": {
                    "confidence_level": "partial",
                    "evidence_count": 1,
                    "has_conflicts": False,
                },
            },
            citations=[],
        ),
        ResearchArtifactRead(
            artifact_key="report_md",
            content_text=(
                "# 报告\n\n"
                "## 被改名的章节 A\n"
                "正文 A\n\n"
                "## 被改名的章节 B\n"
                "正文 B\n"
            ),
            citations=[],
        ),
        ResearchArtifactRead(
            artifact_key="metrics_snapshot",
            content_json={},
            citations=[],
        ),
        ResearchArtifactRead(
            artifact_key="gate_snapshot",
            content_json={},
            citations=[],
        ),
    ]

    snapshot = build_research_presentation_snapshot(
        session=session,
        events=[],
        artifacts=artifacts,
    )

    report = snapshot["report"]
    assert report is not None
    assert report["outline"] == [
        {"id": "section-1", "title": "技术演进主线", "level": 2},
        {"id": "section-2", "title": "应用与风险边界", "level": 2},
    ]

"""深度研究 preflight planner。"""

from __future__ import annotations

import re

from app.models.research_session import ResearchSessionStatus
from app.schemas.research import (
    ResearchComplexity,
    ResearchPlanSnapshot,
    ResearchPlanSubtask,
    ResearchSessionCreateRequest,
    ResearchSourceTarget,
)
from app.services.research_planner_types import ResearchPlannerResult

_COMPARATIVE_PATTERNS = (
    "对比",
    "比较",
    "优缺点",
    "区别",
    "vs",
    "versus",
    "benchmark",
)
_PAPER_PATTERNS = (
    "论文",
    "paper",
    "arxiv",
    "literature",
    "survey",
    "综述",
)
_WEB_PATTERNS = (
    "网页",
    "web",
    "官网",
    "最新",
    "新闻",
    "blog",
    "release",
)
_COMPLEX_PATTERNS = (
    "综述",
    "路线图",
    "roadmap",
    "架构",
    "architecture",
    "多阶段",
    "落地建议",
    "2024-2026",
)


class ResearchPlanner:
    """轻量计划器：只产出研究 brief / complexity / subtasks / routing。"""

    def build_plan(self, request: ResearchSessionCreateRequest) -> ResearchPlannerResult:
        question = request.question.strip()
        complexity = self._classify_complexity(question)
        target_source = self._resolve_target_source(
            question=question,
            has_kb=bool(request.selected_kb_ids),
            allow_external=bool(request.allow_external),
        )
        subtasks = self._build_subtasks(
            question=question,
            complexity=complexity,
            target_source=target_source,
            has_kb=bool(request.selected_kb_ids),
            allow_external=bool(request.allow_external),
        )
        confirmation_required = self._resolve_confirmation_requirement(
            complexity=complexity,
            request_override=request.require_confirmation,
        )
        plan_snapshot = ResearchPlanSnapshot(
            research_brief=self._build_research_brief(question=question, target_source=target_source),
            complexity=complexity,
            summary=self._build_summary(complexity=complexity, target_source=target_source),
            target_sources=[target_source],
            subtasks=subtasks,
            budget_guidance=self._build_budget_hint(complexity=complexity),
            confirmation_required=confirmation_required,
        )
        return ResearchPlannerResult(
            plan_snapshot=plan_snapshot,
            auto_approve=not confirmation_required,
            next_status=(
                ResearchSessionStatus.QUEUED
                if not confirmation_required
                else ResearchSessionStatus.AWAITING_CONFIRMATION
            ),
        )

    def _classify_complexity(self, question: str) -> ResearchComplexity:
        normalized = question.lower()
        if any(pattern in normalized for pattern in _COMPLEX_PATTERNS):
            return ResearchComplexity.COMPLEX
        if any(pattern in normalized for pattern in _COMPARATIVE_PATTERNS):
            return ResearchComplexity.COMPARATIVE
        if self._looks_multi_clause(normalized):
            return ResearchComplexity.COMPLEX
        return ResearchComplexity.SIMPLE

    def _resolve_target_source(
        self,
        *,
        question: str,
        has_kb: bool,
        allow_external: bool,
    ) -> ResearchSourceTarget:
        normalized = question.lower()
        mentions_paper = any(pattern in normalized for pattern in _PAPER_PATTERNS)
        mentions_web = allow_external and any(pattern in normalized for pattern in _WEB_PATTERNS)

        if has_kb and allow_external and (mentions_paper or mentions_web or "结合" in normalized):
            return ResearchSourceTarget.HYBRID
        if has_kb and not allow_external:
            return ResearchSourceTarget.KB
        if mentions_paper:
            return ResearchSourceTarget.PAPER
        return ResearchSourceTarget.WEB if allow_external else ResearchSourceTarget.KB

    def _build_subtasks(
        self,
        *,
        question: str,
        complexity: ResearchComplexity,
        target_source: ResearchSourceTarget,
        has_kb: bool,
        allow_external: bool,
    ) -> list[ResearchPlanSubtask]:
        if complexity == ResearchComplexity.SIMPLE:
            return [
                ResearchPlanSubtask(
                    title="锁定核心问题",
                    description=f"围绕“{question}”整理直接回答所需的最小证据。",
                    target_sources=[target_source],
                )
            ]

        if complexity == ResearchComplexity.COMPARATIVE:
            return [
                ResearchPlanSubtask(
                    title="定义比较维度",
                    description="先明确比较对象、评价维度与结论形式。",
                    target_sources=[target_source],
                ),
                ResearchPlanSubtask(
                    title="收集对比证据",
                    description="按统一维度收集证据，避免运行时边查边改问题定义。",
                    target_sources=[target_source],
                ),
            ]

        subtasks: list[ResearchPlanSubtask] = []
        if has_kb:
            subtasks.append(
                ResearchPlanSubtask(
                    title="抽取内部基线",
                    description="先从内部知识库确认已有结论、术语与约束，避免重复研究。",
                    target_sources=[ResearchSourceTarget.KB],
                )
            )
        subtasks.append(
            ResearchPlanSubtask(
                title="建立论文基线",
                description="优先收集论文 / 技术综述，形成稳定的研究主线。",
                target_sources=[ResearchSourceTarget.PAPER],
            )
        )
        if allow_external:
            subtasks.append(
                ResearchPlanSubtask(
                    title="补充网页上下文",
                    description="使用网页资料补充实现细节、版本差异与最新生态信息。",
                    target_sources=[ResearchSourceTarget.WEB],
                )
            )
        subtasks.append(
            ResearchPlanSubtask(
                title="整理最终回答结构",
                description="在正式 runtime 前先固定最终回答需要覆盖的输出结构与边界。",
                target_sources=[target_source],
            )
        )
        return subtasks

    def _resolve_confirmation_requirement(
        self,
        *,
        complexity: ResearchComplexity,
        request_override: bool | None,
    ) -> bool:
        if request_override is not None:
            return bool(request_override)
        return complexity in {ResearchComplexity.COMPARATIVE, ResearchComplexity.COMPLEX}

    def _build_research_brief(
        self,
        *,
        question: str,
        target_source: ResearchSourceTarget,
    ) -> str:
        source_hint = {
            ResearchSourceTarget.KB: "以内部知识库为主",
            ResearchSourceTarget.WEB: "以网页资料为主",
            ResearchSourceTarget.PAPER: "以论文资料为主",
            ResearchSourceTarget.HYBRID: "以论文/网页/内部知识混合路线为主",
        }[target_source]
        return f"{source_hint}，围绕问题“{question}”形成可执行研究边界与输出目标。"

    def _build_summary(
        self,
        *,
        complexity: ResearchComplexity,
        target_source: ResearchSourceTarget,
    ) -> str:
        if complexity == ResearchComplexity.SIMPLE:
            return f"简单问题，走 {target_source.value} 单路线即可。"
        if complexity == ResearchComplexity.COMPARATIVE:
            return f"比较型问题，先固定维度，再按 {target_source.value} 路线收集证据。"
        return (
            "复杂问题，需要先固定 brief，再按阶段推进研究；"
            f"当前建议主路线为 {target_source.value}。"
        )

    def _build_budget_hint(self, *, complexity: ResearchComplexity) -> str:
        if complexity == ResearchComplexity.SIMPLE:
            return "低预算：单轮规划、单路线执行，默认可 auto-approve。"
        if complexity == ResearchComplexity.COMPARATIVE:
            return "中预算：至少两个对比子任务，建议先确认计划再执行。"
        return "高预算：长时研究，建议先确认计划，并保留 interrupt / resume。"

    def _looks_multi_clause(self, question: str) -> bool:
        separators = re.split(r"[，,。.;；\n]", question)
        meaningful = [part.strip() for part in separators if part.strip()]
        return len(meaningful) >= 3 or question.count("并") >= 2 or question.count("同时") >= 1

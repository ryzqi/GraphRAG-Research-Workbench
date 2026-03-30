"""深度研究 preflight planner。"""

from __future__ import annotations

import re

from app.models.research_session import ResearchSessionStatus
from app.schemas.research import (
    ResearchComplexity,
    ResearchClarificationQuestion,
    ResearchClarificationRequest,
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
    "开源",
    "实现",
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
_UNCLEAR_PATTERNS = (
    "帮我研究",
    "帮忙研究",
)
_GENERIC_SCOPE_PATTERNS = (
    "ai 编程工具",
    "ai 工具",
    "ai工具",
    "编程工具",
    "ai 编程",
)
_SPECIFIC_MARKERS = (
    "langgraph",
    "stategraph",
    "langchain",
    "openai",
    "claude",
    "gpt",
    "copilot",
    "cursor",
)


class ResearchPlanner:
    """轻量计划器：只产出 research brief / complexity / subtasks / routing。"""

    def build_plan(self, request: ResearchSessionCreateRequest) -> ResearchPlannerResult:
        question = request.question.strip()
        clarification_request = self._maybe_build_clarification(question)
        if clarification_request is not None:
            return ResearchPlannerResult(
                plan_snapshot=None,
                clarification_request=clarification_request,
                auto_approve=False,
                next_status=ResearchSessionStatus.CLARIFYING,
            )

        complexity = self._classify_complexity(question)
        target_sources = self._resolve_target_sources(
            question=question,
            complexity=complexity,
        )
        subtasks = self._build_subtasks(
            question=question,
            complexity=complexity,
            target_sources=target_sources,
        )
        confirmation_required = self._resolve_confirmation_requirement(
            complexity=complexity,
            request_override=None,
        )
        plan_snapshot = ResearchPlanSnapshot(
            research_brief=self._build_research_brief(
                question=question,
                target_sources=target_sources,
            ),
            complexity=complexity,
            summary=self._build_summary(
                complexity=complexity,
                target_sources=target_sources,
            ),
            target_sources=target_sources,
            subtasks=subtasks,
            budget_guidance=self._build_budget_hint(complexity=complexity),
            confirmation_required=confirmation_required,
        )
        return ResearchPlannerResult(
            plan_snapshot=plan_snapshot,
            clarification_request=None,
            auto_approve=False,
            next_status=ResearchSessionStatus.AWAITING_CONFIRMATION,
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

    def _resolve_target_sources(
        self,
        *,
        question: str,
        complexity: ResearchComplexity,
    ) -> list[ResearchSourceTarget]:
        normalized = question.lower()
        mentions_paper = any(pattern in normalized for pattern in _PAPER_PATTERNS)
        mentions_web = any(pattern in normalized for pattern in _WEB_PATTERNS)

        if mentions_paper and (mentions_web or complexity == ResearchComplexity.COMPLEX):
            return [ResearchSourceTarget.PAPER, ResearchSourceTarget.WEB]
        if mentions_paper:
            return [ResearchSourceTarget.PAPER]
        return [ResearchSourceTarget.WEB]

    def _build_subtasks(
        self,
        *,
        question: str,
        complexity: ResearchComplexity,
        target_sources: list[ResearchSourceTarget],
    ) -> list[ResearchPlanSubtask]:
        if complexity == ResearchComplexity.SIMPLE:
            return [
                ResearchPlanSubtask(
                    title="锁定核心问题",
                    description=f"围绕“{question}”整理直接回答所需的最小外部证据。",
                    target_sources=target_sources,
                )
            ]

        if complexity == ResearchComplexity.COMPARATIVE:
            return [
                ResearchPlanSubtask(
                    title="定义比较维度",
                    description="先明确比较对象、评价维度与结论形式。",
                    target_sources=target_sources,
                ),
                ResearchPlanSubtask(
                    title="收集对比证据",
                    description="按统一维度收集网页/论文证据，避免运行时边查边改问题定义。",
                    target_sources=target_sources,
                ),
            ]

        subtasks: list[ResearchPlanSubtask] = []
        if ResearchSourceTarget.PAPER in target_sources:
            subtasks.append(
                ResearchPlanSubtask(
                    title="建立论文基线",
                    description="优先收集论文 / 技术综述，形成稳定的研究主线。",
                    target_sources=[ResearchSourceTarget.PAPER],
                )
            )
        if ResearchSourceTarget.WEB in target_sources:
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
                target_sources=target_sources,
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
        return True

    def _build_research_brief(
        self,
        *,
        question: str,
        target_sources: list[ResearchSourceTarget],
    ) -> str:
        if target_sources == [ResearchSourceTarget.WEB]:
            source_hint = "以网页资料为主"
        elif target_sources == [ResearchSourceTarget.PAPER]:
            source_hint = "以论文资料为主"
        else:
            source_hint = "以论文与网页资料联合路线为主"
        return f"{source_hint}，围绕问题“{question}”形成可执行研究边界与输出目标。"

    def _build_summary(
        self,
        *,
        complexity: ResearchComplexity,
        target_sources: list[ResearchSourceTarget],
    ) -> str:
        route_label = "/".join(item.value for item in target_sources)
        if complexity == ResearchComplexity.SIMPLE:
            return f"简单问题，走 {route_label} 路线即可。"
        if complexity == ResearchComplexity.COMPARATIVE:
            return f"比较型问题，先固定维度，再按 {route_label} 路线收集证据。"
        return (
            "复杂问题，需要先固定 brief，再按阶段推进研究；"
            f"当前建议主路线为 {route_label}。"
        )

    def _build_budget_hint(self, *, complexity: ResearchComplexity) -> str:
        if complexity == ResearchComplexity.SIMPLE:
            return "低预算：单轮规划、单路线执行，确认后再进入执行。"
        if complexity == ResearchComplexity.COMPARATIVE:
            return "中预算：至少两个对比子任务，建议先确认计划再执行。"
        return "高预算：长时研究，建议先确认计划，并保留 interrupt / resume。"

    def _looks_multi_clause(self, question: str) -> bool:
        separators = re.split(r"[，,。.;；\n]", question)
        meaningful = [part.strip() for part in separators if part.strip()]
        return len(meaningful) >= 3 or question.count("并") >= 2 or question.count("同时") >= 1

    def _maybe_build_clarification(
        self, question: str
    ) -> ResearchClarificationRequest | None:
        normalized = question.lower()
        if not any(pattern in normalized for pattern in _UNCLEAR_PATTERNS):
            return None

        clarification_note = ""
        if "补充说明：" in question:
            clarification_note = question.split("补充说明：", 1)[1].strip()
        target_text = clarification_note or question
        target_normalized = target_text.lower()

        if any(marker in target_normalized for marker in _SPECIFIC_MARKERS):
            return None
        if any(pattern in target_normalized for pattern in _GENERIC_SCOPE_PATTERNS):
            return ResearchClarificationRequest(
                summary="当前问题过于宽泛，需要先补充研究范围。",
                questions=[
                    ResearchClarificationQuestion(
                        id="scope",
                        question="希望聚焦在哪类 AI 编程工具或具体使用场景？",
                        why_it_matters="范围过大时无法确定检索重点与最终输出结构。",
                    )
                ],
            )
        return None

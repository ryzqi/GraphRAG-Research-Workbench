from __future__ import annotations

import pytest

from app.schemas.research import ResearchPlanSnapshot, ResearchSourceTarget
from app.services import research_planner as planner_module
from app.services.research_planner import LLMResearchScoper


@pytest.mark.asyncio
async def test_function_calling_scoper_forced_proceed_uses_proceed_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scoper = LLMResearchScoper()
    calls: list[tuple[str, str]] = []

    monkeypatch.setattr(
        planner_module,
        "create_chat_model",
        lambda **_: object(),
    )
    monkeypatch.setattr(
        scoper,
        "_structured_output_method",
        lambda: "function_calling",
    )

    async def fake_invoke_structured_payload(
        self: LLMResearchScoper,
        *,
        model: object,
        schema: type,
        method: str,
        messages: list,
        stage: str,
    ) -> object:
        del self, model, method, messages
        calls.append((schema.__name__, stage))
        if schema is planner_module._ResearchScoperDecisionOutput:
            return planner_module._ResearchScoperDecisionOutput(decision="proceed")
        if schema is planner_module._ResearchScoperProceedOutput:
            return planner_module._ResearchScoperProceedOutput(
                summary="研究 2025-2026 RAG 最新进展",
                research_brief="围绕 2025-2026 年 RAG 架构、评估和工程趋势开展中文综述。",
                complexity="complex",
                target_sources=["web", "paper"],
                subtasks=[
                    planner_module._ResearchScoperSubtaskOutput(
                        title="梳理代表方向",
                        description="检索 2025-2026 年 RAG 架构、Agentic RAG、多模态 RAG 和评估基准。",
                        target_sources=["paper", "web"],
                    )
                ],
                budget_guidance="优先近一年论文和工程报告。",
            )
        raise AssertionError(f"unexpected schema: {schema.__name__}")

    monkeypatch.setattr(
        LLMResearchScoper,
        "_invoke_structured_payload",
        fake_invoke_structured_payload,
    )

    result = await scoper.scope(
        question=(
            "原始问题：当前RAG领域的最近研究\n\n"
            "本轮补充：最近指 2025 年至 2026 年，重点关注架构、评估和工程趋势。"
        ),
        allow_clarify=False,
    )

    assert isinstance(result, ResearchPlanSnapshot)
    assert result.research_brief == "围绕 2025-2026 年 RAG 架构、评估和工程趋势开展中文综述。"
    assert result.target_sources == [ResearchSourceTarget.WEB, ResearchSourceTarget.PAPER]
    assert [schema for schema, _stage in calls] == ["_ResearchScoperProceedOutput"]


@pytest.mark.asyncio
async def test_function_calling_forced_proceed_retries_once_after_invalid_schema(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scoper = LLMResearchScoper()
    calls: list[str] = []

    monkeypatch.setattr(
        planner_module,
        "create_chat_model",
        lambda **_: object(),
    )
    monkeypatch.setattr(
        scoper,
        "_structured_output_method",
        lambda: "function_calling",
    )

    async def fake_invoke_structured_payload(
        self: LLMResearchScoper,
        *,
        model: object,
        schema: type,
        method: str,
        messages: list,
        stage: str,
    ) -> object:
        del self, model, method, messages
        assert schema is planner_module._ResearchScoperProceedOutput
        calls.append(stage)
        if len(calls) == 1:
            raise RuntimeError(
                "Research scoper forced proceed structured output 解析失败: "
                "function_calling:invalid_schema"
            )
        return planner_module._ResearchScoperProceedOutput(
            summary="研究 2025-2026 RAG 最新进展",
            research_brief="围绕 2025-2026 年 RAG 架构、评估和工程趋势开展中文综述。",
            complexity="complex",
            target_sources=["web", "paper"],
            subtasks=[
                planner_module._ResearchScoperSubtaskOutput(
                    title="梳理代表方向",
                    description="检索 2025-2026 年 RAG 架构、Agentic RAG、多模态 RAG 和评估基准。",
                    target_sources=["paper", "web"],
                )
            ],
            budget_guidance="优先近一年论文和工程报告。",
        )

    monkeypatch.setattr(
        LLMResearchScoper,
        "_invoke_structured_payload",
        fake_invoke_structured_payload,
    )

    result = await scoper.scope(
        question=(
            "原始问题：当前RAG领域的最近研究\n\n"
            "本轮补充：最近指 2025 年至 2026 年，重点关注架构、评估和工程趋势。"
        ),
        allow_clarify=False,
    )

    assert isinstance(result, ResearchPlanSnapshot)
    assert result.target_sources == [ResearchSourceTarget.WEB, ResearchSourceTarget.PAPER]
    assert calls == ["forced proceed", "forced proceed"]

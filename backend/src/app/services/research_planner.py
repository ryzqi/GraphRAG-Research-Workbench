"""深度研究 preflight planner。"""

from __future__ import annotations

import json
from typing import Literal, Protocol

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)

from app.core.settings import Settings, get_settings
from app.integrations.chat_model_factory import create_chat_model
from app.prompts import get_prompt_loader
from app.models.research_session import ResearchSessionStatus
from app.schemas.research import (
    ResearchClarificationQuestion,
    ResearchClarificationRequest,
    ResearchComplexity,
    ResearchPlanSnapshot,
    ResearchPlanSubtask,
    ResearchSessionCreateRequest,
    ResearchSourceTarget,
)
from app.services.query_rewrite_service import coerce_structured_result_payload
from app.services.research_planner_types import ResearchPlannerResult

class ResearchScoper(Protocol):
    async def scope(
        self,
        *,
        question: str,
    ) -> ResearchClarificationRequest | ResearchPlanSnapshot: ...


class _ResearchScoperQuestionOutput(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str = Field(default="q1", description="Stable question identifier.")
    question: str = Field(description="Concrete clarifying question to ask the user.")
    why_it_matters: str = Field(
        description="Why this clarifying question materially affects research quality."
    )


class _ResearchScoperSubtaskOutput(BaseModel):
    model_config = ConfigDict(extra="ignore")

    title: str = Field(description="Short subtask title.")
    description: str = Field(description="What this research subtask needs to accomplish.")
    target_sources: list[str] = Field(
        default_factory=list,
        description="Suggested source targets for this subtask. Prefer web or paper.",
    )

    @field_validator("target_sources", mode="before")
    @classmethod
    def _normalize_nullable_target_sources(cls, value: object) -> object:
        if value is None:
            return []
        return value


class _ResearchScoperOutput(BaseModel):
    """Research preflight scoper structured output.

    这是 LLM/provider 边界上的传输 DTO，不是内部领域模型。
    这里允许忽略顶层附加元数据，随后再映射为严格的
    ResearchClarificationRequest / ResearchPlanSnapshot。
    """

    model_config = ConfigDict(
        extra="ignore",
        json_schema_extra={
            "description": "Structured decision for whether deep research should ask clarifying questions or start immediately."
        },
    )

    decision: Literal["clarify", "proceed"] = Field(
        description="Whether to ask the user for more information or proceed directly into research."
    )
    summary: str = Field(
        ...,
        min_length=1,
        description="User-facing summary of the decision. For proceed it summarizes the research plan; for clarify it explains why more information is needed.",
    )
    questions: list[_ResearchScoperQuestionOutput] = Field(
        default_factory=list,
        description="Clarifying questions to ask when decision is clarify. Leave empty when decision is proceed.",
    )
    research_brief: str | None = Field(
        default=None,
        description="Executable research brief when decision is proceed.",
    )
    complexity: str | None = Field(
        default=None,
        description="Research complexity classification when decision is proceed.",
    )
    target_sources: list[str] = Field(
        default_factory=list,
        description="Planned source targets when decision is proceed. Only use web or paper.",
    )
    subtasks: list[_ResearchScoperSubtaskOutput] = Field(
        default_factory=list,
        description="Executable research subtasks when decision is proceed.",
    )
    budget_guidance: str | None = Field(
        default=None,
        description="Optional guidance about expected research effort or budget.",
    )

    @field_validator("questions", "target_sources", "subtasks", mode="before")
    @classmethod
    def _normalize_nullable_list_fields(cls, value: object) -> object:
        if value is None:
            return []
        return value

    @field_validator("research_brief", mode="before")
    @classmethod
    def _normalize_structured_research_brief(cls, value: object) -> object:
        if value is None or isinstance(value, str):
            return value
        if isinstance(value, (dict, list)):
            return json.dumps(value, ensure_ascii=False, indent=2)
        return str(value)

    @model_validator(mode="after")
    def _validate_shape(self) -> "_ResearchScoperOutput":
        if self.decision == "clarify":
            if not self.questions:
                raise ValueError("clarify 决策必须提供 questions")
            return self
        if not self.research_brief:
            raise ValueError("proceed 决策必须提供 research_brief")
        if self.complexity is None:
            raise ValueError("proceed 决策必须提供 complexity")
        if not self.target_sources:
            raise ValueError("proceed 决策必须提供 target_sources")
        if not self.subtasks:
            raise ValueError("proceed 决策必须提供 subtasks")
        return self


class LLMResearchScoper:
    def __init__(self, *, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        self._prompts = get_prompt_loader()

    async def scope(
        self,
        *,
        question: str,
    ) -> ResearchClarificationRequest | ResearchPlanSnapshot:
        model = create_chat_model(settings=self._settings, use_previous_response_id=False)
        structured_model = model.with_structured_output(
            _ResearchScoperOutput,
            method="function_calling",
            include_raw=True,
        )
        result = await structured_model.ainvoke(
            [
                SystemMessage(
                    content=self._prompts.render_with_few_shot("research/scoper_system")
                ),
                HumanMessage(
                    content=self._prompts.render_with_few_shot(
                        "research/scoper_user",
                        question=question.strip(),
                    )
                ),
            ]
        )
        payload, reason = coerce_structured_result_payload(
            result=result,
            schema=_ResearchScoperOutput,
        )
        if payload is None:
            raise RuntimeError(f"Research scoper structured output 解析失败: {reason or 'unknown'}")
        if not isinstance(payload, _ResearchScoperOutput):
            try:
                payload = _ResearchScoperOutput.model_validate(payload)
            except ValidationError as exc:
                raise RuntimeError("Research scoper structured output 不符合契约") from exc

        if payload.decision == "clarify":
            return ResearchClarificationRequest(
                summary=payload.summary,
                questions=[
                    ResearchClarificationQuestion(
                        id=(item.id or f"q{index}").strip() or f"q{index}",
                        question=item.question.strip(),
                        why_it_matters=item.why_it_matters.strip(),
                    )
                    for index, item in enumerate(payload.questions, start=1)
                ],
            )
        complexity = str(payload.complexity or "").strip().lower()
        if complexity not in {item.value for item in ResearchComplexity}:
            complexity = ResearchComplexity.COMPARATIVE.value

        def _normalize_target_sources(items: list[str]) -> list[ResearchSourceTarget]:
            normalized: list[ResearchSourceTarget] = []
            for item in items:
                candidate = str(item or "").strip().lower()
                if candidate == ResearchSourceTarget.PAPER.value:
                    normalized.append(ResearchSourceTarget.PAPER)
                elif candidate == ResearchSourceTarget.WEB.value:
                    normalized.append(ResearchSourceTarget.WEB)
            if not normalized:
                normalized.append(ResearchSourceTarget.WEB)
            deduped: list[ResearchSourceTarget] = []
            for item in normalized:
                if item not in deduped:
                    deduped.append(item)
            return deduped

        return ResearchPlanSnapshot(
            research_brief=payload.research_brief.strip(),
            complexity=ResearchComplexity(complexity),
            summary=payload.summary,
            subtasks=[
                ResearchPlanSubtask(
                    title=item.title.strip(),
                    description=item.description.strip(),
                    target_sources=_normalize_target_sources(item.target_sources),
                )
                for item in payload.subtasks
            ],
            target_sources=_normalize_target_sources(payload.target_sources),
            budget_guidance=payload.budget_guidance,
        )


class ResearchPlanner:
    """LLM 驱动的 preflight planner：产出 clarification request 或 research plan。"""

    def __init__(
        self,
        *,
        scoper: ResearchScoper | None = None,
        settings: Settings | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._scoper = scoper or LLMResearchScoper(settings=self._settings)

    async def build_plan(self, request: ResearchSessionCreateRequest) -> ResearchPlannerResult:
        question = request.question.strip()
        scoped = await self._scoper.scope(question=question)
        if isinstance(scoped, ResearchClarificationRequest):
            return ResearchPlannerResult(
                plan_snapshot=None,
                clarification_request=scoped,
                auto_approve=False,
                next_status=ResearchSessionStatus.CLARIFYING,
            )

        return ResearchPlannerResult(
            plan_snapshot=scoped,
            clarification_request=None,
            auto_approve=False,
            next_status=ResearchSessionStatus.PLAN_READY,
        )

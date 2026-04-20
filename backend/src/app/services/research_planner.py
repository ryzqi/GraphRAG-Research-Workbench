"""深度研究 preflight planner。"""

from __future__ import annotations

import json
import logging
from typing import Literal, Protocol, TypeVar

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)

from app.core.errors import AppError
from app.core.settings import Settings, get_settings
from app.integrations.chat_model_cache import (
    create_chat_model_cached as create_chat_model,
)
from app.integrations.model_runtime_config import ModelRuntimeConfigManager
from app.models.model_config import ModelProvider
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


_DEFAULT_SCOPER_STRUCTURED_METHOD = "function_calling"
_OLLAMA_SCOPER_STRUCTURED_METHOD = "json_mode"
SchemaT = TypeVar("SchemaT", bound=BaseModel)
logger = logging.getLogger(__name__)


class ResearchScoper(Protocol):
    async def scope(
        self,
        *,
        question: str,
        allow_clarify: bool = True,
    ) -> ResearchClarificationRequest | ResearchPlanSnapshot: ...


def _map_research_planner_exception(exc: Exception) -> AppError | None:
    mod = exc.__class__.__module__ or ""
    exc_type = type(exc).__name__
    if mod.startswith("openai"):
        if exc_type == "APITimeoutError":
            return AppError(
                code="RESEARCH_LLM_UPSTREAM_TIMEOUT",
                message="研究计划生成超时，请稍后重试；若频繁出现，请检查模型超时配置或上游服务负载",
                status_code=504,
                details={"exc_type": exc_type},
            )
        if exc_type == "APIConnectionError":
            return AppError(
                code="RESEARCH_LLM_CONNECTION_ERROR",
                message="大模型服务连接失败，请检查 Base URL、网络连通性或上游服务状态",
                status_code=503,
                details={"exc_type": exc_type},
            )
        status_code = getattr(exc, "status_code", None)
        if status_code is None:
            response = getattr(exc, "response", None)
            status_code = getattr(response, "status_code", None)
        if isinstance(status_code, int):
            if status_code in {401, 403}:
                return AppError(
                    code="RESEARCH_LLM_AUTH_ERROR",
                    message="研究计划生成鉴权失败，请前往“模型配置”页面检查 API Key / Base URL 配置",
                    status_code=500,
                    details={"upstream_status_code": status_code},
                )
            if status_code == 429:
                return AppError(
                    code="RESEARCH_LLM_RATE_LIMITED",
                    message="研究计划生成被上游限流，请稍后重试",
                    status_code=503,
                    details={"upstream_status_code": status_code},
                )
            if status_code >= 500:
                return AppError(
                    code="RESEARCH_LLM_UPSTREAM_ERROR",
                    message="上游大模型服务暂时不可用，请稍后重试",
                    status_code=503,
                    details={"upstream_status_code": status_code},
                )
    if isinstance(exc, RuntimeError):
        message = str(exc)
        if (
            "Research scoper" in message
            and "structured output" in message
            and "invalid_schema" in message
        ):
            return AppError(
                code="RESEARCH_SCOPER_INVALID_SCHEMA",
                message="研究计划结构化输出解析失败，请稍后重试",
                status_code=502,
                details={"reason": "invalid_schema"},
            )
    return None


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
    description: str = Field(
        description="What this research subtask needs to accomplish."
    )
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


class _ResearchScoperDecisionOutput(BaseModel):
    model_config = ConfigDict(extra="ignore")

    decision: Literal["clarify", "proceed"] = Field(
        description="Whether deep research needs clarification before execution."
    )


class _ResearchScoperClarifyOutput(BaseModel):
    model_config = ConfigDict(extra="ignore")

    summary: str = Field(
        ...,
        min_length=1,
        description="User-facing summary of the missing information that blocks research.",
    )
    questions: list[_ResearchScoperQuestionOutput] = Field(
        default_factory=list,
        description="One or two concrete clarifying questions.",
    )

    @field_validator("questions", mode="before")
    @classmethod
    def _normalize_nullable_questions(cls, value: object) -> object:
        if value is None:
            return []
        return value

    @model_validator(mode="after")
    def _validate_questions(self) -> "_ResearchScoperClarifyOutput":
        if not self.questions:
            raise ValueError("clarify 输出必须提供 questions")
        return self


class _ResearchScoperProceedOutput(BaseModel):
    model_config = ConfigDict(extra="ignore")

    summary: str = Field(
        ...,
        min_length=1,
        description="User-facing summary of the research direction and assumptions.",
    )
    research_brief: str = Field(
        ...,
        min_length=1,
        description="Executable research brief for the runtime.",
    )
    complexity: str = Field(
        ...,
        min_length=1,
        description="Research complexity classification.",
    )
    target_sources: list[str] = Field(
        default_factory=list,
        description="Planned source targets when the research can proceed.",
    )
    subtasks: list[_ResearchScoperSubtaskOutput] = Field(
        default_factory=list,
        description="Executable research subtasks.",
    )
    budget_guidance: str | None = Field(
        default=None,
        description="Optional guidance about expected research effort or budget.",
    )

    @field_validator("target_sources", "subtasks", mode="before")
    @classmethod
    def _normalize_nullable_lists(cls, value: object) -> object:
        if value is None:
            return []
        return value

    @field_validator("research_brief", mode="before")
    @classmethod
    def _normalize_research_brief(cls, value: object) -> object:
        if isinstance(value, str):
            return value
        if isinstance(value, (dict, list)):
            return json.dumps(value, ensure_ascii=False, indent=2)
        return str(value or "")

    @model_validator(mode="after")
    def _validate_required_fields(self) -> "_ResearchScoperProceedOutput":
        if not self.target_sources:
            raise ValueError("proceed 输出必须提供 target_sources")
        if not self.subtasks:
            raise ValueError("proceed 输出必须提供 subtasks")
        return self


class _ResearchScoperOutput(BaseModel):
    """Provider 边界上的完整 scoper 输出。"""

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
        description="User-facing summary of the decision.",
    )
    questions: list[_ResearchScoperQuestionOutput] = Field(
        default_factory=list,
        description="Clarifying questions to ask when decision is clarify.",
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
        description="Planned source targets when decision is proceed.",
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

    @staticmethod
    def _json_mode_schema_prompt(
        *,
        schema: type[BaseModel],
        instructions: list[str],
        example_json: str | None = None,
    ) -> str:
        schema_json = json.dumps(
            schema.model_json_schema(),
            ensure_ascii=False,
            indent=2,
        )
        instruction_block = "\n".join(instructions)
        example_block = f"\n合法输出示例：\n{example_json}\n" if example_json else "\n"
        return (
            "你必须只返回一个 JSON 对象，不要输出 Markdown 代码块、解释、前后缀文本或额外字段。\n"
            "输出必须满足下面的 JSON Schema；即使某些字段为空，也必须按 schema 提供对应字段。\n"
            f"{instruction_block}"
            f"{example_block}"
            f"JSON Schema:\n{schema_json}"
        )

    @staticmethod
    def _build_json_mode_user_prompt(
        *,
        question: str,
        stage_prompt: str,
        schema_prompt: str,
    ) -> str:
        return (
            "请只根据下面的用户问题完成当前阶段任务，然后按要求返回 JSON。\n"
            f"用户问题：{question.strip()}\n\n"
            f"{stage_prompt}\n\n"
            f"{schema_prompt}"
        )

    def _build_scoper_messages(
        self,
        *,
        question: str,
        method: str,
        schema: type[BaseModel],
        stage_prompt: str,
        schema_instructions: list[str],
        example_json: str | None = None,
    ) -> list[SystemMessage | HumanMessage]:
        question_text = question.strip()
        if method == "json_mode":
            user_prompt = self._build_json_mode_user_prompt(
                question=question_text,
                stage_prompt=stage_prompt,
                schema_prompt=self._json_mode_schema_prompt(
                    schema=schema,
                    instructions=schema_instructions,
                    example_json=example_json,
                ),
            )
        else:
            base_prompt = self._prompts.render_with_few_shot(
                "research/scoper_user",
                question=question_text,
            )
            instruction_block = "\n".join(f"- {item}" for item in schema_instructions)
            user_prompt = (
                f"{base_prompt}\n\n"
                "当前阶段约束：\n"
                f"{stage_prompt}\n"
                f"{instruction_block}"
            )
        return [
            SystemMessage(
                content=self._prompts.render_with_few_shot("research/scoper_system")
            ),
            HumanMessage(content=user_prompt),
        ]

    def _build_decision_messages(
        self, *, question: str, method: str
    ) -> list[SystemMessage | HumanMessage]:
        return self._build_scoper_messages(
            question=question,
            method=method,
            schema=_ResearchScoperDecisionOutput,
            stage_prompt=(
                "当前阶段只做路由判断。你只能返回 decision，不能返回 summary、questions、research_brief、"
                "complexity、target_sources、subtasks、budget_guidance。"
            ),
            schema_instructions=[
                "只能返回 decision。",
                'decision 只能是 "clarify" 或 "proceed"。',
            ],
            example_json='{"decision": "proceed"}',
        )

    def _build_clarify_messages(
        self, *, question: str, method: str
    ) -> list[SystemMessage | HumanMessage]:
        return self._build_scoper_messages(
            question=question,
            method=method,
            schema=_ResearchScoperClarifyOutput,
            stage_prompt=(
                "你已经判断当前问题需要先澄清。现在只生成澄清请求，不要输出 decision、research_brief、"
                "complexity、target_sources、subtasks、budget_guidance。优先一次性收集所有会改变研究路径的关键缺口，"
                "允许把多个剩余关键维度聚合为一次提问，只要用户能够一次性作答。"
            ),
            schema_instructions=[
                "summary 要明确指出已知焦点与真正缺失的关键变量。",
                "questions 只允许 1 到 2 个问题，优先一次性收集所有会改变研究路径的关键缺口。",
                "允许把多个剩余关键维度聚合为一次提问，只要问题仍然清晰且用户可以一次性作答。",
                "不要为时间范围、受众、输出形态等轻微模糊单独追问，应改用保守假设继续规划。",
            ],
            example_json=(
                "{\n"
                '  "summary": "...",\n'
                '  "questions": [{"id": "q1", "question": "...", "why_it_matters": "..."}]\n'
                "}"
            ),
        )

    def _build_proceed_messages(
        self, *, question: str, method: str
    ) -> list[SystemMessage | HumanMessage]:
        return self._build_scoper_messages(
            question=question,
            method=method,
            schema=_ResearchScoperProceedOutput,
            stage_prompt=(
                "你已经判断当前问题可以直接开始研究。现在只生成研究计划，不要输出 decision 和 questions。"
            ),
            schema_instructions=[
                "research_brief 必须是单个字符串字段，只写研究说明正文。",
                "不能把 complexity、target_sources、subtasks、budget_guidance 写进 research_brief。",
                'complexity 只能是 "simple"、"comparative" 或 "complex"。',
            ],
            example_json=(
                "{\n"
                '  "summary": "...",\n'
                '  "research_brief": "...",\n'
                '  "complexity": "simple",\n'
                '  "target_sources": ["web"],\n'
                '  "subtasks": [{"title": "...", "description": "...", "target_sources": ["web"]}],\n'
                '  "budget_guidance": "..."\n'
                "}"
            ),
        )

    def _structured_output_method(self) -> str:
        try:
            snapshot = ModelRuntimeConfigManager.get_snapshot(settings=self._settings)
            provider = snapshot.active_provider_config().provider
        except RuntimeError:
            return _DEFAULT_SCOPER_STRUCTURED_METHOD
        if provider == ModelProvider.OLLAMA:
            return _OLLAMA_SCOPER_STRUCTURED_METHOD
        return _DEFAULT_SCOPER_STRUCTURED_METHOD

    async def _invoke_structured_payload(
        self,
        *,
        model: BaseChatModel,
        schema: type[SchemaT],
        method: str,
        messages: list[SystemMessage | HumanMessage],
        stage: str,
    ) -> SchemaT:
        structured_model = model.with_structured_output(
            schema,
            method=method,
            include_raw=True,
        )
        result = await structured_model.ainvoke(messages)
        payload, reason = coerce_structured_result_payload(
            result=result,
            schema=schema,
        )
        if payload is None:
            raise RuntimeError(
                f"Research scoper {stage} structured output 解析失败: {method}:{reason or 'unknown'}"
            )
        if isinstance(payload, schema):
            return payload
        try:
            return schema.model_validate(payload)
        except ValidationError as exc:
            raise RuntimeError(
                f"Research scoper {stage} structured output 解析失败: {method}:invalid_schema"
            ) from exc

    @staticmethod
    def _is_retryable_function_calling_schema_error(
        *, exc: RuntimeError, method: str
    ) -> bool:
        return (
            method == _DEFAULT_SCOPER_STRUCTURED_METHOD
            and "invalid_schema" in str(exc)
        )

    async def _invoke_proceed_payload(
        self,
        *,
        model: BaseChatModel,
        question: str,
        method: str,
        stage: str,
    ) -> _ResearchScoperProceedOutput:
        messages = self._build_proceed_messages(question=question, method=method)
        try:
            return await self._invoke_structured_payload(
                model=model,
                schema=_ResearchScoperProceedOutput,
                method=method,
                messages=messages,
                stage=stage,
            )
        except RuntimeError as exc:
            if not self._is_retryable_function_calling_schema_error(
                exc=exc,
                method=method,
            ):
                raise
            logger.warning(
                "Research scoper %s structured output invalid_schema; retrying once",
                stage,
                exc_info=True,
            )
            return await self._invoke_structured_payload(
                model=model,
                schema=_ResearchScoperProceedOutput,
                method=method,
                messages=messages,
                stage=stage,
            )

    async def _invoke_scoper_payload(
        self,
        *,
        model: BaseChatModel,
        question: str,
        method: str,
    ) -> _ResearchScoperOutput:
        messages = self._build_scoper_messages(
            question=question,
            method=method,
            schema=_ResearchScoperOutput,
            stage_prompt="请按完整 scoper 契约生成结构化结果。",
            schema_instructions=[
                "如果 decision=clarify，则必须提供 questions。",
                "如果 decision=proceed，则必须提供 research_brief、complexity、target_sources、subtasks。",
            ],
        )
        return await self._invoke_structured_payload(
            model=model,
            schema=_ResearchScoperOutput,
            method=method,
            messages=messages,
            stage="structured output",
        )

    async def _scope_via_staged_contract(
        self,
        *,
        model: BaseChatModel,
        question: str,
        method: str,
        allow_clarify: bool,
    ) -> ResearchClarificationRequest | ResearchPlanSnapshot:
        if not allow_clarify:
            proceed_payload = await self._invoke_proceed_payload(
                model=model,
                question=question,
                method=method,
                stage="forced proceed",
            )
            return self._build_plan_snapshot_from_payload(
                summary=proceed_payload.summary,
                research_brief=proceed_payload.research_brief,
                complexity=proceed_payload.complexity,
                target_sources=proceed_payload.target_sources,
                subtasks=proceed_payload.subtasks,
                budget_guidance=proceed_payload.budget_guidance,
            )

        decision_payload = await self._invoke_structured_payload(
            model=model,
            schema=_ResearchScoperDecisionOutput,
            method=method,
            messages=self._build_decision_messages(question=question, method=method),
            stage="decision",
        )
        if decision_payload.decision == "clarify":
            clarify_payload = await self._invoke_structured_payload(
                model=model,
                schema=_ResearchScoperClarifyOutput,
                method=method,
                messages=self._build_clarify_messages(question=question, method=method),
                stage="clarify",
            )
            return ResearchClarificationRequest(
                summary=clarify_payload.summary,
                questions=[
                    ResearchClarificationQuestion(
                        id=(item.id or f"q{index}").strip() or f"q{index}",
                        question=item.question.strip(),
                        why_it_matters=item.why_it_matters.strip(),
                    )
                    for index, item in enumerate(clarify_payload.questions, start=1)
                ],
            )

        proceed_payload = await self._invoke_proceed_payload(
            model=model,
            question=question,
            method=method,
            stage="proceed",
        )
        return self._build_plan_snapshot_from_payload(
            summary=proceed_payload.summary,
            research_brief=proceed_payload.research_brief,
            complexity=proceed_payload.complexity,
            target_sources=proceed_payload.target_sources,
            subtasks=proceed_payload.subtasks,
            budget_guidance=proceed_payload.budget_guidance,
        )

    @staticmethod
    def _build_plan_snapshot_from_payload(
        *,
        summary: str,
        research_brief: str,
        complexity: str,
        target_sources: list[str],
        subtasks: list[_ResearchScoperSubtaskOutput],
        budget_guidance: str | None,
    ) -> ResearchPlanSnapshot:
        normalized_complexity = str(complexity or "").strip().lower()
        if normalized_complexity not in {item.value for item in ResearchComplexity}:
            normalized_complexity = ResearchComplexity.COMPARATIVE.value

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
            research_brief=research_brief.strip(),
            complexity=ResearchComplexity(normalized_complexity),
            summary=summary,
            subtasks=[
                ResearchPlanSubtask(
                    title=item.title.strip(),
                    description=item.description.strip(),
                    target_sources=_normalize_target_sources(item.target_sources),
                )
                for item in subtasks
            ],
            target_sources=_normalize_target_sources(target_sources),
            budget_guidance=budget_guidance,
        )

    async def scope(
        self,
        *,
        question: str,
        allow_clarify: bool = True,
    ) -> ResearchClarificationRequest | ResearchPlanSnapshot:
        model = create_chat_model(
            settings=self._settings, use_previous_response_id=False
        )
        method = self._structured_output_method()
        if method == "json_mode":
            return await self._scope_via_staged_contract(
                model=model,
                question=question,
                method=method,
                allow_clarify=allow_clarify,
            )

        if not allow_clarify:
            return await self._scope_via_staged_contract(
                model=model,
                question=question,
                method=method,
                allow_clarify=False,
            )

        payload = await self._invoke_scoper_payload(
            model=model,
            question=question,
            method=method,
        )
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
        research_brief = payload.research_brief
        if research_brief is None:
            raise RuntimeError("Research scoper proceed 决策缺少 research_brief")
        return self._build_plan_snapshot_from_payload(
            summary=payload.summary,
            research_brief=research_brief,
            complexity=str(payload.complexity or ""),
            target_sources=payload.target_sources,
            subtasks=payload.subtasks,
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

    async def build_plan(
        self,
        request: ResearchSessionCreateRequest,
        *,
        allow_clarify: bool = True,
    ) -> ResearchPlannerResult:
        question = request.question.strip()
        try:
            scoped = await self._scoper.scope(
                question=question,
                allow_clarify=allow_clarify,
            )
        except AppError:
            raise
        except Exception as exc:
            mapped = _map_research_planner_exception(exc)
            if mapped is not None:
                raise mapped from exc
            raise
        if isinstance(scoped, ResearchClarificationRequest):
            return ResearchPlannerResult(
                plan_snapshot=None,
                clarification_request=scoped,
                next_status=ResearchSessionStatus.CLARIFYING,
            )

        return ResearchPlannerResult(
            plan_snapshot=scoped,
            clarification_request=None,
            next_status=ResearchSessionStatus.PLAN_READY,
        )

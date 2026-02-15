"""研究计划工具。

支持问题拆解和研究计划生成。
"""

from __future__ import annotations

import json
from typing import Literal

from langchain.tools import BaseTool, tool as lc_tool
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.integrations.llm_client import ChatMessage, LLMClient
from app.prompts import PromptLoader


class ResearchPlanArgs(BaseModel):
    """研究计划参数。"""

    question: str = Field(..., description="研究问题")
    context: str = Field(default="", description="背景上下文")
    available_kb_ids: list[str] = Field(
        default_factory=list, description="可用知识库 ID"
    )
    allow_external: bool = Field(default=False, description="是否允许外部搜索")
    max_subtasks: int = Field(default=5, ge=1, le=10, description="最大子任务数")


class ResearchSubtask(BaseModel):
    """研究子任务结构。"""

    model_config = ConfigDict(extra="ignore")

    id: str
    description: str
    search_queries: list[str] = Field(default_factory=list)
    target_sources: Literal["kb", "web"] = "kb"
    dependencies: list[str] = Field(default_factory=list)
    priority: int = Field(default=3, ge=1, le=5)


class ResearchPlanResult(BaseModel):
    """研究计划结构化输出。"""

    model_config = ConfigDict(extra="ignore")

    original_question: str
    complexity: Literal["simple", "moderate", "complex"] = "moderate"
    research_type: Literal[
        "factual", "analytical", "comparative", "exploratory"
    ] = "exploratory"
    subtasks: list[ResearchSubtask] = Field(default_factory=list)
    estimated_steps: int = Field(default=1, ge=1)
    suggested_approach: str
    key_assumptions: list[str] = Field(default_factory=list)
    success_criteria: list[str] = Field(default_factory=list)


PLAN_PROMPT = """你是一个研究规划专家。请分析以下研究问题，生成结构化的研究计划。

## 研究问题
{question}

## 背景上下文
{context}

## 可用资源
- 知识库: {kb_info}
- 外部搜索: {external_info}

## 要求
- 最多生成 {max_subtasks} 个子任务
- 每个子任务应该是独立可执行的
- 考虑任务之间的依赖关系

请以 JSON 格式输出研究计划，包含以下字段：
- original_question: 原始问题
- complexity: 复杂度（"simple"/"moderate"/"complex"）
- research_type: 研究类型（"factual"/"analytical"/"comparative"/"exploratory"）
- subtasks: 子任务列表，每个子任务包含：
  - id: 任务 ID（如 "task_1"）
  - description: 任务描述
  - search_queries: 建议的搜索查询列表
  - target_sources: 目标来源（"kb"/"web"）
  - dependencies: 依赖的任务 ID 列表
  - priority: 优先级（1-5，1 最高）
- estimated_steps: 预计步骤数
- suggested_approach: 建议的研究方法
- key_assumptions: 关键假设列表
- success_criteria: 成功标准列表

只输出 JSON，不要其他内容。"""


def _extract_json_object(text: str) -> dict | None:
    """从 LLM 响应中提取首个 JSON 对象。"""
    content = text.strip()
    if content.startswith("```"):
        lines = content.splitlines()
        if len(lines) >= 3:
            content = "\n".join(lines[1:-1]).strip()
    decoder = json.JSONDecoder()
    start = content.find("{")
    while start >= 0:
        try:
            payload, _ = decoder.raw_decode(content[start:])
            if isinstance(payload, dict):
                return payload
        except json.JSONDecodeError:
            pass
        start = content.find("{", start + 1)
    return None


def _build_fallback_plan(
    *, question: str, max_subtasks: int, allow_external: bool
) -> ResearchPlanResult:
    """构建保底研究计划，避免工具输出不可用。"""
    target_source: Literal["kb", "web"] = "web" if allow_external else "kb"
    subtasks: list[ResearchSubtask] = [
        ResearchSubtask(
            id="task_1",
            description="确认问题定义与关键约束，并检索可用证据",
            search_queries=[question],
            target_sources=target_source,
            dependencies=[],
            priority=1,
        )
    ]
    if max_subtasks <= 0:
        subtasks = []
    return ResearchPlanResult(
        original_question=question,
        complexity="moderate",
        research_type="exploratory",
        subtasks=subtasks,
        estimated_steps=max(len(subtasks), 1),
        suggested_approach="先建立问题边界，再逐步补证并验证结论。",
        key_assumptions=[],
        success_criteria=["形成可复核的初步结论与证据清单"],
    )


def _normalize_plan(
    plan: ResearchPlanResult,
    *,
    question: str,
    max_subtasks: int,
    allow_external: bool,
) -> ResearchPlanResult:
    """规整计划结构，确保下游执行可用。"""
    limited_subtasks = plan.subtasks[: max(1, int(max_subtasks))]
    if not limited_subtasks:
        return _build_fallback_plan(
            question=question,
            max_subtasks=max_subtasks,
            allow_external=allow_external,
        )

    resolved_ids: list[str] = []
    for idx, task in enumerate(limited_subtasks, 1):
        candidate = (task.id or "").strip() or f"task_{idx}"
        if candidate in resolved_ids:
            candidate = f"task_{idx}"
        resolved_ids.append(candidate)
    known_ids = set(resolved_ids)

    normalized_subtasks: list[ResearchSubtask] = []
    for idx, task in enumerate(limited_subtasks):
        task_id = resolved_ids[idx]
        queries = [q.strip() for q in task.search_queries if q and q.strip()]
        if not queries:
            queries = [question]
        target_sources: Literal["kb", "web"] = task.target_sources
        if target_sources == "web" and not allow_external:
            target_sources = "kb"
        dependencies = [
            dep
            for dep in task.dependencies
            if dep in known_ids and dep != task_id
        ]
        normalized_subtasks.append(
            ResearchSubtask(
                id=task_id,
                description=(task.description or "").strip() or f"执行子任务 {idx + 1}",
                search_queries=queries,
                target_sources=target_sources,
                dependencies=dependencies,
                priority=task.priority,
            )
        )

    return ResearchPlanResult(
        original_question=question,
        complexity=plan.complexity,
        research_type=plan.research_type,
        subtasks=normalized_subtasks,
        estimated_steps=max(int(plan.estimated_steps), len(normalized_subtasks), 1),
        suggested_approach=(plan.suggested_approach or "").strip() or "分步取证并交叉验证。",
        key_assumptions=[
            item.strip() for item in plan.key_assumptions if item and item.strip()
        ][:5],
        success_criteria=[
            item.strip() for item in plan.success_criteria if item and item.strip()
        ][:5],
    )


def _parse_llm_response(
    response: str, *, question: str, max_subtasks: int, allow_external: bool
) -> ResearchPlanResult:
    """解析并标准化 LLM 输出。"""
    payload = _extract_json_object(response)
    if not isinstance(payload, dict):
        return _build_fallback_plan(
            question=question,
            max_subtasks=max_subtasks,
            allow_external=allow_external,
        )
    try:
        parsed = ResearchPlanResult.model_validate(payload)
    except ValidationError:
        return _build_fallback_plan(
            question=question,
            max_subtasks=max_subtasks,
            allow_external=allow_external,
        )
    return _normalize_plan(
        parsed,
        question=question,
        max_subtasks=max_subtasks,
        allow_external=allow_external,
    )


def build_research_plan_tool(
    llm: LLMClient, prompts: PromptLoader | None = None
) -> BaseTool:
    """构建研究计划工具。"""

    async def _plan(
        question: str,
        context: str = "",
        available_kb_ids: list[str] | None = None,
        allow_external: bool = False,
        max_subtasks: int = 5,
    ) -> str:
        kb_ids = available_kb_ids or []
        kb_info = f"{len(kb_ids)} 个知识库可用" if kb_ids else "无可用知识库"
        external_info = "已启用" if allow_external else "未启用"
        bounded_subtasks = max(1, min(int(max_subtasks), 10))

        if prompts:
            prompt = prompts.render(
                "tools/research_plan",
                question=question,
                context=context or "无",
                kb_info=kb_info,
                external_info=external_info,
                max_subtasks=bounded_subtasks,
            )
        else:
            prompt = PLAN_PROMPT.format(
                question=question,
                context=context or "无",
                kb_info=kb_info,
                external_info=external_info,
                max_subtasks=bounded_subtasks,
            )

        response = (
            await llm.chat_with_metrics(
                messages=[ChatMessage(role="user", content=prompt)]
            )
        ).content
        result = _parse_llm_response(
            response,
            question=question,
            max_subtasks=bounded_subtasks,
            allow_external=allow_external,
        )
        return json.dumps(result.model_dump(mode="json"), ensure_ascii=False)

    return lc_tool(
        "research_plan",
        description="分析研究问题，生成结构化的研究计划和子任务拆解。",
        args_schema=ResearchPlanArgs,
    )(_plan)

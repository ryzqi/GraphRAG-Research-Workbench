"""研究计划工具。

支持问题拆解和研究计划生成。
"""

from __future__ import annotations

import json

from langchain_core.tools import BaseTool, StructuredTool
from pydantic import BaseModel, Field

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

只输出 JSON，不要其他内容。"""


def _parse_llm_response(response: str) -> dict:
    """解析 LLM 响应为结构化结果。"""
    response = response.strip()
    if response.startswith("```"):
        response = response.split("\n", 1)[1].rsplit("```", 1)[0]

    try:
        return json.loads(response)
    except json.JSONDecodeError:
        return {
            "original_question": "",
            "complexity": "moderate",
            "research_type": "exploratory",
            "subtasks": [],
            "estimated_steps": 1,
            "suggested_approach": "无法生成研究计划，请重新描述问题",
        }


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

        if prompts:
            prompt = prompts.render(
                "tools/research_plan",
                question=question,
                context=context or "无",
                kb_info=kb_info,
                external_info=external_info,
                max_subtasks=max_subtasks,
            )
        else:
            prompt = PLAN_PROMPT.format(
                question=question,
                context=context or "无",
                kb_info=kb_info,
                external_info=external_info,
                max_subtasks=max_subtasks,
            )

        response = await llm.chat(messages=[ChatMessage(role="user", content=prompt)])
        result = _parse_llm_response(response)
        result["original_question"] = question

        return json.dumps(result, ensure_ascii=False)

    return StructuredTool.from_function(
        name="research_plan",
        description="分析研究问题，生成结构化的研究计划和子任务拆解。",
        args_schema=ResearchPlanArgs,
        coroutine=_plan,
    )

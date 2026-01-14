"""证据对比工具。

支持多来源证据的冲突检测和对比分析。
"""

from __future__ import annotations

import json
from typing import Literal

from langchain_core.tools import BaseTool, StructuredTool
from pydantic import BaseModel, Field

from app.integrations.llm_client import ChatMessage, LLMClient
from app.prompts import PromptLoader


class EvidenceItem(BaseModel):
    """证据条目。"""

    source_id: str = Field(..., description="来源标识")
    source_type: Literal["kb", "web", "external"] = Field(..., description="来源类型")
    content: str = Field(..., description="证据内容")
    metadata: dict = Field(default_factory=dict, description="元数据")


class EvidenceCompareArgs(BaseModel):
    """证据对比参数。"""

    question: str = Field(..., description="原始问题")
    evidence_items: list[EvidenceItem] = Field(
        ..., min_length=1, description="证据列表"
    )
    comparison_mode: Literal["auto", "factual", "opinion", "temporal"] = Field(
        default="auto", description="对比模式"
    )


COMPARE_PROMPT = """你是一个证据分析专家。请分析以下证据，检测是否存在冲突或不一致。

## 原始问题
{question}

## 证据列表
{evidence_list}

## 对比模式
{comparison_mode}

请以 JSON 格式输出分析结果，包含以下字段：
- has_conflicts: 是否存在冲突（布尔值）
- confidence_level: 证据充分程度（"sufficient"/"partial"/"insufficient"）
- conflicts: 冲突列表，每个冲突包含 topic（主题）、positions（各方立场）、severity（严重程度：high/medium/low）
- consensus_points: 共识点列表
- evidence_gaps: 证据缺口列表
- recommendation: 建议（如需补充检索）

只输出 JSON，不要其他内容。"""


def _format_evidence_list(items: list[EvidenceItem]) -> str:
    parts = []
    for i, item in enumerate(items, 1):
        parts.append(
            f"[{i}] 来源: {item.source_id} ({item.source_type})\n内容: {item.content}"
        )
    return "\n\n".join(parts)


def _parse_llm_response(response: str) -> dict:
    """解析 LLM 响应为结构化结果。"""
    response = response.strip()
    if response.startswith("```"):
        response = response.split("\n", 1)[1].rsplit("```", 1)[0]

    try:
        return json.loads(response)
    except json.JSONDecodeError:
        return {
            "has_conflicts": False,
            "confidence_level": "insufficient",
            "conflicts": [],
            "consensus_points": [],
            "evidence_gaps": ["无法解析分析结果"],
            "recommendation": "请重新提交证据进行分析",
        }


def build_evidence_compare_tool(
    llm: LLMClient, prompts: PromptLoader | None = None
) -> BaseTool:
    """构建证据对比工具。"""

    async def _compare(
        question: str,
        evidence_items: list[dict],
        comparison_mode: str = "auto",
    ) -> str:
        items = [EvidenceItem(**e) for e in evidence_items]

        if len(items) < 2:
            return json.dumps(
                {
                    "has_conflicts": False,
                    "confidence_level": "partial" if items else "insufficient",
                    "conflicts": [],
                    "consensus_points": [],
                    "evidence_gaps": ["证据数量不足，无法进行对比分析"],
                    "recommendation": "建议补充更多证据来源",
                },
                ensure_ascii=False,
            )

        evidence_list = _format_evidence_list(items)

        if prompts:
            prompt = prompts.render(
                "tools/evidence_compare",
                question=question,
                evidence_list=evidence_list,
                comparison_mode=comparison_mode,
            )
        else:
            prompt = COMPARE_PROMPT.format(
                question=question,
                evidence_list=evidence_list,
                comparison_mode=comparison_mode,
            )

        response = (await llm.chat_with_metrics(messages=[ChatMessage(role="user", content=prompt)])).content
        result = _parse_llm_response(response)

        return json.dumps(result, ensure_ascii=False)

    return StructuredTool.from_function(
        name="evidence_compare",
        description="对比分析多来源证据，检测冲突和不一致，评估证据充分程度。",
        args_schema=EvidenceCompareArgs,
        coroutine=_compare,
    )

"""证据对比工具。

支持多来源证据的冲突检测和对比分析。
"""

from __future__ import annotations

import json
from typing import Literal

from langchain.tools import BaseTool, tool as lc_tool
from pydantic import BaseModel, ConfigDict, Field, ValidationError

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


class EvidenceConflict(BaseModel):
    """单条冲突结构。"""

    model_config = ConfigDict(extra="ignore")

    topic: str
    positions: list[str] = Field(default_factory=list)
    severity: Literal["high", "medium", "low"] = "medium"


class EvidenceCompareResult(BaseModel):
    """证据对比结构化结果。"""

    model_config = ConfigDict(extra="ignore")

    has_conflicts: bool
    confidence_level: Literal["sufficient", "partial", "insufficient"] = "partial"
    conflicts: list[EvidenceConflict] = Field(default_factory=list)
    consensus_points: list[str] = Field(default_factory=list)
    evidence_gaps: list[str] = Field(default_factory=list)
    recommendation: str
    next_actions: list[str] = Field(default_factory=list)


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
- next_actions: 下一步动作列表

只输出 JSON，不要其他内容。"""


def _extract_json_object(text: str) -> dict | None:
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


def _format_evidence_list(items: list[EvidenceItem]) -> str:
    parts = []
    for i, item in enumerate(items, 1):
        parts.append(
            f"[{i}] 来源: {item.source_id} ({item.source_type})\n内容: {item.content}"
        )
    return "\n\n".join(parts)


def _fallback_result(message: str) -> EvidenceCompareResult:
    return EvidenceCompareResult(
        has_conflicts=False,
        confidence_level="insufficient",
        conflicts=[],
        consensus_points=[],
        evidence_gaps=[message],
        recommendation="建议补充更多可交叉验证的证据来源。",
        next_actions=["补充至少一个独立来源并再次对比"],
    )


def _normalize_result(result: EvidenceCompareResult) -> EvidenceCompareResult:
    conflicts: list[EvidenceConflict] = []
    for conflict in result.conflicts[:5]:
        positions = [p.strip() for p in conflict.positions if p and p.strip()][:5]
        conflicts.append(
            EvidenceConflict(
                topic=(conflict.topic or "").strip() or "未命名冲突",
                positions=positions,
                severity=conflict.severity,
            )
        )
    return EvidenceCompareResult(
        has_conflicts=bool(result.has_conflicts and conflicts),
        confidence_level=result.confidence_level,
        conflicts=conflicts,
        consensus_points=[p.strip() for p in result.consensus_points if p and p.strip()][
            :8
        ],
        evidence_gaps=[p.strip() for p in result.evidence_gaps if p and p.strip()][:8],
        recommendation=(result.recommendation or "").strip() or "建议补充证据后再下结论。",
        next_actions=[p.strip() for p in result.next_actions if p and p.strip()][:8],
    )


def _parse_llm_response(response: str) -> EvidenceCompareResult:
    """解析 LLM 响应为结构化结果。"""
    payload = _extract_json_object(response)
    if not isinstance(payload, dict):
        return _fallback_result("无法解析分析结果")
    try:
        parsed = EvidenceCompareResult.model_validate(payload)
    except ValidationError:
        return _fallback_result("分析结果结构不合法")
    return _normalize_result(parsed)


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
            result = EvidenceCompareResult(
                has_conflicts=False,
                confidence_level="partial" if items else "insufficient",
                conflicts=[],
                consensus_points=[],
                evidence_gaps=["证据数量不足，无法进行对比分析"],
                recommendation="建议补充更多证据来源",
                next_actions=["补充至少 2 个来源后重新对比"],
            )
            return json.dumps(result.model_dump(mode="json"), ensure_ascii=False)

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

        response = (
            await llm.chat_with_metrics(
                messages=[ChatMessage(role="user", content=prompt)]
            )
        ).content
        result = _parse_llm_response(response)
        return json.dumps(result.model_dump(mode="json"), ensure_ascii=False)

    return lc_tool(
        "evidence_compare",
        description="对比分析多来源证据，检测冲突和不一致，评估证据充分程度。",
        args_schema=EvidenceCompareArgs,
    )(_compare)

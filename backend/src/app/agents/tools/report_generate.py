"""报告生成工具。

支持结构化研究报告生成。
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Literal

from langchain_core.tools import BaseTool, StructuredTool
from pydantic import BaseModel, Field

from app.integrations.llm_client import ChatMessage, LLMClient
from app.prompts import PromptLoader


class ReportGenerateArgs(BaseModel):
    """报告生成参数。"""

    question: str = Field(..., description="研究问题")
    findings: list[str] = Field(..., description="研究发现列表")
    evidence_summary: dict = Field(..., description="证据摘要（来自 evidence_compare）")
    citations: list[dict] = Field(default_factory=list, description="引用列表")
    report_format: Literal["standard", "brief", "detailed"] = Field(
        default="standard", description="报告格式"
    )


REPORT_PROMPT = """你是一个研究报告撰写专家。请根据以下研究发现和证据，生成结构化的研究报告。

## 研究问题
{question}

## 研究发现
{findings}

## 证据摘要
{evidence_summary}

## 引用来源
{citations}

## 报告格式要求
{format_instruction}

请生成 Markdown 格式的研究报告，包含以下章节：
1. 摘要 - 简要概述研究结论
2. 研究发现 - 详细阐述各项发现
3. 证据分析 - 分析证据的充分性和冲突点（如有）
4. 结论与建议 - 给出结论和下一步建议
5. 参考来源 - 列出所有引用

同时输出 JSON 格式的元数据，包含：
- confidence_level: 结论置信度
- evidence_count: 证据数量
- has_conflicts: 是否存在冲突
- generated_at: 生成时间

输出格式：
```json
{{
  "report_md": "Markdown 报告内容",
  "sections": [...],
  "metadata": {{...}}
}}
```

只输出 JSON，不要其他内容。"""


FORMAT_INSTRUCTIONS = {
    "brief": "简洁模式：每个章节 1-2 句话，总长度不超过 500 字",
    "standard": "标准模式：每个章节 2-3 段，总长度 800-1500 字",
    "detailed": "详细模式：每个章节充分展开，包含所有细节，总长度 2000+ 字",
}


def _format_findings(findings: list[str]) -> str:
    if not findings:
        return "无研究发现"
    return "\n".join(f"- {f}" for f in findings)


def _format_citations(citations: list[dict]) -> str:
    if not citations:
        return "无引用来源"
    parts = []
    for i, c in enumerate(citations, 1):
        source = c.get("source_id", c.get("kb_id", "未知来源"))
        excerpt = c.get("excerpt", c.get("content", ""))[:100]
        parts.append(f"[{i}] {source}: {excerpt}...")
    return "\n".join(parts)


def _parse_llm_response(response: str, question: str) -> dict:
    """解析 LLM 响应为结构化结果。"""
    response = response.strip()
    if response.startswith("```"):
        response = response.split("\n", 1)[1].rsplit("```", 1)[0]

    try:
        result = json.loads(response)
        if "metadata" not in result:
            result["metadata"] = {}
        result["metadata"]["generated_at"] = datetime.now(timezone.utc).isoformat()
        return result
    except json.JSONDecodeError:
        return {
            "report_md": f"# 研究报告\n\n## 研究问题\n{question}\n\n无法生成完整报告，请重试。",
            "sections": [{"title": "错误", "content": "报告生成失败"}],
            "metadata": {
                "confidence_level": "insufficient",
                "evidence_count": 0,
                "has_conflicts": False,
                "generated_at": datetime.now(timezone.utc).isoformat(),
            },
        }


def build_report_generate_tool(llm: LLMClient, prompts: PromptLoader | None = None) -> BaseTool:
    """构建报告生成工具。"""

    async def _generate(
        question: str,
        findings: list[str],
        evidence_summary: dict,
        citations: list[dict] | None = None,
        report_format: str = "standard",
    ) -> str:
        citations = citations or []
        findings_text = _format_findings(findings)
        citations_text = _format_citations(citations)
        evidence_text = json.dumps(evidence_summary, ensure_ascii=False, indent=2)
        format_instruction = FORMAT_INSTRUCTIONS.get(report_format, FORMAT_INSTRUCTIONS["standard"])

        if prompts:
            prompt = prompts.render(
                "tools/report_generate",
                question=question,
                findings=findings_text,
                evidence_summary=evidence_text,
                citations=citations_text,
                format_instruction=format_instruction,
            )
        else:
            prompt = REPORT_PROMPT.format(
                question=question,
                findings=findings_text,
                evidence_summary=evidence_text,
                citations=citations_text,
                format_instruction=format_instruction,
            )

        response = (await llm.chat_with_metrics(messages=[ChatMessage(role="user", content=prompt)])).content
        result = _parse_llm_response(response, question)

        return json.dumps(result, ensure_ascii=False)

    return StructuredTool.from_function(
        name="report_generate",
        description="根据研究发现和证据生成结构化研究报告。",
        args_schema=ReportGenerateArgs,
        coroutine=_generate,
    )

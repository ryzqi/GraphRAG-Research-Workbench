"""报告生成工具。

支持结构化研究报告生成。
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Literal

from langchain.tools import BaseTool, tool as lc_tool
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.integrations.llm_client import ChatMessage, LLMClient
from app.prompts import PromptLoader


class ReportGenerateArgs(BaseModel):
    """报告生成参数。"""

    question: str = Field(..., description="研究问题")
    findings: list[str] = Field(..., description="研究发现列表")
    evidence_summary: dict = Field(..., description="证据摘要")
    citations: list[dict] = Field(default_factory=list, description="引用列表")
    report_format: Literal["standard", "brief", "detailed"] = Field(
        default="standard", description="报告格式"
    )


class ReportSection(BaseModel):
    """报告章节。"""

    model_config = ConfigDict(extra="ignore")

    title: str
    content: str


class ReportMetadata(BaseModel):
    """报告元数据。"""

    model_config = ConfigDict(extra="ignore")

    confidence_level: Literal["sufficient", "partial", "insufficient"] = "partial"
    evidence_count: int = Field(default=0, ge=0)
    has_conflicts: bool = False
    generated_at: str


class ReportGenerateResult(BaseModel):
    """报告生成结构化结果。"""

    model_config = ConfigDict(extra="ignore")

    report_md: str
    sections: list[ReportSection] = Field(default_factory=list)
    metadata: ReportMetadata


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

只输出 JSON，不要其他内容。"""


FORMAT_INSTRUCTIONS = {
    "brief": "简洁模式：每个章节 1-2 句话，总长度不超过 500 字",
    "standard": "标准模式：每个章节 2-3 段，总长度 800-1500 字",
    "detailed": "详细模式：每个章节充分展开，包含所有细节，总长度 2000+ 字",
}


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


def _format_findings(findings: list[str]) -> str:
    if not findings:
        return "无研究发现"
    return "\n".join(f"- {f}" for f in findings)


def _format_citations(citations: list[dict]) -> str:
    if not citations:
        return "无引用来源"
    parts = []
    for i, citation in enumerate(citations, 1):
        source = citation.get("source_id", citation.get("kb_id", "未知来源"))
        excerpt = str(citation.get("excerpt", citation.get("content", "")))[:100]
        parts.append(f"[{i}] {source}: {excerpt}...")
    return "\n".join(parts)


def _build_fallback_result(
    *,
    question: str,
    evidence_count: int,
    has_conflicts: bool,
    confidence_level: str,
    error_message: str,
) -> ReportGenerateResult:
    generated_at = datetime.now(timezone.utc).isoformat()
    safe_confidence: Literal["sufficient", "partial", "insufficient"]
    safe_confidence = (
        confidence_level
        if confidence_level in {"sufficient", "partial", "insufficient"}
        else "insufficient"
    )
    report_md = (
        "# 研究报告\n\n"
        "## 摘要\n"
        f"{error_message}\n\n"
        "## 研究发现\n"
        "暂无可用结构化结果。\n\n"
        "## 证据分析\n"
        "建议补充证据并重试。\n\n"
        "## 结论与建议\n"
        "当前输出采用保底模板，仅供流程继续执行。\n\n"
        "## 参考来源\n"
        "暂无。"
    )
    return ReportGenerateResult(
        report_md=report_md,
        sections=[
            ReportSection(title="摘要", content=error_message),
            ReportSection(title="研究发现", content="暂无可用结构化结果。"),
            ReportSection(title="证据分析", content="建议补充证据并重试。"),
            ReportSection(title="结论与建议", content="当前输出采用保底模板。"),
            ReportSection(title="参考来源", content="暂无。"),
        ],
        metadata=ReportMetadata(
            confidence_level=safe_confidence,
            evidence_count=max(int(evidence_count), 0),
            has_conflicts=bool(has_conflicts),
            generated_at=generated_at,
        ),
    )


def _normalize_result(
    result: ReportGenerateResult,
    *,
    question: str,
    evidence_count: int,
    has_conflicts: bool,
    confidence_level: str,
) -> ReportGenerateResult:
    generated_at = datetime.now(timezone.utc).isoformat()
    normalized_sections = [
        ReportSection(
            title=(section.title or "").strip() or "未命名章节",
            content=(section.content or "").strip() or "无内容",
        )
        for section in result.sections
    ]
    if not normalized_sections:
        normalized_sections = [
            ReportSection(title="摘要", content="未生成章节内容。"),
        ]
    report_md = (result.report_md or "").strip()
    if not report_md:
        report_md = (
            "# 研究报告\n\n"
            + "\n\n".join(
                f"## {section.title}\n{section.content}" for section in normalized_sections
            )
        )
    metadata = result.metadata
    confidence = metadata.confidence_level
    if confidence not in {"sufficient", "partial", "insufficient"}:
        confidence = (
            confidence_level
            if confidence_level in {"sufficient", "partial", "insufficient"}
            else "partial"
        )
    return ReportGenerateResult(
        report_md=report_md,
        sections=normalized_sections,
        metadata=ReportMetadata(
            confidence_level=confidence,
            evidence_count=max(int(metadata.evidence_count or evidence_count), 0),
            has_conflicts=bool(metadata.has_conflicts or has_conflicts),
            generated_at=generated_at,
        ),
    )


def _parse_llm_response(
    response: str,
    *,
    question: str,
    evidence_count: int,
    has_conflicts: bool,
    confidence_level: str,
) -> ReportGenerateResult:
    payload = _extract_json_object(response)
    if not isinstance(payload, dict):
        return _build_fallback_result(
            question=question,
            evidence_count=evidence_count,
            has_conflicts=has_conflicts,
            confidence_level=confidence_level,
            error_message="无法解析报告生成结果，请重试。",
        )
    try:
        parsed = ReportGenerateResult.model_validate(payload)
    except ValidationError:
        return _build_fallback_result(
            question=question,
            evidence_count=evidence_count,
            has_conflicts=has_conflicts,
            confidence_level=confidence_level,
            error_message="报告生成结果结构不合法，已回退为保底模板。",
        )
    return _normalize_result(
        parsed,
        question=question,
        evidence_count=evidence_count,
        has_conflicts=has_conflicts,
        confidence_level=confidence_level,
    )


def build_report_generate_tool(
    llm: LLMClient, prompts: PromptLoader | None = None
) -> BaseTool:
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
        format_instruction = FORMAT_INSTRUCTIONS.get(
            report_format, FORMAT_INSTRUCTIONS["standard"]
        )
        evidence_count = len(citations)
        has_conflicts = bool(evidence_summary.get("has_conflicts"))
        confidence_level = str(evidence_summary.get("confidence_level") or "partial")

        if prompts:
            prompt = prompts.render_with_few_shot(
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

        response = (
            await llm.chat_with_metrics(
                messages=[ChatMessage(role="user", content=prompt)]
            )
        ).content
        result = _parse_llm_response(
            response,
            question=question,
            evidence_count=evidence_count,
            has_conflicts=has_conflicts,
            confidence_level=confidence_level,
        )
        return json.dumps(result.model_dump(mode="json"), ensure_ascii=False)

    return lc_tool(
        "report_generate",
        description="根据研究发现和证据生成结构化研究报告。",
        args_schema=ReportGenerateArgs,
    )(_generate)

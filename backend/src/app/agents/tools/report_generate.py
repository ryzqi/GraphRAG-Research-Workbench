"""报告生成工具。

支持结构化研究报告生成。
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Literal

from langchain.tools import BaseTool, tool as lc_tool
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.integrations.llm_client import ChatMessage, LLMClient
from app.prompts import PromptLoader, get_prompt_loader


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


def _normalize_confidence_level(
    value: str,
) -> Literal["sufficient", "partial", "insufficient"]:
    if value == "sufficient":
        return "sufficient"
    if value == "partial":
        return "partial"
    return "insufficient"


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


def _render_text(
    template_key: str, *, prompts: PromptLoader | None = None, **kwargs: Any
) -> str:
    loader = prompts or get_prompt_loader()
    return loader.render(template_key, **kwargs).strip()


def _resolve_format_instruction(
    report_format: str, *, prompts: PromptLoader | None = None
) -> str:
    key_map = {
        "brief": "research/report_generate_format_brief",
        "standard": "research/report_generate_format_standard",
        "detailed": "research/report_generate_format_detailed",
    }
    return _render_text(
        key_map.get(report_format, "research/report_generate_format_standard"),
        prompts=prompts,
    )


def _format_findings(
    findings: list[str], *, prompts: PromptLoader | None = None
) -> str:
    if not findings:
        return _render_text("research/report_generate_no_findings", prompts=prompts)
    return "\n".join(f"- {f}" for f in findings)


def _format_citations(
    citations: list[dict], *, prompts: PromptLoader | None = None
) -> str:
    if not citations:
        return _render_text("research/report_generate_no_citations", prompts=prompts)
    unknown_source = _render_text(
        "research/report_generate_unknown_source", prompts=prompts
    )
    parts = []
    for i, citation in enumerate(citations, 1):
        source = citation.get("source_id", citation.get("kb_id", unknown_source))
        excerpt = str(citation.get("excerpt", citation.get("content", "")))[:100]
        parts.append(f"[{i}] {source}: {excerpt}...")
    return "\n".join(parts)


def _parse_section_payloads(
    template_key: str, *, prompts: PromptLoader | None = None, **kwargs: Any
) -> list[ReportSection]:
    payload = json.loads(_render_text(template_key, prompts=prompts, **kwargs))
    if isinstance(payload, dict):
        payload = [payload]
    return [ReportSection.model_validate(item) for item in payload]


def _build_sections_markdown(
    sections: list[ReportSection],
    *,
    prompts: PromptLoader | None = None,
) -> str:
    sections_markdown = "\n\n".join(
        _render_text(
            "research/report_generate_section_md",
            prompts=prompts,
            title=section.title,
            content=section.content,
        )
        for section in sections
    )
    return _render_text(
        "research/report_generate_compiled_md",
        prompts=prompts,
        sections_markdown=sections_markdown,
    )


def _build_fallback_result(
    *,
    question: str,
    evidence_count: int,
    has_conflicts: bool,
    confidence_level: str,
    error_message: str,
    prompts: PromptLoader | None = None,
) -> ReportGenerateResult:
    generated_at = datetime.now(timezone.utc).isoformat()
    safe_confidence = _normalize_confidence_level(confidence_level)
    sections = _parse_section_payloads(
        "research/report_generate_fallback_sections_json",
        prompts=prompts,
        error_message=error_message,
    )
    report_md = _render_text(
        "research/report_generate_fallback_md",
        prompts=prompts,
        error_message=error_message,
    )
    return ReportGenerateResult(
        report_md=report_md,
        sections=sections,
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
    prompts: PromptLoader | None = None,
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
        normalized_sections = _parse_section_payloads(
            "research/report_generate_default_section_json",
            prompts=prompts,
        )
    report_md = (result.report_md or "").strip()
    if not report_md:
        report_md = _build_sections_markdown(normalized_sections, prompts=prompts)
    metadata = result.metadata
    confidence = metadata.confidence_level
    if confidence not in {"sufficient", "partial", "insufficient"}:
        confidence = _normalize_confidence_level(confidence_level)
    return ReportGenerateResult(
        report_md=report_md,
        sections=normalized_sections,
        metadata=ReportMetadata(
            confidence_level=_normalize_confidence_level(confidence),
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
    prompts: PromptLoader | None = None,
) -> ReportGenerateResult:
    payload = _extract_json_object(response)
    if not isinstance(payload, dict):
        return _build_fallback_result(
            question=question,
            evidence_count=evidence_count,
            has_conflicts=has_conflicts,
            confidence_level=confidence_level,
            error_message=_render_text(
                "research/report_generate_parse_error_message",
                prompts=prompts,
            ),
            prompts=prompts,
        )
    try:
        parsed = ReportGenerateResult.model_validate(payload)
    except ValidationError:
        return _build_fallback_result(
            question=question,
            evidence_count=evidence_count,
            has_conflicts=has_conflicts,
            confidence_level=confidence_level,
            error_message=_render_text(
                "research/report_generate_invalid_schema_error_message",
                prompts=prompts,
            ),
            prompts=prompts,
        )
    return _normalize_result(
        parsed,
        question=question,
        evidence_count=evidence_count,
        has_conflicts=has_conflicts,
        confidence_level=confidence_level,
        prompts=prompts,
    )


def build_report_generate_tool(
    llm: LLMClient, prompts: PromptLoader | None = None
) -> BaseTool:
    """构建报告生成工具。"""

    prompt_loader = prompts or get_prompt_loader()

    async def _generate(
        question: str,
        findings: list[str],
        evidence_summary: dict,
        citations: list[dict] | None = None,
        report_format: str = "standard",
    ) -> str:
        citations = citations or []
        findings_text = _format_findings(findings, prompts=prompt_loader)
        citations_text = _format_citations(citations, prompts=prompt_loader)
        evidence_text = json.dumps(evidence_summary, ensure_ascii=False, indent=2)
        format_instruction = _resolve_format_instruction(
            report_format,
            prompts=prompt_loader,
        )
        evidence_count = len(citations)
        has_conflicts = bool(evidence_summary.get("has_conflicts"))
        confidence_level = str(evidence_summary.get("confidence_level") or "partial")

        prompt = prompt_loader.render_with_few_shot(
            "tools/report_generate",
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
            prompts=prompt_loader,
        )
        return json.dumps(result.model_dump(mode="json"), ensure_ascii=False)

    return lc_tool(
        "report_generate",
        description="根据研究发现和证据生成结构化研究报告。",
        args_schema=ReportGenerateArgs,
    )(_generate)

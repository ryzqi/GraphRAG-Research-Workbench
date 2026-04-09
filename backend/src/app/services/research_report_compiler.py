"""Research report compiler helpers."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Literal, Mapping, Sequence

from app.prompts import PromptLoader, get_prompt_loader
from app.services.research_runtime_context import ResearchRuntimeContextSnapshot
from app.services.research_source_bundle import ResearchSourceBundle

ConfidenceLevel = Literal["sufficient", "partial", "insufficient"]


@dataclass(slots=True, frozen=True)
class ResearchCompiledSection:
    title: str
    content: str


@dataclass(slots=True, frozen=True)
class ResearchCompiledReport:
    report_md: str
    sections: list[dict[str, str]]
    metadata: dict[str, Any]


def normalize_confidence_level(value: str | None) -> ConfidenceLevel:
    if value == "sufficient":
        return "sufficient"
    if value == "partial":
        return "partial"
    return "insufficient"


def compile_report_from_sections(
    *,
    sections: Sequence[ResearchCompiledSection],
    evidence_count: int,
    has_conflicts: bool,
    confidence_level: str | None,
    report_md: str | None = None,
    prompts: PromptLoader | None = None,
) -> ResearchCompiledReport:
    normalized_sections = _normalize_sections(sections)
    resolved_report_md = (report_md or "").strip()
    if not resolved_report_md:
        resolved_report_md = _build_sections_markdown(
            normalized_sections,
            prompts=prompts,
        )

    return ResearchCompiledReport(
        report_md=resolved_report_md,
        sections=[
            {"title": section.title, "content": section.content}
            for section in normalized_sections
        ],
        metadata={
            "confidence_level": normalize_confidence_level(confidence_level),
            "evidence_count": max(int(evidence_count), 0),
            "has_conflicts": bool(has_conflicts),
            "generated_at": datetime.now(timezone.utc).isoformat(),
        },
    )


def compile_report_from_runtime_context(
    *,
    question: str,
    source_bundle: ResearchSourceBundle,
    runtime_context_snapshot: ResearchRuntimeContextSnapshot | None,
    prompts: PromptLoader | None = None,
) -> ResearchCompiledReport | None:
    del question
    if runtime_context_snapshot is None:
        return None

    report_context = dict(runtime_context_snapshot.report_context_json)
    has_material = any(
        (
            runtime_context_snapshot.claim_map_md.strip(),
            runtime_context_snapshot.evidence_ledger_md.strip(),
            runtime_context_snapshot.analysis_notes_md.strip(),
            runtime_context_snapshot.report_outline_md.strip(),
            runtime_context_snapshot.report_draft_md.strip(),
            bool(report_context),
        )
    )
    if not has_material:
        return None

    executive_summary = _resolve_executive_summary(
        report_context=report_context,
        source_bundle=source_bundle,
    )
    confidence_level = _resolve_runtime_confidence_level(
        report_context=report_context,
        source_bundle=source_bundle,
    )
    has_conflicts = bool(report_context.get("has_conflicts"))

    sections = [
        ResearchCompiledSection(
            title="核心结论",
            content=_join_blocks(
                executive_summary,
                _format_bullets("已验证发现", source_bundle.findings),
                _trim_leading_heading(runtime_context_snapshot.claim_map_md),
            ),
        ),
        ResearchCompiledSection(
            title="分主题分析",
            content=_join_blocks(
                _trim_leading_heading(runtime_context_snapshot.report_outline_md),
                _trim_leading_heading(runtime_context_snapshot.report_draft_md),
                _trim_leading_heading(runtime_context_snapshot.analysis_notes_md),
            ),
        ),
        ResearchCompiledSection(
            title="证据与反证",
            content=_join_blocks(
                _trim_leading_heading(runtime_context_snapshot.evidence_ledger_md),
                _format_citations_block(source_bundle),
            ),
        ),
        ResearchCompiledSection(
            title="结论与建议",
            content=_join_blocks(
                f"当前置信度：{_format_confidence_label(confidence_level)}。",
                _format_bullets(
                    "待解问题",
                    _normalize_string_list(report_context.get("open_questions")),
                ),
                _format_bullets("覆盖缺口", source_bundle.coverage_gaps),
            ),
        ),
        ResearchCompiledSection(
            title="参考来源",
            content=_format_citation_list(source_bundle),
        ),
    ]
    return compile_report_from_sections(
        sections=sections,
        evidence_count=len(source_bundle.citations),
        has_conflicts=has_conflicts,
        confidence_level=confidence_level,
        prompts=prompts,
    )


def _normalize_sections(
    sections: Sequence[ResearchCompiledSection],
) -> list[ResearchCompiledSection]:
    normalized = [
        ResearchCompiledSection(
            title=(section.title or "").strip() or "未命名章节",
            content=(section.content or "").strip() or "无内容",
        )
        for section in sections
    ]
    if normalized:
        return normalized
    return [ResearchCompiledSection(title="摘要", content="无内容")]


def _build_sections_markdown(
    sections: Sequence[ResearchCompiledSection],
    *,
    prompts: PromptLoader | None = None,
) -> str:
    loader = prompts or get_prompt_loader()
    sections_markdown = "\n\n".join(
        loader.render(
            "research/report_generate_section_md",
            title=section.title,
            content=section.content,
        ).strip()
        for section in sections
    )
    return loader.render(
        "research/report_generate_compiled_md",
        sections_markdown=sections_markdown,
    ).strip()


def _resolve_executive_summary(
    *,
    report_context: Mapping[str, Any],
    source_bundle: ResearchSourceBundle,
) -> str:
    summary = str(report_context.get("executive_summary") or "").strip()
    return summary or source_bundle.interim_summary


def _resolve_runtime_confidence_level(
    *,
    report_context: Mapping[str, Any],
    source_bundle: ResearchSourceBundle,
) -> ConfidenceLevel:
    configured = normalize_confidence_level(
        str(report_context.get("confidence_level") or "").strip() or None
    )
    if configured != "insufficient":
        return configured
    if report_context.get("confidence_level"):
        return configured
    if source_bundle.coverage_gaps:
        return "partial"
    return "sufficient"


def _format_confidence_label(value: ConfidenceLevel) -> str:
    mapping = {
        "sufficient": "已证实",
        "partial": "部分支持",
        "insufficient": "证据不足",
    }
    return mapping[value]


def _format_bullets(title: str, items: Sequence[str]) -> str:
    cleaned = [str(item).strip() for item in items if str(item).strip()]
    if not cleaned:
        return ""
    return "\n".join([f"{title}：", *[f"- {item}" for item in cleaned]])


def _normalize_string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _format_citations_block(source_bundle: ResearchSourceBundle) -> str:
    if not source_bundle.citations:
        return ""
    providers = "、".join(sorted(source_bundle.provider_counts)) or "暂无"
    return "\n".join(
        [
            f"引用覆盖：{len(source_bundle.citations)} 条，来源 {providers}。",
            f"当前发现数：{len(source_bundle.findings)}。",
        ]
    )


def _format_citation_list(source_bundle: ResearchSourceBundle) -> str:
    if not source_bundle.citations:
        return "暂无引用。"
    parts: list[str] = []
    for index, citation in enumerate(source_bundle.citations, start=1):
        location = str(
            citation.origin_url or citation.url or citation.pdf_url or citation.source_id
        )
        title = str(citation.title or citation.source_id)
        parts.append(f"{index:02d}. {title} | {citation.source_provider} | {location}")
    return "\n".join(parts)


def _trim_leading_heading(value: str) -> str:
    lines = [line.rstrip() for line in value.strip().splitlines()]
    if not lines:
        return ""
    if lines[0].startswith("#"):
        lines = lines[1:]
    return "\n".join(line for line in lines if line.strip()).strip()


def _join_blocks(*blocks: str) -> str:
    return "\n\n".join(block.strip() for block in blocks if block.strip())

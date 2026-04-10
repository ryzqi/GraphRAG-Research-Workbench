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
            bool(runtime_context_snapshot.task_graph_json),
            bool(runtime_context_snapshot.claim_bundles_json),
            bool(runtime_context_snapshot.section_briefs_json),
            bool(runtime_context_snapshot.live_board_json),
            bool(runtime_context_snapshot.todos_json),
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
            title="研究问题与执行路径",
            content=_join_blocks(
                f"研究问题：{question}",
                _format_task_graph_summary(runtime_context_snapshot.task_graph_json),
                _format_todos_summary(runtime_context_snapshot.todos_json),
                _format_runtime_activity_summary(runtime_context_snapshot.live_board_json),
                _format_bullets(
                    "方法提示",
                    _normalize_string_list(report_context.get("methodology_notes")),
                ),
            ),
        ),
        ResearchCompiledSection(
            title="核心结论",
            content=_join_blocks(
                executive_summary,
                _format_bullets(
                    "关键要点",
                    _normalize_string_list(report_context.get("key_takeaways")),
                ),
                _format_bullets("已验证发现", source_bundle.findings),
                _format_claim_bundle_summary(
                    runtime_context_snapshot.claim_bundles_json
                ),
                _trim_leading_heading(runtime_context_snapshot.claim_map_md),
            ),
        ),
        ResearchCompiledSection(
            title="分主题分析",
            content=_join_blocks(
                _format_section_briefs(runtime_context_snapshot.section_briefs_json),
                _format_section_status(report_context.get("section_status")),
                _trim_leading_heading(runtime_context_snapshot.report_outline_md),
                _trim_leading_heading(runtime_context_snapshot.report_draft_md),
                _trim_leading_heading(runtime_context_snapshot.analysis_notes_md),
            ),
        ),
        ResearchCompiledSection(
            title="证据、反证与验证",
            content=_join_blocks(
                _format_claim_bundle_details(
                    runtime_context_snapshot.claim_bundles_json
                ),
                _trim_leading_heading(runtime_context_snapshot.evidence_ledger_md),
                _format_bullets(
                    "验证说明",
                    _normalize_string_list(report_context.get("verification_notes")),
                ),
                _format_citations_block(source_bundle),
            ),
        ),
        ResearchCompiledSection(
            title="风险、缺口与建议",
            content=_join_blocks(
                f"当前置信度：{_format_confidence_label(confidence_level)}。",
                _format_bullets(
                    "推荐动作",
                    _normalize_string_list(report_context.get("recommended_actions")),
                ),
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


def _format_task_graph_summary(task_graph: Mapping[str, Any]) -> str:
    tasks = task_graph.get("tasks")
    if not isinstance(tasks, list) or not tasks:
        return ""
    lines = ["本轮研究按任务图执行："]
    for item in tasks:
        if not isinstance(item, Mapping):
            continue
        title = str(item.get("title") or "").strip()
        task_kind = str(item.get("task_kind") or "").strip()
        status = str(item.get("status") or "").strip()
        owner = str(item.get("owner") or "").strip()
        if not title:
            continue
        details = [token for token in [task_kind, status, owner] if token]
        lines.append(f"- {title}" + (f" ({' / '.join(details)})" if details else ""))
    return "\n".join(lines) if len(lines) > 1 else ""


def _format_section_briefs(section_briefs: Sequence[Mapping[str, Any]]) -> str:
    if not section_briefs:
        return ""
    blocks: list[str] = []
    for item in section_briefs:
        title = str(item.get("title") or "").strip()
        summary = str(item.get("summary") or "").strip()
        brief_markdown = _trim_leading_heading(str(item.get("brief_markdown") or ""))
        must_cover = _normalize_string_list(item.get("must_cover"))
        evidence_targets = _normalize_string_list(item.get("evidence_targets"))
        counterpoints = _normalize_string_list(item.get("counterpoints"))
        open_questions = _normalize_string_list(item.get("open_questions"))
        citation_indices = item.get("citation_indices")
        citation_block = (
            "引用索引：" + ", ".join(str(value) for value in citation_indices)
            if isinstance(citation_indices, list) and citation_indices
            else ""
        )
        blocks.append(
            _join_blocks(
                f"### {title}" if title else "",
                summary,
                brief_markdown,
                _format_bullets("必须覆盖", must_cover),
                _format_bullets("证据目标", evidence_targets),
                _format_bullets("反向检查", counterpoints),
                _format_bullets("待补问题", open_questions),
                citation_block,
            )
        )
    return "\n\n".join(block for block in blocks if block)


def _format_claim_bundle_summary(claim_bundles: Sequence[Mapping[str, Any]]) -> str:
    if not claim_bundles:
        return ""
    lines = ["关键 claim 收口："]
    for item in claim_bundles:
        claim = str(item.get("claim") or "").strip()
        status = str(item.get("status") or "").strip()
        if not claim:
            continue
        lines.append(f"- {claim}" + (f" ({status})" if status else ""))
    return "\n".join(lines) if len(lines) > 1 else ""


def _format_claim_bundle_details(claim_bundles: Sequence[Mapping[str, Any]]) -> str:
    if not claim_bundles:
        return ""
    blocks: list[str] = []
    for item in claim_bundles:
        claim = str(item.get("claim") or "").strip()
        status = str(item.get("status") or "").strip()
        evidence = _normalize_string_list(item.get("evidence"))
        counter_evidence = _normalize_string_list(item.get("counter_evidence"))
        limitations = _normalize_string_list(item.get("limitations"))
        open_questions = _normalize_string_list(item.get("open_questions"))
        citation_indices = item.get("citation_indices")
        citation_block = (
            "引用索引：" + ", ".join(str(value) for value in citation_indices)
            if isinstance(citation_indices, list) and citation_indices
            else ""
        )
        blocks.append(
            _join_blocks(
                f"### {claim}" if claim else "",
                f"状态：{status}" if status else "",
                _format_bullets("支撑证据", evidence),
                _format_bullets("反向证据", counter_evidence),
                _format_bullets("限制与反证", limitations),
                _format_bullets("开放问题", open_questions),
                citation_block,
            )
        )
    return "\n\n".join(block for block in blocks if block)


def _format_todos_summary(todos: Sequence[Mapping[str, Any]]) -> str:
    if not todos:
        return ""
    lines = ["待办执行："]
    for item in todos:
        content = str(item.get("content") or "").strip()
        status = str(item.get("status") or "").strip()
        if not content:
            continue
        prefix = f"[{status}] " if status else ""
        lines.append(f"- {prefix}{content}")
    return "\n".join(lines) if len(lines) > 1 else ""


def _format_runtime_activity_summary(live_board: Mapping[str, Any]) -> str:
    recent_activity = live_board.get("recent_activity")
    if not isinstance(recent_activity, list) or not recent_activity:
        return ""
    lines = ["最近活动："]
    for item in recent_activity:
        if not isinstance(item, Mapping):
            continue
        title = str(item.get("title") or "").strip()
        status = str(item.get("status") or "").strip()
        agent_label = str(item.get("agent_label") or "").strip()
        message = str(item.get("message") or "").strip()
        summary = message or title
        if not summary:
            continue
        details = [token for token in [agent_label, status] if token]
        lines.append(f"- {summary}" + (f" ({' / '.join(details)})" if details else ""))
    return "\n".join(lines) if len(lines) > 1 else ""


def _format_section_status(value: Any) -> str:
    if not isinstance(value, list) or not value:
        return ""
    lines = ["章节状态："]
    for item in value:
        if not isinstance(item, Mapping):
            continue
        title = str(item.get("title") or "").strip()
        status = str(item.get("status") or "").strip()
        owner = str(item.get("owner") or "").strip()
        if not title:
            continue
        details = [token for token in [status, owner] if token]
        lines.append(f"- {title}" + (f" ({' / '.join(details)})" if details else ""))
    return "\n".join(lines) if len(lines) > 1 else ""


def _trim_leading_heading(value: str) -> str:
    lines = [line.rstrip() for line in value.strip().splitlines()]
    if not lines:
        return ""
    if lines[0].startswith("#"):
        lines = lines[1:]
    return "\n".join(line for line in lines if line.strip()).strip()


def _join_blocks(*blocks: str) -> str:
    return "\n\n".join(block.strip() for block in blocks if block.strip())

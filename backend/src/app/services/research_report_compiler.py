"""Research report compiler helpers."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Literal, Mapping, Sequence

from app.prompts import PromptLoader, get_prompt_loader
from app.services.research_runtime_context import ResearchRuntimeContextSnapshot
from app.services.research_source_bundle import ResearchSourceBundle

ConfidenceLevel = Literal["sufficient", "partial", "insufficient"]
_SECTION_ID_HEADING_PATTERN = re.compile(
    r"^\[(?P<section_id>[^\[\]]+)\]\s*(?P<title>.*)$"
)
_OUTLINE_LIST_LINE_PATTERN = re.compile(r"^(?:[-*•]\s+|\d+(?:\.\d+)*[.)]?\s+)")
_PLACEHOLDER_TOKENS = (
    "待补",
    "待生成",
    "待完善",
    "todo",
    "tbd",
    "<待补章节标题>",
)


@dataclass(slots=True, frozen=True)
class ResearchCompiledSection:
    title: str
    content: str
    id: str = ""
    level: int = 2


@dataclass(slots=True, frozen=True)
class ResearchCompiledReport:
    report_md: str
    sections: list[dict[str, Any]]
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
            {
                "id": section.id,
                "title": section.title,
                "content": section.content,
                "level": section.level,
            }
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
            runtime_context_snapshot.claim_map_json.get("claims"),
            runtime_context_snapshot.evidence_ledger_json.get("evidences"),
            runtime_context_snapshot.section_briefs_json,
            runtime_context_snapshot.report_outline_md.strip(),
            runtime_context_snapshot.report_draft_md.strip(),
            bool(report_context),
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
    dynamic_sections = _build_dynamic_outline_sections(
        source_bundle=source_bundle,
        runtime_context_snapshot=runtime_context_snapshot,
    )
    if dynamic_sections:
        return compile_report_from_sections(
            sections=dynamic_sections,
            evidence_count=len(source_bundle.citations),
            has_conflicts=has_conflicts,
            confidence_level=confidence_level,
            prompts=prompts,
        )

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
                _render_claims_from_json(runtime_context_snapshot.claim_map_json),
            ),
        ),
        ResearchCompiledSection(
            title="分主题分析",
            content=_join_blocks(
                _format_section_briefs(runtime_context_snapshot.section_briefs_json),
                _format_section_status(report_context.get("section_status")),
                _publishable_runtime_block(runtime_context_snapshot.report_outline_md),
                _publishable_runtime_block(runtime_context_snapshot.report_draft_md),
                _publishable_runtime_block(runtime_context_snapshot.analysis_notes_md),
            ),
        ),
        ResearchCompiledSection(
            title="证据、反证与验证",
            content=_join_blocks(
                _render_evidence_from_json(
                    runtime_context_snapshot.evidence_ledger_json
                ),
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
            id=(section.id or "").strip(),
            level=max(int(section.level), 1),
        )
        for section in sections
    ]
    if not normalized:
        normalized = [ResearchCompiledSection(title="摘要", content="无内容")]
    return [
        ResearchCompiledSection(
            title=section.title,
            content=section.content,
            id=section.id or f"section-{index}",
            level=section.level,
        )
        for index, section in enumerate(normalized, start=1)
    ]


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


def _render_claims_from_json(claim_map: dict[str, Any]) -> str:
    claims = claim_map.get("claims") or []
    lines = ["## 核心主张"]
    for claim in claims:
        if not isinstance(claim, Mapping):
            continue
        claim_id = str(claim.get("claim_id") or "").strip()
        claim_text = str(claim.get("claim") or "").strip()
        status = str(claim.get("status") or "").strip()
        if not claim_id or not claim_text:
            continue
        status_text = f" _(状态：{status})_" if status else ""
        lines.append(f"- [{claim_id}] {claim_text}{status_text}")
    return "\n".join(lines) if len(lines) > 1 else ""


def _render_evidence_from_json(ledger: dict[str, Any]) -> str:
    evidences = ledger.get("evidences") or []
    lines = ["## 证据账本"]
    for evidence in evidences:
        if not isinstance(evidence, Mapping):
            continue
        evidence_id = str(evidence.get("evidence_id") or "").strip()
        if not evidence_id:
            continue
        relation = str(evidence.get("relation") or "supports").strip() or "supports"
        confidence = str(evidence.get("confidence") or "medium").strip() or "medium"
        claim_ids = [
            str(value).strip()
            for value in (evidence.get("claim_ids") or [])
            if str(value).strip()
        ]
        claim_ids_text = ",".join(claim_ids)
        lines.append(
            f"- [{evidence_id}] {relation} · 置信度 {confidence} · 关联 {claim_ids_text}"
        )
    return "\n".join(lines) if len(lines) > 1 else ""


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
        if not (
            _is_publishable_section_summary(summary)
            or _is_publishable_section_body(brief_markdown)
        ):
            continue
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


def _format_todos_summary(todos: Sequence[Mapping[str, Any]]) -> str:
    if not todos:
        return ""
    lines = ["执行记录："]
    for item in todos:
        content = str(item.get("content") or "").strip()
        if not content:
            continue
        lines.append(f"- {content}")
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
        agent_label = str(item.get("agent_label") or "").strip()
        message = str(item.get("message") or "").strip()
        summary = message or title
        if not summary:
            continue
        details = [token for token in [agent_label] if token]
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


def _build_dynamic_outline_sections(
    *,
    source_bundle: ResearchSourceBundle,
    runtime_context_snapshot: ResearchRuntimeContextSnapshot,
) -> list[ResearchCompiledSection]:
    outline_sections = _parse_markdown_h2_sections(runtime_context_snapshot.report_outline_md)
    draft_sections = _parse_markdown_h2_sections(runtime_context_snapshot.report_draft_md)
    outline_sections_by_id = _index_sections_by_id(outline_sections)
    draft_sections_by_id = _index_sections_by_id(draft_sections)
    outline_sections_by_title = (
        {}
        if outline_sections_by_id
        else _index_sections_by_title(outline_sections)
    )
    draft_sections_by_title = (
        {}
        if draft_sections_by_id
        else _index_sections_by_title(draft_sections)
    )
    brief_items = [
        item
        for item in runtime_context_snapshot.section_briefs_json
        if isinstance(item, Mapping)
        and (
            str(item.get("section_id") or "").strip()
            or str(item.get("title") or "").strip()
        )
    ]

    if not brief_items:
        return []
    sections: list[ResearchCompiledSection] = []
    all_sections_publishable = True

    for index, brief in enumerate(brief_items, start=1):
        section_id = str(brief.get("section_id") or "").strip() or f"section-{index}"
        title = str(brief.get("title") or "").strip() or f"未命名章节 {index}"
        draft_content = draft_sections_by_id.get(section_id, "")
        outline_content = outline_sections_by_id.get(section_id, "")
        if not draft_content and not draft_sections_by_id:
            draft_content = draft_sections_by_title.get(title, "")
        if not outline_content and not outline_sections_by_id:
            outline_content = outline_sections_by_title.get(title, "")
        if not _has_publishable_dynamic_material(
            draft_content=draft_content,
            outline_content=outline_content,
            brief=brief,
        ):
            all_sections_publishable = False
        sections.append(
            ResearchCompiledSection(
                id=section_id,
                title=title,
                content=_build_dynamic_section_content(
                    draft_content=draft_content,
                    outline_content=outline_content,
                    brief=brief,
                ),
            )
        )

    if not sections or not all_sections_publishable:
        return []

    if (
        source_bundle.citations
        and not any(_looks_like_reference_section(section.title) for section in sections)
    ):
        sections.append(
            ResearchCompiledSection(
                id=f"section-{len(sections) + 1}",
                title="参考来源",
                content=_format_citation_list(source_bundle),
            )
        )
    return sections


def _parse_markdown_h2_sections(value: str) -> list[dict[str, str]]:
    if not value.strip():
        return []
    sections: list[dict[str, str]] = []
    current_title = ""
    current_section_id = ""
    current_lines: list[str] = []
    for raw_line in value.splitlines():
        line = raw_line.rstrip()
        stripped = line.strip()
        if stripped.startswith("## "):
            if current_title:
                sections.append(
                    {
                        "section_id": current_section_id,
                        "title": current_title,
                        "content": "\n".join(current_lines).strip(),
                    }
                )
            current_section_id, current_title = _split_section_heading(stripped[3:].strip())
            current_lines = []
            continue
        if current_title:
            current_lines.append(line)
    if current_title:
        sections.append(
            {
                "section_id": current_section_id,
                "title": current_title,
                "content": "\n".join(current_lines).strip(),
            }
        )
    return sections


def _index_sections_by_id(
    sections: Sequence[Mapping[str, str]],
) -> dict[str, str]:
    indexed: dict[str, str] = {}
    for item in sections:
        section_id = str(item.get("section_id") or "").strip()
        content = str(item.get("content") or "")
        if not section_id or section_id in indexed:
            continue
        indexed[section_id] = content
    return indexed


def _index_sections_by_title(
    sections: Sequence[Mapping[str, str]],
) -> dict[str, str]:
    duplicate_titles = _duplicate_titles(
        [str(item.get("title") or "").strip() for item in sections]
    )
    indexed: dict[str, str] = {}
    for item in sections:
        normalized_title = str(item.get("title") or "").strip()
        content = str(item.get("content") or "")
        if (
            not normalized_title
            or normalized_title in indexed
            or normalized_title in duplicate_titles
        ):
            continue
        indexed[normalized_title] = content
    return indexed


def _duplicate_titles(titles: Sequence[str]) -> set[str]:
    seen: set[str] = set()
    duplicates: set[str] = set()
    for raw_title in titles:
        title = raw_title.strip()
        if not title:
            continue
        if title in seen:
            duplicates.add(title)
            continue
        seen.add(title)
    return duplicates


def _split_section_heading(raw_heading: str) -> tuple[str, str]:
    heading = raw_heading.strip()
    if not heading:
        return "", ""
    match = _SECTION_ID_HEADING_PATTERN.match(heading)
    if match is None:
        return "", heading
    return (
        str(match.group("section_id") or "").strip(),
        str(match.group("title") or "").strip(),
    )


def _build_dynamic_section_content(
    *,
    draft_content: str,
    outline_content: str,
    brief: Mapping[str, Any] | None,
) -> str:
    if brief is None:
        brief = {}
    description = str(brief.get("description") or "").strip()
    summary = str(brief.get("summary") or "").strip()
    writing_goal = str(brief.get("writing_goal") or "").strip()
    brief_markdown = _trim_leading_heading(str(brief.get("brief_markdown") or ""))
    must_cover = _normalize_string_list(brief.get("must_cover"))
    open_questions = _normalize_string_list(brief.get("open_questions"))
    citation_indices = brief.get("citation_indices")
    citation_block = (
        "引用索引：" + ", ".join(str(value) for value in citation_indices)
        if isinstance(citation_indices, list) and citation_indices
        else ""
    )
    return _join_blocks(
        draft_content,
        (
            outline_content
            if not draft_content and _is_publishable_section_body(outline_content)
            else ""
        ),
        summary if not draft_content else "",
        brief_markdown,
        (
            f"本节目标：{description}"
            if description and not draft_content and not summary and not brief_markdown
            else ""
        ),
        (
            f"写作说明：{writing_goal}"
            if writing_goal and not draft_content and not summary and not brief_markdown
            else ""
        ),
        (
            _format_bullets("必须覆盖", must_cover)
            if not draft_content and not summary and not brief_markdown
            else ""
        ),
        _format_bullets("待补问题", open_questions),
        citation_block,
    )


def _looks_like_reference_section(title: str) -> bool:
    normalized = title.strip()
    return any(token in normalized for token in ("参考", "引用", "来源"))


def _trim_leading_heading(value: str) -> str:
    lines = [line.rstrip() for line in value.strip().splitlines()]
    if not lines:
        return ""
    if lines[0].startswith("#"):
        lines = lines[1:]
    return "\n".join(line for line in lines if line.strip()).strip()


def _join_blocks(*blocks: str) -> str:
    return "\n\n".join(block.strip() for block in blocks if block.strip())


def _publishable_runtime_block(value: str) -> str:
    normalized = _trim_leading_heading(value)
    if not _is_publishable_section_body(normalized):
        return ""
    return normalized


def _has_publishable_dynamic_material(
    *,
    draft_content: str,
    outline_content: str,
    brief: Mapping[str, Any],
) -> bool:
    return any(
        (
            _is_publishable_section_body(draft_content),
            _is_publishable_section_body(outline_content),
            _is_publishable_section_body(str(brief.get("brief_markdown") or "")),
            _is_publishable_section_summary(str(brief.get("summary") or "")),
        )
    )


def _is_publishable_section_summary(value: str) -> bool:
    plain_text = _normalize_plain_text(value)
    if not plain_text or _contains_placeholder_token(plain_text):
        return False
    return len(plain_text) >= 18 or _contains_sentence_punctuation(plain_text)


def _is_publishable_section_body(value: str) -> bool:
    normalized = value.strip()
    if not normalized:
        return False
    plain_text = _normalize_plain_text(normalized)
    if not plain_text or _contains_placeholder_token(plain_text):
        return False
    content_lines = [line.strip() for line in normalized.splitlines() if line.strip()]
    if not content_lines:
        return False
    if all(_is_outline_like_line(line) for line in content_lines):
        return False
    if _contains_sentence_punctuation(plain_text):
        return True
    return len(plain_text) >= 32


def _normalize_plain_text(value: str) -> str:
    plain_text = re.sub(r"^#+\s*", "", value, flags=re.MULTILINE)
    plain_text = re.sub(r"^\[[^\[\]]+\]\s*", "", plain_text, flags=re.MULTILINE)
    plain_text = re.sub(r"[*_`>#-]", " ", plain_text)
    plain_text = re.sub(r"\s+", " ", plain_text)
    return plain_text.strip()


def _contains_placeholder_token(value: str) -> bool:
    lowered = value.lower()
    return any(token in value for token in _PLACEHOLDER_TOKENS[:3]) or any(
        token in lowered for token in _PLACEHOLDER_TOKENS[3:]
    )


def _contains_sentence_punctuation(value: str) -> bool:
    return any(token in value for token in ("。", "；", "！", "？", ".", ";", "!", "?"))


def _is_outline_like_line(value: str) -> bool:
    stripped = value.strip()
    if not stripped:
        return True
    if stripped.startswith("#"):
        return True
    content = stripped
    match = _OUTLINE_LIST_LINE_PATTERN.match(stripped)
    if match is not None:
        content = stripped[match.end() :].strip()
    if not content:
        return True
    plain_text = _normalize_plain_text(content)
    if not plain_text:
        return True
    if _contains_sentence_punctuation(plain_text):
        return False
    return len(plain_text) < 32

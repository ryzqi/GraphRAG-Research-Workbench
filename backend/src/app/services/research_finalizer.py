"""Research finalizer。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Sequence

from pydantic import BaseModel

from app.prompts import get_prompt_loader
from app.schemas.research import ResearchSourceTarget
from app.services.research_source_bundle import ResearchSourceBundle
from app.services.research_verification import build_verification_artifacts


@dataclass(slots=True, frozen=True)
class ResearchFinalizerResult:
    report_md: str
    report_json: dict[str, Any]


class ResearchFinalizer:
    """把 source bundle 收口为最终双产物。"""

    def __init__(self) -> None:
        self._prompts = get_prompt_loader()

    def finalize(
        self,
        *,
        question: str,
        target_sources: Sequence[ResearchSourceTarget],
        source_bundle: ResearchSourceBundle,
        response_format: type[BaseModel] | None = None,
    ) -> ResearchFinalizerResult:
        citations_payload = [
            citation.model_dump(mode="json") for citation in source_bundle.citations
        ]
        verification = build_verification_artifacts(
            findings=list(source_bundle.findings),
            citations=list(source_bundle.citations),
            coverage_gaps=list(source_bundle.coverage_gaps),
            provider_counts=dict(source_bundle.provider_counts),
        )
        report_md = self._build_report_md(
            question=question,
            source_bundle=source_bundle,
        )
        report_json_base = {
            "question": question,
            "target_sources": [item.value for item in target_sources],
            "summary": source_bundle.interim_summary,
            "findings": list(source_bundle.findings),
            "coverage_gaps": list(source_bundle.coverage_gaps),
            "provider_counts": dict(source_bundle.provider_counts),
            "citations": citations_payload,
            "report_md": report_md,
        }
        verification_payload = {
            "claim_map": verification.claim_map,
            "coverage_matrix": verification.coverage_matrix,
            "conflicts": verification.conflicts,
            "source_ledger": verification.source_ledger,
        }
        report_json = {**report_json_base, **verification_payload}
        if response_format is not None:
            validation_input = {
                field_name: report_json_base[field_name]
                for field_name in response_format.model_fields
                if field_name in report_json_base
            }
            validated_payload = response_format.model_validate(
                validation_input
            ).model_dump(mode="json")
            report_json_base = {**report_json_base, **validated_payload}
            report_json = {**report_json_base, **verification_payload}
        return ResearchFinalizerResult(
            report_md=report_md,
            report_json=report_json,
        )

    def _build_report_md(
        self,
        *,
        question: str,
        source_bundle: ResearchSourceBundle,
    ) -> str:
        findings_section = self._render_section(
            template_key="research/report_findings_section_md",
            items=[f"- {finding}" for finding in source_bundle.findings],
        )
        evidence_section = self._render_section(
            template_key="research/report_evidence_section_md",
            items=self._build_evidence_points(source_bundle),
        )
        coverage_gaps_section = self._render_section(
            template_key="research/report_coverage_gaps_section_md",
            items=[f"- {gap}" for gap in source_bundle.coverage_gaps],
        )
        references_section = self._render_section(
            template_key="research/report_references_section_md",
            items=[
                f"- {str(citation.title or citation.source_id)}: "
                f"{str(citation.origin_url or citation.url or citation.source_id)}"
                for citation in source_bundle.citations
            ],
        )

        return self._prompts.render(
            "research/report_md",
            question=question,
            interim_summary=source_bundle.interim_summary,
            findings_section=findings_section,
            evidence_section=evidence_section,
            coverage_gaps_section=coverage_gaps_section,
            references_section=references_section,
        )

    def _build_evidence_points(
        self,
        source_bundle: ResearchSourceBundle,
    ) -> list[str]:
        providers = "、".join(sorted(source_bundle.provider_counts)) or "暂无"
        points = [
            f"- 当前已汇总 {len(source_bundle.citations)} 条可追溯引用，已覆盖来源：{providers}。",
            "- 所有核心结论均应回链到具体 citation；若证据存在冲突，应在正文中保留冲突描述而不是强行合并。",
        ]
        if source_bundle.coverage_gaps:
            points.append(
                "- 当前仍存在覆盖缺口，以下结论需结合“覆盖缺口”章节一并阅读。"
            )
        return points

    def _render_section(self, *, template_key: str, items: Sequence[str]) -> str:
        if not items:
            return ""
        return self._prompts.render(
            template_key,
            items_block="\n".join(items),
        )

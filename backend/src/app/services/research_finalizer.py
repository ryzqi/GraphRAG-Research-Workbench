"""Research finalizer。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Sequence

from pydantic import BaseModel

from app.schemas.research import ResearchSourceTarget
from app.services.research_source_bundle import ResearchSourceBundle
from app.services.research_verification import build_verification_artifacts


@dataclass(slots=True, frozen=True)
class ResearchFinalizerResult:
    report_md: str
    report_json: dict[str, Any]


class ResearchFinalizer:
    """把 source bundle 收口为最终双产物。"""

    def finalize(
        self,
        *,
        question: str,
        target_sources: Sequence[ResearchSourceTarget],
        source_bundle: ResearchSourceBundle,
        response_format: type[BaseModel] | None = None,
    ) -> ResearchFinalizerResult:
        citations_payload = [
            citation.model_dump(mode="json")
            for citation in source_bundle.citations
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
            validated_payload = response_format.model_validate(validation_input).model_dump(mode="json")
            report_json_base = {**report_json_base, **validated_payload}
            report_json = {**report_json_base, **verification_payload}
        return ResearchFinalizerResult(
            report_md=report_md,
            report_json=report_json,
        )

    @staticmethod
    def _build_report_md(
        *,
        question: str,
        source_bundle: ResearchSourceBundle,
    ) -> str:
        lines = [
            "# Research Report",
            "",
            "## Question",
            question,
            "",
            "## Interim Summary",
            source_bundle.interim_summary,
        ]
        if source_bundle.findings:
            lines.extend(["", "## Findings"])
            lines.extend(f"- {finding}" for finding in source_bundle.findings)
        if source_bundle.coverage_gaps:
            lines.extend(["", "## Coverage Gaps"])
            lines.extend(f"- {gap}" for gap in source_bundle.coverage_gaps)
        if source_bundle.citations:
            lines.extend(["", "## References"])
            for citation in source_bundle.citations:
                url = str(citation.origin_url or citation.url or citation.source_id)
                title = str(citation.title or citation.source_id)
                lines.append(f"- {title}: {url}")
        return "\n".join(lines)

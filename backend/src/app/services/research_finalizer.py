"""Research finalizer。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Sequence

from pydantic import BaseModel

from app.prompts import get_prompt_loader
from app.schemas.research import ResearchSourceTarget
from app.schemas.research_workspace import ResearchClaimMap, ResearchEvidenceLedger
from app.services.research_report_compiler import compile_report_from_runtime_context
from app.services.research_runtime_context import ResearchRuntimeContextSnapshot
from app.services.research_source_bundle import ResearchSourceBundle
from app.services.research_verification import (
    AlignmentJudgeProtocol,
    build_verification_artifacts_async,
)


@dataclass(slots=True, frozen=True)
class ResearchFinalizerResult:
    report_md: str
    report_json: dict[str, Any]


class ResearchFinalizer:
    """把 source bundle 收口为最终双产物。"""

    def __init__(self, *, judge: AlignmentJudgeProtocol | None = None) -> None:
        self._prompts = get_prompt_loader()
        self._judge = judge

    async def finalize_async(
        self,
        *,
        question: str,
        target_sources: Sequence[ResearchSourceTarget],
        source_bundle: ResearchSourceBundle,
        runtime_context_snapshot: ResearchRuntimeContextSnapshot | None = None,
        response_format: type[BaseModel] | None = None,
    ) -> ResearchFinalizerResult:
        if self._judge is None:
            raise RuntimeError("ResearchFinalizer 未配置 alignment judge")
        citations_payload = [
            citation.model_dump(mode="json") for citation in source_bundle.citations
        ]
        verification = await build_verification_artifacts_async(
            claims=self._build_claim_map(
                runtime_context_snapshot=runtime_context_snapshot
            ).claims,
            evidences=self._build_evidence_ledger(
                runtime_context_snapshot=runtime_context_snapshot
            ).evidences,
            citations=list(source_bundle.citations),
            coverage_gaps=list(source_bundle.coverage_gaps),
            provider_counts=dict(source_bundle.provider_counts),
            judge=self._judge,
        )
        compiled_report = compile_report_from_runtime_context(
            question=question,
            source_bundle=source_bundle,
            runtime_context_snapshot=runtime_context_snapshot,
            prompts=self._prompts,
        )
        report_md = (
            compiled_report.report_md
            if compiled_report is not None
            else self._build_report_md(
                question=question,
                source_bundle=source_bundle,
            )
        )
        report_summary = self._resolve_report_summary(
            source_bundle=source_bundle,
            runtime_context_snapshot=runtime_context_snapshot,
        )
        report_json_base = {
            "question": question,
            "target_sources": [item.value for item in target_sources],
            "summary": report_summary,
            "findings": list(source_bundle.findings),
            "coverage_gaps": list(source_bundle.coverage_gaps),
            "provider_counts": dict(source_bundle.provider_counts),
            "citations": citations_payload,
            "sections": compiled_report.sections if compiled_report is not None else [],
            "metadata": compiled_report.metadata if compiled_report is not None else {},
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

    @staticmethod
    def _resolve_report_summary(
        *,
        source_bundle: ResearchSourceBundle,
        runtime_context_snapshot: ResearchRuntimeContextSnapshot | None,
    ) -> str:
        if runtime_context_snapshot is not None:
            summary = str(
                runtime_context_snapshot.report_context_json.get("executive_summary")
                or ""
            ).strip()
            if summary:
                return summary
        return source_bundle.interim_summary

    @staticmethod
    def _build_claim_map(
        *,
        runtime_context_snapshot: ResearchRuntimeContextSnapshot | None,
    ) -> ResearchClaimMap:
        payload = (
            runtime_context_snapshot.claim_map_json
            if runtime_context_snapshot is not None
            else {}
        )
        return ResearchClaimMap.model_validate(
            payload
            or {
                "claims": [],
                "generated_at": datetime.now(timezone.utc).isoformat(),
            }
        )

    @staticmethod
    def _build_evidence_ledger(
        *,
        runtime_context_snapshot: ResearchRuntimeContextSnapshot | None,
    ) -> ResearchEvidenceLedger:
        payload = (
            runtime_context_snapshot.evidence_ledger_json
            if runtime_context_snapshot is not None
            else {}
        )
        return ResearchEvidenceLedger.model_validate(
            payload
            or {
                "evidences": [],
                "generated_at": datetime.now(timezone.utc).isoformat(),
            }
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

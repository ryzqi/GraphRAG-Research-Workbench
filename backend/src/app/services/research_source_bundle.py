"""Research source bundle 收口与去重。"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import json
from typing import Any, Literal, Sequence
from urllib.parse import urlparse

from langchain_core.messages import HumanMessage
from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.config.policy_loader import load_research_policy
from app.config.policy_provider import PolicyProvider
from app.prompts import get_prompt_loader
from app.schemas.research import (
    ResearchCanonicalCitation,
    ResearchPlanSnapshot,
    ResearchSourceTarget,
    ResearchSourceType,
)
from app.services.query_rewrite_structured import coerce_structured_result_payload


ResearchSourceQualityDecisionLiteral = Literal["keep", "drop", "borderline"]


@dataclass(slots=True, frozen=True)
class ResearchSourceBundle:
    target_sources: tuple[ResearchSourceTarget, ...]
    citations: list[ResearchCanonicalCitation]
    findings: list[str]
    interim_summary: str
    coverage_gaps: list[str]
    provider_counts: dict[str, int]


@dataclass(slots=True, frozen=True)
class ResearchSourceQualityContext:
    question: str
    plan_snapshot: ResearchPlanSnapshot


class ResearchSourceQualityJudgeDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    citation_index: int = Field(ge=0)
    decision: ResearchSourceQualityDecisionLiteral
    relevance_to_question: Literal["high", "medium", "low", "none"]
    support_utility: Literal["direct", "contextual", "weak", "none"]
    source_trust_signal: Literal["high", "medium", "low", "unknown"]
    reason: str = Field(min_length=1)


class _ResearchSourceQualityJudgeOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decisions: list[ResearchSourceQualityJudgeDecision] = Field(min_length=1)

    @model_validator(mode="after")
    def _validate_unique_indices(self) -> "_ResearchSourceQualityJudgeOutput":
        citation_indices = [item.citation_index for item in self.decisions]
        if len(set(citation_indices)) != len(citation_indices):
            raise ValueError("citation_index 不能重复")
        return self


@dataclass(slots=True, frozen=True)
class ResearchSourceQualityJudgeResult:
    citations: list[ResearchCanonicalCitation]
    decisions: tuple[ResearchSourceQualityJudgeDecision, ...]
    total_candidates: int
    kept_count: int
    dropped_count: int
    borderline_count: int
    error_fallback_used: bool = False


class ResearchSourceQualityJudge:
    """基于模型的 citation 质量裁决器，仅保留极小硬安全底线。"""

    def __init__(
        self,
        *,
        model: Any | None = None,
        structured_method: str = "function_calling",
        policy_provider: PolicyProvider | None = None,
    ) -> None:
        self._policy = load_research_policy(provider=policy_provider).source_quality
        self._model = model
        self._structured_method = structured_method
        self._prompts = get_prompt_loader()

    async def filter_citations(
        self,
        citations: Sequence[ResearchCanonicalCitation],
        *,
        context: ResearchSourceQualityContext,
    ) -> ResearchSourceQualityJudgeResult:
        normalized_citations = list(citations)
        decisions: list[ResearchSourceQualityJudgeDecision] = []
        kept: list[ResearchCanonicalCitation] = []
        judge_candidates: list[tuple[int, ResearchCanonicalCitation]] = []
        dropped_count = 0
        borderline_count = 0
        error_fallback_used = False

        for index, citation in enumerate(normalized_citations):
            if citation.source_provider == "workspace":
                kept.append(citation)
                decisions.append(
                    self._build_decision(
                        citation_index=index,
                        decision="keep",
                        relevance_to_question="medium",
                        support_utility="contextual",
                        source_trust_signal="high",
                        reason="workspace_source",
                    )
                )
                continue
            if (
                citation.source_type == ResearchSourceType.WEB
                and self._is_hard_blocked_web_host(citation)
            ):
                dropped_count += 1
                decisions.append(
                    self._build_decision(
                        citation_index=index,
                        decision="drop",
                        relevance_to_question="low",
                        support_utility="none",
                        source_trust_signal="low",
                        reason="hard_blocked_domain",
                    )
                )
                continue
            judge_candidates.append((index, citation))

        if not judge_candidates:
            return self._build_result(
                citations=kept,
                decisions=decisions,
                total_candidates=len(normalized_citations),
                dropped_count=dropped_count,
                borderline_count=borderline_count,
                error_fallback_used=error_fallback_used,
            )

        if not self._policy.judge_enabled or self._model is None:
            for index, citation in judge_candidates:
                kept.append(citation)
                decisions.append(
                    self._build_decision(
                        citation_index=index,
                        decision="keep",
                        relevance_to_question="medium",
                        support_utility="contextual",
                        source_trust_signal="unknown",
                        reason="judge_disabled",
                    )
                )
            return self._build_result(
                citations=kept,
                decisions=decisions,
                total_candidates=len(normalized_citations),
                dropped_count=dropped_count,
                borderline_count=borderline_count,
                error_fallback_used=error_fallback_used,
            )

        for batch in self._batched(judge_candidates, self._policy.judge_batch_size):
            batch_output, error_reason = await self._judge_batch(batch=batch, context=context)
            if batch_output is None:
                fallback_decision = (
                    "keep"
                    if self._policy.fallback_mode == "keep_on_judge_error"
                    else "drop"
                )
                if error_reason is not None:
                    error_fallback_used = True
                for index, citation in batch:
                    if fallback_decision == "keep":
                        kept.append(citation)
                    else:
                        dropped_count += 1
                    decisions.append(
                        self._build_decision(
                            citation_index=index,
                            decision=fallback_decision,
                            relevance_to_question="medium",
                            support_utility="contextual",
                            source_trust_signal="unknown",
                            reason=error_reason or "judge_error_fallback",
                        )
                    )
                continue

            decision_by_index = {
                item.citation_index: item for item in batch_output.decisions
            }
            expected_indices = {index for index, _citation in batch}
            if set(decision_by_index) != expected_indices:
                error_fallback_used = True
                fallback_decision = (
                    "keep"
                    if self._policy.fallback_mode == "keep_on_judge_error"
                    else "drop"
                )
                for index, citation in batch:
                    if fallback_decision == "keep":
                        kept.append(citation)
                    else:
                        dropped_count += 1
                    decisions.append(
                        self._build_decision(
                            citation_index=index,
                            decision=fallback_decision,
                            relevance_to_question="medium",
                            support_utility="contextual",
                            source_trust_signal="unknown",
                            reason="invalid_schema",
                        )
                    )
                continue

            for index, citation in batch:
                decision = decision_by_index[index]
                if decision.decision == "drop":
                    dropped_count += 1
                elif decision.decision == "borderline":
                    borderline_count += 1
                    if self._policy.keep_borderline_results:
                        kept.append(citation)
                    else:
                        dropped_count += 1
                else:
                    kept.append(citation)
                decisions.append(decision)

        return self._build_result(
            citations=kept,
            decisions=decisions,
            total_candidates=len(normalized_citations),
            dropped_count=dropped_count,
            borderline_count=borderline_count,
            error_fallback_used=error_fallback_used,
        )

    async def _judge_batch(
        self,
        *,
        batch: Sequence[tuple[int, ResearchCanonicalCitation]],
        context: ResearchSourceQualityContext,
    ) -> tuple[_ResearchSourceQualityJudgeOutput | None, str | None]:
        assert self._model is not None
        structured_model = self._model.with_structured_output(
            _ResearchSourceQualityJudgeOutput,
            method=self._structured_method,
            include_raw=True,
        )
        prompt = self._prompts.render(
            "research/source_quality_judge",
            question=context.question,
            research_brief=context.plan_snapshot.research_brief,
            summary=context.plan_snapshot.summary,
            target_sources=json.dumps(
                [item.value for item in context.plan_snapshot.target_sources],
                ensure_ascii=False,
            ),
            subtasks_json=json.dumps(
                [
                    item.model_dump(mode="json")
                    for item in context.plan_snapshot.subtasks
                ],
                ensure_ascii=False,
                default=str,
            ),
            citations_json=json.dumps(
                [
                    {
                        "citation_index": index,
                        **citation.model_dump(mode="json"),
                    }
                    for index, citation in batch
                ],
                ensure_ascii=False,
                default=str,
            ),
        )
        try:
            result = await structured_model.ainvoke([HumanMessage(content=prompt)])
        except Exception as exc:
            return None, self._classify_structured_error(exc)
        payload, reason = coerce_structured_result_payload(
            result=result,
            schema=_ResearchSourceQualityJudgeOutput,
        )
        if payload is None:
            return None, reason
        if isinstance(payload, _ResearchSourceQualityJudgeOutput):
            return payload, None
        return _ResearchSourceQualityJudgeOutput.model_validate(payload), None

    def _is_hard_blocked_web_host(self, citation: ResearchCanonicalCitation) -> bool:
        host = self._citation_host(citation)
        if not host:
            return False
        return any(
            host == domain or host.endswith(f".{domain}")
            for domain in self._policy.hard_blocked_domain_suffixes
        )

    @staticmethod
    def _citation_host(citation: ResearchCanonicalCitation) -> str:
        raw_url = str(citation.origin_url or citation.url or "").strip()
        if not raw_url:
            return ""
        return (urlparse(raw_url).hostname or "").lower()

    @staticmethod
    def _batched(
        items: Sequence[tuple[int, ResearchCanonicalCitation]],
        batch_size: int,
    ) -> list[list[tuple[int, ResearchCanonicalCitation]]]:
        return [
            list(items[index : index + batch_size])
            for index in range(0, len(items), batch_size)
        ]

    @staticmethod
    def _classify_structured_error(exc: Exception) -> str:
        name = exc.__class__.__name__
        if name in {
            "StructuredOutputValidationError",
            "ValidationError",
            "OutputParserException",
        }:
            return "invalid_schema"
        if name == "MultipleStructuredOutputsError":
            return "multiple_structured_outputs"
        return "error"

    @staticmethod
    def _build_decision(
        *,
        citation_index: int,
        decision: ResearchSourceQualityDecisionLiteral,
        relevance_to_question: Literal["high", "medium", "low", "none"],
        support_utility: Literal["direct", "contextual", "weak", "none"],
        source_trust_signal: Literal["high", "medium", "low", "unknown"],
        reason: str,
    ) -> ResearchSourceQualityJudgeDecision:
        return ResearchSourceQualityJudgeDecision(
            citation_index=citation_index,
            decision=decision,
            relevance_to_question=relevance_to_question,
            support_utility=support_utility,
            source_trust_signal=source_trust_signal,
            reason=reason,
        )

    @staticmethod
    def _build_result(
        *,
        citations: list[ResearchCanonicalCitation],
        decisions: list[ResearchSourceQualityJudgeDecision],
        total_candidates: int,
        dropped_count: int,
        borderline_count: int,
        error_fallback_used: bool,
    ) -> ResearchSourceQualityJudgeResult:
        kept_count = len(citations)
        decisions.sort(key=lambda item: item.citation_index)
        return ResearchSourceQualityJudgeResult(
            citations=citations,
            decisions=tuple(decisions),
            total_candidates=total_candidates,
            kept_count=kept_count,
            dropped_count=dropped_count,
            borderline_count=borderline_count,
            error_fallback_used=error_fallback_used,
        )


class ResearchSourceBundleBuilder:
    """把多 provider 证据收口成可恢复、可 finalizer 消费的 source bundle。"""

    def build(
        self,
        *,
        target_sources: Sequence[ResearchSourceTarget],
        citations: Sequence[ResearchCanonicalCitation],
        findings: Sequence[str],
        required_web_providers: Sequence[str] = (),
    ) -> ResearchSourceBundle:
        normalized_required_web_providers = tuple(
            dict.fromkeys(
                str(provider).strip()
                for provider in required_web_providers
                if str(provider).strip()
            )
        )
        normalized_citations = [
            self._normalize_citation(citation) for citation in citations
        ]
        deduped = self._dedupe_citations(normalized_citations)
        provider_counts = Counter(
            citation.source_provider for citation in normalized_citations
        )
        coverage_gaps = [
            f"缺少来源证据：{provider}"
            for provider in normalized_required_web_providers
            if provider not in provider_counts
        ]
        interim_summary = (
            f"已汇总 {len(deduped)} 条去重证据，"
            f"已覆盖来源：{'、'.join(sorted(provider_counts)) or '暂无'}。"
        )
        return ResearchSourceBundle(
            target_sources=tuple(target_sources),
            citations=deduped,
            findings=[item.strip() for item in findings if str(item).strip()],
            interim_summary=interim_summary,
            coverage_gaps=coverage_gaps,
            provider_counts=dict(provider_counts),
        )

    @staticmethod
    def _dedupe_citations(
        citations: Sequence[ResearchCanonicalCitation],
    ) -> list[ResearchCanonicalCitation]:
        deduped: list[ResearchCanonicalCitation] = []
        seen_keys: set[tuple[str, str]] = set()
        for citation in citations:
            key = ResearchSourceBundleBuilder._dedupe_key(citation)
            if key in seen_keys:
                continue
            seen_keys.add(key)
            deduped.append(citation)
        return deduped

    @staticmethod
    def _normalize_citation(
        citation: ResearchCanonicalCitation,
    ) -> ResearchCanonicalCitation:
        if citation.source_type == ResearchSourceType.WEB and citation.origin_url:
            return citation.model_copy(update={"url": citation.origin_url})
        return citation

    @staticmethod
    def _dedupe_key(citation: ResearchCanonicalCitation) -> tuple[str, str]:
        if citation.source_type == ResearchSourceType.WEB:
            return (
                citation.source_type.value,
                str(citation.origin_url or citation.url or citation.source_id),
            )
        if citation.source_type == ResearchSourceType.PAPER:
            return (
                citation.source_type.value,
                str(citation.arxiv_id or citation.source_id),
            )
        return (citation.source_type.value, str(citation.source_id))

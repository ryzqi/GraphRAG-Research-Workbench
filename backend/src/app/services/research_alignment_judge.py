"""Deep Research claim↔evidence 对齐裁决。"""

from __future__ import annotations

import json
from collections.abc import Iterable, Sequence
from typing import Any, Literal

from langchain_core.messages import HumanMessage
from pydantic import BaseModel, ConfigDict, Field

from app.prompts import get_prompt_loader
from app.schemas.research import ResearchCanonicalCitation
from app.schemas.research_workspace import (
    ResearchClaimEntry,
    ResearchEvidenceEntry,
)
from app.services.query_rewrite_service import coerce_structured_result_payload


class ClaimAlignmentVerdict(BaseModel):
    model_config = ConfigDict(extra="forbid")

    claim_id: str = Field(min_length=1)
    verdict: Literal["supported", "contested", "insufficient"]
    supporting_evidence_ids: list[str] = Field(default_factory=list)
    conflicting_evidence_ids: list[str] = Field(default_factory=list)
    missing_aspects: list[str] = Field(default_factory=list)
    reason: str = Field(min_length=1)


class ClaimAlignmentJudgeOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    results: list[ClaimAlignmentVerdict] = Field(min_length=1)


_DEFAULT_BATCH_SIZE = 4


class ResearchAlignmentJudge:
    def __init__(
        self,
        *,
        model: Any,
        structured_method: str = "function_calling",
        batch_size: int = _DEFAULT_BATCH_SIZE,
    ) -> None:
        self._model = model
        self._structured_method = structured_method
        self._batch_size = batch_size
        self._prompts = get_prompt_loader()

    @staticmethod
    def split_into_batches(
        items: Sequence[Any], *, batch_size: int
    ) -> Iterable[list[Any]]:
        for i in range(0, len(items), batch_size):
            yield list(items[i : i + batch_size])

    async def judge_batch(
        self,
        *,
        claims: Sequence[ResearchClaimEntry],
        evidences: Sequence[ResearchEvidenceEntry],
        citations: Sequence[ResearchCanonicalCitation],
    ) -> ClaimAlignmentJudgeOutput:
        if self._model is None:
            raise RuntimeError("ResearchAlignmentJudge: model 未配置")
        structured = self._model.with_structured_output(
            ClaimAlignmentJudgeOutput,
            method=self._structured_method,
            include_raw=True,
        )
        prompt = self._prompts.render(
            "research/alignment_judge",
            claims_json=json.dumps(
                [claim.model_dump(mode="json") for claim in claims],
                ensure_ascii=False,
            ),
            evidences_json=json.dumps(
                [evidence.model_dump(mode="json") for evidence in evidences],
                ensure_ascii=False,
            ),
            citations_json=json.dumps(
                [citation.model_dump(mode="json") for citation in citations],
                ensure_ascii=False,
                default=str,
            ),
        )
        result = await structured.ainvoke([HumanMessage(content=prompt)])
        payload, reason = coerce_structured_result_payload(
            result=result, schema=ClaimAlignmentJudgeOutput
        )
        if payload is None:
            raise RuntimeError(f"alignment judge 解析失败: {reason or 'unknown'}")
        if isinstance(payload, ClaimAlignmentJudgeOutput):
            return payload
        return ClaimAlignmentJudgeOutput.model_validate(payload)

    async def judge_all(
        self,
        *,
        claims: Sequence[ResearchClaimEntry],
        evidences: Sequence[ResearchEvidenceEntry],
        citations: Sequence[ResearchCanonicalCitation],
    ) -> list[ClaimAlignmentVerdict]:
        all_results: list[ClaimAlignmentVerdict] = []
        for batch in self.split_into_batches(claims, batch_size=self._batch_size):
            batch_claim_ids = {claim.claim_id for claim in batch}
            batch_output = await self.judge_batch(
                claims=batch,
                evidences=[
                    evidence
                    for evidence in evidences
                    if any(
                        claim_id in batch_claim_ids for claim_id in evidence.claim_ids
                    )
                ],
                citations=citations,
            )
            all_results.extend(batch_output.results)
        return all_results

"""Deep Research 金样 session 数据（不调外网）。"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True, frozen=True)
class GoldenSessionFixture:
    session_id: str
    question: str
    expected_claim_id: str
    expected_citation_excerpt_keyword: str


GOLDEN_G_01 = GoldenSessionFixture(
    session_id="g01-00000000-0000-0000-0000-000000000001",
    question="Claude 3.5 Sonnet 2024 年 10 月更新的 HumanEval 得分是多少？",
    expected_claim_id="claim-01",
    expected_citation_excerpt_keyword="92",
)

GOLDEN_G_04 = GoldenSessionFixture(
    session_id="g04-00000000-0000-0000-0000-000000000004",
    question="'2030 年量子芯片已取代 GPU' 这一说法是否属实？",
    expected_claim_id="claim-01",
    expected_citation_excerpt_keyword="speculative",
)

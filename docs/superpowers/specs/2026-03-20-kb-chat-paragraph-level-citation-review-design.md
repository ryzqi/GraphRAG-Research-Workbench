# KB Chat Paragraph-Level Citation Review Redesign Design

- Date: 2026-03-20
- Status: Approved for planning
- Scope: KB Chat answer review and answer rendering only; no changes to general chat

## 1. Summary

This design replaces the current unit-level citation coverage policy with a paragraph-level citation and provenance model.

The new model keeps citations visible to end users, but changes the display contract from per-sentence or near-sentence markers to paragraph-end aggregate markers such as `[S1][S3]`.

Internally, the system no longer treats citation review as a string scan over punctuation-delimited units. Instead, draft generation produces structured answer paragraphs with claim-level grounding metadata, while the user-visible answer remains rendered Markdown/plain text.

The new runtime shape inside the answer subgraph becomes:

`draft_generate_structured -> answer_review_dispatch -> [answer_review_citation / answer_review] -> answer_review_fuse -> [answer_repair | answer_commit]`

Within this shape:

- paragraph-level visible citations replace per-unit coverage checks
- paragraph review focuses on paragraph provenance and main-claim support
- weakly supported auxiliary claims do not block release
- explicitly unsupported auxiliary claims are repaired by deletion, not by forcing per-sentence citation insertion
- backward compatibility is not preserved; the repository keeps only the latest implementation

## 2. User-approved decisions

The following behavioral choices are explicitly approved:

1. Visible citations must remain in the user answer.
2. Citation display moves to paragraph-level aggregate markers at paragraph end.
3. The system no longer requires every sentence or every unit to carry its own citation marker.
4. For paragraphs with multiple supporting sources, the paragraph may end with an aggregate citation set such as `[S1][S3]`.
5. A paragraph may pass when its main idea is supported, even if some auxiliary claims are only weakly supported.
6. If a paragraph contains an explicitly unsupported auxiliary claim, repair should delete the unsupported clause and keep the rest of the paragraph when safe.
7. Destructive refactoring is allowed.
8. Backward compatibility is not required; the repository should keep only the latest implementation.
9. The redesign should favor simpler, cleaner code over dual-path migration scaffolding.

## 3. Goals

1. Replace unit-level citation coverage review with paragraph-level provenance review.
2. Reduce citation noise in user-visible answers while preserving explicit source visibility.
3. Preserve internal grounding explainability through structured claim metadata.
4. Make unsupported auxiliary content removable without forcing full-paragraph rejection.
5. Simplify the answer review code by removing the old unit-based citation pipeline.
6. Keep changes isolated to KB Chat answer generation, review, repair, and rendering contracts.

## 4. Non-goals

1. Do not redesign Milvus retrieval, rerank internals, or storage layout.
2. Do not redesign general chat.
3. Do not introduce feature flags, compatibility shims, or long-lived migration branches.
4. Do not preserve the old unit-level citation coverage API.
5. Do not redesign frontend interaction patterns beyond what is required to render paragraph-end aggregate citations.
6. Do not apply paragraph-level citation aggregation to Markdown table data rows in this phase unless later explicitly approved.

## 5. Current repository problems

Based on the current repository:

- `review_citation_coverage(...)` in `backend/src/app/services/evidence_guardrails.py` splits answers by punctuation and newline, then treats each resulting unit as citation-bearing or uncovered.
- Markdown heading, table header, and table separator lines are special-cased, but ordinary summary bullets and paragraph sentences are still judged at unit granularity.
- `answer_review_citation` in `backend/src/app/agents/kb_chat_agentic/answer_subgraph.py` relies on the uncovered-unit list and the `kb_chat/citation_review` prompt to decide whether missing citations are critical.
- `answer_repair` is currently biased toward adding nearby citations and preserving citation coverage score, rather than deleting explicitly unsupported auxiliary content.
- The current model conflates two separate concerns:
  1. whether a visible citation marker exists near a unit of text
  2. whether a paragraph is actually grounded in the allowed evidence set

This creates noisy answers and false friction for summary paragraphs that are grounded overall but not annotated sentence by sentence.

## 6. Research-grounded design direction

The redesign follows common industrial patterns:

1. keep user-visible citations, but bind them to larger answer spans rather than every sentence
2. separate internal grounding metadata from external rendering form
3. judge provenance at a meaningful answer span level
4. allow unsupported details to be removed surgically instead of rewriting everything
5. treat rendering as a projection of structured truth, not the truth itself

## 7. Proposed runtime architecture

### 7.1 Top-level answer subgraph path

Target answer path:

`draft_generate_structured -> answer_review_dispatch -> [answer_review_citation / answer_review] -> answer_review_fuse -> [answer_repair | answer_commit]`

This means:

- `draft_generate` is upgraded in-place to produce structured paragraphs plus rendered draft text
- there is no standalone `answer_grounding_map` node in the latest-only implementation
- `answer_review_dispatch`, `answer_review_fuse`, `answer_repair`, and `answer_commit` remain the main control points

### 7.2 Node responsibilities

#### `draft_generate_structured`

Responsibilities:

- generate structured answer paragraphs
- assign paragraph-level citation sets
- identify paragraph claims and their roles
- render the user-visible draft answer with paragraph-end aggregate citations

#### `answer_review_citation`

Responsibilities:

- validate that each grounding-required paragraph has a non-empty citation set
- validate that citation ids are within the allowed evidence set
- validate that the paragraph main claim is aligned with the paragraph citation set
- no longer inspect punctuation-delimited uncovered units

#### `answer_review`

Responsibilities:

- validate that the answer addresses the user question
- validate that paragraph main claims are supported
- distinguish weakly supported auxiliary claims from explicitly unsupported auxiliary claims

#### `answer_review_fuse`

Responsibilities:

- combine paragraph provenance review and answer content review
- route unsupported auxiliary-only failures to repair
- route main-claim failures to retry/exit behavior rather than cosmetic repair

#### `answer_repair`

Responsibilities:

- remove explicitly unsupported auxiliary clauses
- recalculate paragraph citation sets when content changes
- rerender the draft/final answer after repair
- avoid restoring the old unit-level citation insertion strategy

#### `answer_commit`

Responsibilities:

- commit the latest structured paragraphs and rendered final answer
- preserve summary and routing data for observability

## 8. Core internal model

The new internal truth model is paragraph-first.

### 8.1 `answer_paragraphs`

Each paragraph should have at least:

```json
{
  "paragraph_id": "p1",
  "text": "CoT suits single-path logical reasoning with lower compute cost.",
  "citation_ids": ["S1", "S2"],
  "claims": [
    {
      "claim_id": "p1c1",
      "claim_text": "CoT suits single-path logical reasoning.",
      "role": "main",
      "support_status": "supported",
      "supporting_citation_ids": ["S1"]
    },
    {
      "claim_id": "p1c2",
      "claim_text": "It has lower compute cost.",
      "role": "auxiliary",
      "support_status": "weak_supported",
      "supporting_citation_ids": ["S2"]
    }
  ],
  "review_status": "passed"
}
```

### 8.2 Claim roles

Every claim must be categorized as:

- `main`: required to preserve the paragraph's main user-facing meaning
- `auxiliary`: supporting, comparative, contextual, or elaborative detail

### 8.3 Claim support states

Every claim must be categorized as:

- `supported`
- `weak_supported`
- `unsupported`

### 8.4 Visible rendering contract

The user sees only paragraph text plus paragraph-end aggregate citation markers.

Example:

`CoT is better suited to single-path logical reasoning and usually costs less to compute.[S1][S2]`

The user does not see claim segmentation.

## 9. Review semantics

### 9.1 Paragraph provenance pass conditions

A paragraph passes provenance review when:

1. it requires grounding
2. it has a non-empty citation id set
3. all citation ids are allowed in the current evidence set
4. the paragraph main claim is compatible with the aggregate citation set

### 9.2 Paragraph content pass conditions

A paragraph may pass content review when:

1. its main claim is supported
2. any unsupported content is limited to auxiliary claims that are safe to delete
3. weakly supported auxiliary claims do not materially distort the paragraph main idea

### 9.3 Hard-failure conditions

A paragraph fails hard when:

1. its main claim is unsupported
2. its citation ids are invalid and cannot be repaired safely
3. its visible paragraph meaning materially exceeds the support available in the cited source set

### 9.4 Repairable conditions

A paragraph is repairable when:

1. it contains unsupported auxiliary claims only
2. it is missing paragraph-level citations but the correct source set can be recovered safely
3. paragraph citation ids need to be recalculated after removing unsupported auxiliary content

## 10. State and contract model

This is a latest-only design, so state may be simplified without preserving legacy compatibility.

### 10.1 Core graph state additions

`KbChatInternalState` should add:

- `answer_paragraphs: list[dict[str, Any]]`
- `answer_render_meta: dict[str, Any]`

### 10.2 Existing fields retained as latest contracts

These fields remain useful and stay in the latest model:

- `final_context`
- `evidence_items`
- `citation_catalog`
- `draft_answer`
- `final_answer`
- `answer_review_runs`
- `reflection`
- `stage_summaries`
- `answer_subgraph_state`

### 10.3 `draft_answer` and `final_answer`

These remain rendered user-facing strings, but they become projections of `answer_paragraphs`, not the primary truth source.

### 10.4 `answer_review_runs`

`answer_review_runs` should keep its append-only shape, but each run should be allowed to include richer details:

- `details`
- `affected_paragraph_ids`
- `repair_scope`

### 10.5 `reflection.review_breakdown`

This stays as the compact routing summary and should contain:

- review pass/fail for citation and answer checks
- paragraph-level aggregate counts
- whether failure is repairable
- whether unsupported scope is `auxiliary_only` or `includes_main`

### 10.6 `stage_summaries`

Recommended new or updated summary entries:

- `stage_summaries.draft_generate`
  - paragraph count
  - claim count
  - citation aggregation mode
- `stage_summaries.answer_review`
  - paragraph pass/fail counts
  - repair target count
  - unsupported auxiliary count
- `stage_summaries.answer_repair`
  - removed auxiliary claim count
  - rerendered paragraph count

## 11. Prompt and schema redesign

### 11.1 Remove old citation prompt contract

Delete the old `kb_chat/citation_review` prompt contract that asks the model to classify punctuation-delimited uncovered fragments.

### 11.2 Replace with paragraph-grounding review contract

Introduce a new prompt contract for paragraph-level provenance review. It should accept:

- question
- allowed evidence set
- structured paragraph payload
- paragraph citation sets
- paragraph claims with roles

It should decide:

- paragraph passed or failed
- missing or invalid paragraph citation sets
- whether the paragraph main claim is aligned with the aggregate citation set

### 11.3 Update draft-generation contract

The draft-generation contract should explicitly require:

1. paragraph-level output planning
2. paragraph-end aggregate citation sets
3. claim role awareness
4. no per-sentence citation obligation
5. no unsupported auxiliary content when avoidable

### 11.4 Update answer-review contract

The answer-review contract should explicitly state:

- main-claim support is decisive
- weakly supported auxiliary details do not automatically fail the paragraph
- explicitly unsupported auxiliary content should be marked for repair

## 12. Latest-only cutover plan

This refactor intentionally removes the old implementation rather than maintaining two systems.

### 12.1 Directly remove

1. `review_citation_coverage(...)` and related unit-level coverage helpers
2. `_citation_coverage_score(...)` in its current uncovered-unit form
3. the old `kb_chat/citation_review.yaml` fragment-criticality contract
4. old tests whose purpose is only to protect punctuation-unit citation coverage behavior

### 12.2 Preserve and repurpose

1. `resolve_structured_evidence(...)`
2. `citation_catalog`
3. `answer_review_dispatch`
4. `answer_review_fuse`
5. `answer_repair`
6. `answer_commit`

### 12.3 Implementation order

1. add new paragraph/claim schema
2. upgrade draft generation to output structured paragraphs and rendered draft text
3. rewrite citation review to consume paragraph structure
4. rewrite answer review to consume paragraph structure
5. rewrite repair to delete unsupported auxiliary claims and rerender paragraphs
6. delete old unit-level review utilities and tests
7. verify with targeted tests and lint

## 13. Test strategy

Because this is a destructive refactor, old behavior-preservation tests should not be kept unless they validate still-desired behavior.

### 13.1 Unit tests

Add or rewrite tests for:

1. single paragraph, single source, supported main claim -> pass
2. single paragraph, multi-source aggregate citation set -> pass
3. supported main claim + weak auxiliary claim -> pass
4. supported main claim + unsupported auxiliary claim -> repair removes auxiliary content
5. unsupported main claim -> fail
6. invalid paragraph citation ids -> fail or repair depending on recoverability
7. grounding-required paragraph with empty citation set -> `missing_citations`
8. paragraph that does not require grounding -> may pass without citations

### 13.2 Prompt/schema contract tests

Add tests for:

- structured draft-generation output shape
- paragraph-grounding review output shape
- main-vs-auxiliary support classification behavior
- repair behavior that deletes unsupported auxiliary claims without widening supported content

### 13.3 Graph routing tests

Add routing tests for:

1. all paragraphs pass -> `answer_commit`
2. auxiliary-only unsupported content -> `answer_repair`
3. main-claim unsupported content -> retry/exit path
4. missing or invalid paragraph citations -> repair path when safe

### 13.4 Replay-style regression tests

Include real answer samples that previously failed for missing per-sentence citation markers but should pass under paragraph-level aggregate citation review.

## 14. Risks and mitigations

### Risk 1: paragraph citation aggregation becomes too permissive

Mitigation:

- require paragraph main-claim support against the aggregate citation set
- do not let unsupported main claims pass just because the paragraph cites something

### Risk 2: repair becomes overly destructive

Mitigation:

- limit repair to explicitly unsupported auxiliary claims
- keep main-claim deletion out of automatic repair scope

### Risk 3: structured generation increases implementation complexity

Mitigation:

- keep the public answer string contract stable (`draft_answer`, `final_answer`)
- restrict new structure to `answer_paragraphs` and compact review metadata

## 15. Success criteria

This redesign is successful when:

1. user-visible answers show paragraph-end aggregate citations instead of sentence-level citation pressure
2. paragraph main claims determine review pass/fail behavior
3. unsupported auxiliary claims are removed by repair rather than forcing sentence-level citation insertion
4. old unit-level citation coverage utilities are removed from the live path
5. tests cover the new paragraph-grounding contract and the latest-only answer-review flow

# KB Chat LLM-Driven Query Understanding and Review Design

- Date: 2026-03-18
- Status: Approved for planning
- Scope: KB Chat only; no changes to general chat

## 1. Summary

This design restructures the KB Chat live path around LLM-driven query understanding, retrieval planning, context compression, and answer review, while removing two rule-heavy control layers that the user no longer wants:

- remove the evidence sufficiency gate completely
- remove confidence calibration completely

The resulting runtime path becomes:

`preprocess_subgraph -> retrieval_subgraph -> answer_subgraph`

Inside that path:

- coreference resolution becomes LLM-driven
- question normalization becomes rule-first, then LLM refinement
- retrieval budget planning becomes LLM-driven with rule fallback
- context compression keeps the current LLM-only fail-open shape, but gets a stronger prompt
- factual answer review reads the full context and full draft without truncation

## 2. User-approved decisions

The following behavioral choices were explicitly confirmed:

1. LLM-driven nodes use fail-open behavior.
   - reference resolution failure => keep original query
   - retrieval planning failure => fall back to conservative default budget
   - factual review failure => do not block the main path; keep explicit fallback markers
2. Live node ids may be renamed to better match the new semantics.
3. After removing evidence sufficiency, weak retrieval should still continue to draft generation.
4. For factual review, use the full `final_context` and full `draft_answer`; do not truncate for the current model window assumptions.

## 3. Goals

1. Replace remaining heuristic-only query understanding nodes with LLM-driven behavior where requested.
2. Keep the system observable and grep-friendly with explicit node ids, summaries, and fallback markers.
3. Remove unwanted live control nodes and all related runtime contract residue.
4. Keep the change set focused on KB Chat; do not opportunistically redesign unrelated retrieval or UI behavior.

## 4. Non-goals

1. Do not redesign Milvus retrieval itself.
2. Do not collapse multiple understanding steps into one opaque mega-node.
3. Do not rewrite the frontend interaction model; frontend remains render-only over backend contracts.
4. Do not remove HyDE, decomposition, or variant generation unless required by direct contract cleanup.

## 5. Current observed runtime state

Based on the current repository:

- `coref_rewrite` is still heuristic-only and delegates to `QueryRewriteService.coref_rewrite(...)`.
- `normalize_rewrite` is already rule-first plus structured LLM refinement.
- `retrieval_budget_plan` is still deterministic and depends on complexity, prior failure reason, and retry count.
- `context_compress` is already LLM-driven fail-open, but uses a lightweight prompt and fixed `max_tokens`.
- `doc_gate_sufficiency` and `doc_gate_route` still exist as live runtime nodes.
- `draft_generate` still binds `max_tokens=1024`.
- `_answer_review_llm_check(...)` still truncates context and draft.
- `confidence_calibrate` still exists as a live finalization node.

This means the repo already has part of the desired direction, but not the final live contract.

## 6. Proposed runtime architecture

### 6.1 Top-level path

Replace the current public live path with:

`preprocess_subgraph -> retrieval_subgraph -> answer_subgraph`

There is no live `evidence_gate_subgraph`.
There is no live `confidence_calibrate`.

Terminal convergence becomes:

- `answer_commit -> END`
- `force_exit -> END`
- `transform_query -> retrieval_subgraph`

### 6.2 Preprocess subgraph

Target shape:

`merge_context -> resolve_reference -> ambiguity_check -> query_normalize -> complexity_classify -> (decomposition / generate_variants_mod / generate_variants / entity_expand / hyde) -> prepare_messages`

Rationale:

- preserve current enhancement chain that already matches common RAG practice
- replace only the meaningfully outdated nodes
- keep observability at node granularity

### 6.3 Retrieval subgraph

Target shape:

`retrieval_plan -> dispatch_subqueries -> (retrieve | retrieve_subquery -> merge_subquery_context) -> context_compress`

Rationale:

- retrieval planning becomes LLM-driven
- subquery dispatch and retrieval execution remain separate and observable
- context compression remains immediately before answer generation

### 6.4 Answer subgraph

Target shape:

`draft_generate -> answer_review_dispatch -> [answer_review_citation / answer_review_factual / answer_review_answerability] -> answer_review_fuse -> (answer_commit | answer_repair | transform_query | force_exit)`

Rationale:

- continue generating even when retrieval is weak
- let answer review and repair be the quality-control layer
- remove the redundant evidence gate layer
- remove confidence calibration from the runtime live path

## 7. Node rename map

Only rename nodes whose semantics materially change.

| Current node id | New node id | Reason |
| --- | --- | --- |
| `coref_rewrite` | `resolve_reference` | becomes LLM-driven reference resolution instead of heuristic rewrite |
| `normalize_rewrite` | `query_normalize` | better matches rule-first plus LLM normalization semantics |
| `retrieval_budget_plan` | `retrieval_plan` | becomes structured LLM retrieval planning instead of deterministic budgeting |

These node ids remain unchanged:

- `merge_context`
- `ambiguity_check`
- `complexity_classify`
- `generate_variants_mod`
- `decomposition`
- `generate_variants`
- `entity_expand`
- `hyde`
- `prepare_messages`
- `dispatch_subqueries`
- `retrieve_subquery`
- `merge_subquery_context`
- `retrieve`
- `context_compress`
- `draft_generate`
- `answer_review_dispatch`
- `answer_review_citation`
- `answer_review_factual`
- `answer_review_answerability`
- `answer_review_fuse`
- `answer_repair`
- `answer_commit`
- `transform_query`
- `force_exit`

## 8. Detailed node contracts

### 8.1 `resolve_reference`

#### Inputs

- `rewrite_input_query`, else `user_input`
- `context_frame.selected_turns`
- `context_frame.summary_text`
- `context_frame.memory_snippet`

#### Outputs

- `resolved_query`
- `reference_resolution_meta`
- `stage_summaries.resolve_reference`

#### `reference_resolution_meta`

Recommended structure:

```json
{
  "resolved": true,
  "decision_source": "llm",
  "confidence": 0.86,
  "resolved_span": "它",
  "antecedent": "Qwen3-Embedding-8B",
  "fallback_used": false,
  "fallback_reason": ""
}
```

#### Behavior

- use the context only to resolve pronouns, omitted referents, or short anaphoric forms
- do not broaden the query
- do not perform generic retrieval optimization here

#### Fail-open

- invalid output, empty output, or model failure => `resolved_query = original query`

#### Cleanup requirement

Remove the current heuristic candidate-scoring and replacement path rather than leaving it as a dormant fallback branch.

### 8.2 `query_normalize`

#### Inputs

- `resolved_query`, else the original query
- runtime/settings for alias limits and related normalization controls

#### Outputs

- `normalized_query`
- `normalized_meta`
- `stage_summaries.query_normalize`

#### Behavior

Two-stage flow:

1. rules first
   - preserve numbers, years, time ranges, comparisons, negation, scope, and metric terms
   - remove obvious conversational noise
2. LLM second
   - produce canonical query
   - extract aliases, entities, and constraints
   - preserve retrieval-critical intent

#### Required invariants

The LLM must not silently widen the scope of the question and must preserve:

- numbers
- time constraints
- comparison targets
- negation and exceptions
- scope restrictions

#### Fail-open

- rule stage failure => return original query
- LLM stage failure => return rule-normalized query

### 8.3 `retrieval_plan`

#### Inputs

- `normalized_query`
- `query_items`
- `complexity_level`
- `loop_counts`
- prior failure reason, if any

#### Outputs

- `retrieval_budget`
- `retrieval_plan_meta`
- `stage_summaries.retrieval_plan`

#### `retrieval_budget`

Keep the existing downstream-friendly shape:

```json
{
  "per_query_top_k": 8,
  "global_candidates_limit": 36,
  "rerank_input_limit": 20
}
```

#### `retrieval_plan_meta`

Recommended structure:

```json
{
  "decision_source": "llm",
  "reasoning": "问题跨多个实体且含比较，适合更高候选上限",
  "retry_count": 1,
  "fallback_used": false,
  "fallback_reason": ""
}
```

#### Behavior

- LLM proposes a structured retrieval budget
- backend clamps every numeric field to configured bounds
- downstream retrieval logic continues to use the existing `retrieval_budget` contract

#### Fail-open

- invalid JSON, missing numeric fields, out-of-bounds values, or model failure => reuse the current conservative rule formula

### 8.4 `context_compress`

#### Inputs

- `final_context`
- question text, preferably `normalized_query`

#### Outputs

- updated `final_context`
- `compression_stats`
- `stage_summaries.context_compress`

#### Prompt requirements

The prompt must explicitly preserve:

- key facts
- original citation labels such as `[S1]`
- numbers and thresholds
- time conditions
- exceptions and limitations
- comparison baselines
- causal or prerequisite relationships

#### Fail-open

Keep the current fail-open shape:

- failure => original context
- empty compression => original context
- non-compacting output => original context
- suspicious loss of citation anchors => original context

### 8.5 `draft_generate`

#### Inputs

- question
- full `final_context`

#### Outputs

- `draft_answer`
- `final_answer` may still mirror draft for force-exit safety

#### Change

Remove the current `chat_model.bind(max_tokens=1024)` limit entirely.

#### Fail-open

Keep the existing fallback refusal path when generation fails.

### 8.6 `answer_review_factual`

#### Inputs

- question
- full `final_context`
- full `draft_answer`

#### Outputs

- factual entry in `answer_review_runs`
- `stage_summaries.answer_review_factual`

#### Change

Remove all runtime truncation of:

- `final_context[:4000]`
- `draft[:2000]`

#### Behavior

- remain fully LLM-driven
- review unsupported claims, contradictions, and citation mismatch against the full context

#### Fail-open

- model failure does not block the main path
- explicit fallback markers must still be emitted

## 9. Prompting strategy

All new or updated LLM nodes should use constrained outputs rather than free-form behavior.

### 9.1 `resolve_reference`

Purpose:

- resolve references only

Constraints:

- only use provided context
- do not broaden the query
- if uncertain, keep the original query
- output structured JSON

### 9.2 `query_normalize`

Purpose:

- conservative normalization over rule-produced input

Constraints:

- do not delete or weaken numeric, temporal, negative, or scope constraints
- output structured JSON with canonical query, aliases, and constraint fields

### 9.3 `retrieval_plan`

Purpose:

- produce realistic retrieval budgets and rationale

Constraints:

- output budget only, not a rewritten query
- values must remain within backend clampable ranges
- output structured JSON

### 9.4 `context_compress`

Purpose:

- compress evidence only

Constraints:

- preserve citation tags and critical factual qualifiers
- if safe compression is impossible, effectively return the original content
- output plain text only

### 9.5 `answer_review_factual`

Purpose:

- factual review against the full evidence set

Constraints:

- focus on unsupported claims, contradictions, and missing support for key assertions
- output structured JSON

## 10. Removed runtime contracts

### 10.1 Remove evidence gate runtime contract

Remove all live runtime usage of:

- `evidence_gate_subgraph`
- `doc_gate_sufficiency`
- `doc_gate_route`
- `routing_decisions.doc_gate`
- `stage_summaries.doc_gate_sufficiency`
- `stage_summaries.doc_gate_route`
- `doc_gate_runs`
- reflection mirror fields that exist only to support the gate live path

After this change, weak retrieval still continues to draft generation and answer review.

### 10.2 Remove confidence calibration runtime contract

Remove all live runtime usage of:

- `confidence_calibrate`
- `stage_summaries.confidence_calibrate`
- `confidence_score`
- `confidence_level`

Runtime convergence should no longer rely on a dedicated confidence node.

## 11. State-key guidance

To reduce blast radius, keep these high-value keys stable where possible:

- `normalized_query`
- `query_items`
- `retrieval_budget`
- `final_context`
- `draft_answer`
- `final_answer`

Replace:

- `coref_query` -> `resolved_query`
- `coref_meta` -> `reference_resolution_meta`

Also keep node id, trace metadata, and `stage_summaries` naming aligned with the new canonical names.

## 12. Backend and frontend contract impact

### 12.1 Backend changes

- graph node ids
- trace node metadata
- stage summary keys
- graph schema output
- terminal routing after answer review

### 12.2 Frontend changes

- KB node catalog ids, labels, and order
- graph schema tests and snapshots
- final-node detection and answer reveal logic after removing `confidence_calibrate`
- any label fallback that still references removed node ids

### 12.3 Explicit non-changes

- no redesign of the page-level interaction model
- frontend remains render-only over backend contracts
- retrieval service implementation remains structurally intact

## 13. Testing and regression strategy

### 13.1 Backend tests

At minimum, add or update tests that verify:

1. graph/schema cleanup
   - removed nodes do not appear in the live graph contract
2. routing/state cleanup
   - no live `routing_decisions.doc_gate`
   - no live `confidence_score` or `confidence_level` contract
3. preprocess behavior
   - `resolve_reference` fail-open returns original query
   - `query_normalize` uses rule-first and falls back to rules on LLM failure
4. retrieval planning behavior
   - LLM planner output is clamped
   - planner failures fall back to conservative rule budget
5. answer review behavior
   - factual review no longer truncates context or draft
6. negative guards
   - removed node ids and removed summary keys cannot silently re-enter the live contract

### 13.2 Frontend tests

At minimum, update tests for:

- `kbNodeCatalog.ts`
- `kbNodeCatalog.test.ts`
- graph-schema-based node ordering and labeling
- terminal/finalize node resolution after removing `confidence_calibrate`

## 14. Rollout order

To reduce contract drift risk, implement in this order:

1. remove live contract and graph wiring for deleted nodes
2. replace node implementations and rename runtime ids
3. update trace metadata, service schema, and frontend catalog
4. update docs and regression tests

This order minimizes the half-aligned state where backend removes nodes but frontend still treats them as live.

## 15. Risks and mitigations

### Risk 1: contract drift between backend and frontend

Mitigation:

- treat node id, trace metadata, and frontend catalog as one change set

### Risk 2: LLM planner instability

Mitigation:

- keep backend clamp logic
- keep conservative rule fallback

### Risk 3: normalization drift broadens the user question

Mitigation:

- preserve explicit invariants for numbers, time, scope, comparison, and negation
- add regression tests around constraint preservation

### Risk 4: compression loses crucial qualifiers

Mitigation:

- strengthen prompt with explicit preservation rules
- fail open on suspicious output

## 16. Acceptance criteria

This design is satisfied when:

1. KB Chat has no live evidence gate nodes.
2. KB Chat has no live confidence calibration node or final confidence contract.
3. reference resolution is LLM-driven and no longer uses the current heuristic implementation.
4. query normalization is explicitly rule-first, then LLM.
5. retrieval planning is LLM-driven with conservative rule fallback.
6. context compression prompt explicitly preserves critical evidence qualifiers.
7. draft generation no longer binds `max_tokens=1024`.
8. factual review reads full `final_context` and full `draft_answer`.
9. frontend catalog, graph schema, and tests are aligned with the new runtime contract.

## 17. References

- Azure AI Search query rewrite: https://learn.microsoft.com/en-us/azure/search/semantic-how-to-query-rewrite
- Azure Architecture Center RAG retrieval guide: https://learn.microsoft.com/azure/architecture/ai-ml/guide/rag/rag-information-retrieval
- Rewrite-Retrieve-Read: https://aclanthology.org/2023.emnlp-main.322/
- Query2doc: https://aclanthology.org/2023.emnlp-main.585/
- HyDE: https://aclanthology.org/2023.acl-long.99/

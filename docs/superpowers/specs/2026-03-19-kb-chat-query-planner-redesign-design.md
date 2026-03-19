# KB Chat Query Planner Redesign Design

- Date: 2026-03-19
- Status: Approved for planning
- Scope: KB Chat only; no changes to general chat

## 1. Summary

This design replaces the current KB Chat query enhancement chain that mixes rule-based token extraction, alias expansion, decomposition, multi-query generation, entity expansion, HyDE, and late query bundling with a single explicit query planner.

The new runtime shape becomes:

`merge_context -> resolve_reference -> query_normalize -> query_plan -> retrieval_subgraph -> answer_subgraph`

Within this shape:

- `resolve_reference` remains conservative and context-bound
- `query_normalize` remains responsible for canonicalization plus structured constraint extraction
- `query_plan` becomes the only node allowed to decide whether to use direct retrieval, paraphrase expansion, decomposition, or HyDE fallback
- fragment queries and mechanically concatenated constraint variants are removed from the live path
- retrieval fallback becomes staged instead of enabling every enhancement strategy up front

## 2. User-approved decisions

The following decisions are explicitly approved for this redesign:

1. Destructive refactoring is allowed.
2. The current query enhancement chain may be collapsed into a smaller number of nodes.
3. Fragment-only query items such as isolated tokens or incomplete noun phrases may be removed from the live path.
4. Constraint-concatenated variants may be removed from the live path.
5. Trace contracts may be changed if the new contracts are more explicit and business-readable.
6. The redesign must be grounded in current industrial and academic best practices.
7. The result should be written as repo-local design and implementation documents for later approval-driven execution.

## 3. Goals

1. Replace heuristic query expansion that currently over-produces low-semantic-value variants.
2. Align KB Chat retrieval preparation with current best practices: adaptive rewrite, explicit planning, controlled expansion, and staged fallback.
3. Preserve observability by making query planning decisions explicit in trace output.
4. Reduce retrieval noise, rerank burden, and query-count inflation caused by fragment queries.
5. Keep the change isolated to KB Chat contracts, prompts, retrieval orchestration, and trace/UI rendering.

## 4. Non-goals

1. Do not redesign Milvus storage, hybrid search internals, or collection layout in this phase.
2. Do not redesign answer synthesis, answer review policy, or frontend interaction patterns outside query-planning display changes.
3. Do not introduce a new external search product or move retrieval into Azure/OpenAI managed retrieval.
4. Do not attempt synonym-map/index-level redesign in the same phase; that is a follow-on option.
5. Do not change general chat behavior.

## 5. Current observed problems in the repository

Based on the current code paths:

- `query_normalize` currently derives `entities` via `_extract_query_focus_terms(...)` and then derives `aliases` from the first two entities.
- `prepare_messages` currently adds variants from `multi_queries`, `aliases`, and `_build_constraint_variants(...)`.
- `_build_constraint_variants(...)` constructs query strings by concatenating the base query with extracted entities and constraints.
- `build_query_items(...)` treats all accepted variants as equivalent retrieval candidates with only light quality scoring and filtering.
- trace/UI currently show only `[main]` and `[variant]` formatting, which hides why a query was produced and whether it is semantically complete.

Observed failure mode example:

- user query: `解释agent的记忆系统`
- current live outputs can include:
  - `[main] 解释agent的记忆系统`
  - `[variant] agent`
  - `[variant] 的记忆系统`
  - `[variant] 解释agent的记忆系统 agent 的记忆系统 解释`
  - `[variant] 解释agent的记忆系统 agent 的记忆系统`

These outputs show two repo-local design issues:

1. token extraction is being reused as alias generation
2. constraint preservation is implemented as string concatenation instead of planner-controlled rewrite or structured filtering

## 6. Research-grounded design principles

This design follows the direction supported by current industrial and academic work:

1. Keep query preprocessing, but make it adaptive rather than purely heuristic.
2. Preserve a canonical main query for every request.
3. Only generate additional queries when there is evidence of likely recall gain.
4. Require expansion queries to remain semantically complete.
5. Prefer controlled synonym/alias expansion or planner-generated paraphrases over token fragments.
6. Treat HyDE and broadening strategies as fallback tools, not default always-on steps.
7. Make planner intent visible in trace contracts so operators can audit why each query exists.

## 7. Proposed runtime architecture

### 7.1 Top-level path

Target live path:

`preprocess_subgraph -> retrieval_subgraph -> answer_subgraph`

Inside preprocess:

`merge_context -> resolve_reference -> query_normalize -> query_plan`

There is no live path through the current enhancement chain of:

- `complexity_classify`
- `generate_variants_mod`
- `decomposition`
- `generate_variants`
- `entity_expand`
- `hyde`
- `prepare_messages`

Those responsibilities are replaced or absorbed into `query_plan`, with HyDE retained as an internal fallback capability rather than a first-class live preprocessing node.

### 7.2 Query planner responsibilities

`query_plan` owns all of the following decisions:

1. whether the request should run as `direct`
2. whether paraphrase expansion is warranted
3. whether decomposition is warranted
4. whether HyDE should be prepared immediately or only on fallback
5. how many query items may enter first-pass retrieval
6. which query items are complete enough for retrieval
7. which structured constraints should be carried separately for future filter use

### 7.3 Query planner boundaries

`query_plan` must not:

- perform reference resolution
- silently broaden the user question beyond normalized intent
- emit fragment-only queries
- emit queries that fail semantic completeness checks
- emit concatenated constraint bags that only increase lexical overlap without improving intent fidelity

## 8. New state and contract model

### 8.1 Replace scattered preparation outputs with a planner result

Current scattered outputs:

- `sub_queries`
- `decomposition_plan`
- `multi_queries`
- `entity_expand_meta`
- `hyde_docs`
- `query_items`
- `message_plan`
- `query_bundle`
- `prepare_diagnostics`

New primary outputs:

- `query_plan_result`
- `query_items`
- `query_plan_diagnostics`

### 8.2 `query_plan_result`

Recommended structure:

```json
{
  "strategy": "direct",
  "reasoning": "canonical query is already retrieval-ready; no safe gain from expansion",
  "fallback_policy": {
    "allow_broaden": true,
    "allow_hyde": true,
    "allow_retry_rewrite": true
  },
  "items": [
    {
      "kind": "main",
      "query": "解释agent的记忆系统",
      "strategy_source": "canonical",
      "trigger_reason": "always_keep_main",
      "semantic_complete": true,
      "preserve_constraints": true,
      "retrieval_mode": "hybrid",
      "priority": 1,
      "purpose": "primary retrieval"
    }
  ]
}
```

### 8.3 Query item invariants

Every emitted `query_items[*]` must satisfy:

1. `query` is non-empty after normalization
2. `semantic_complete` is true
3. `preserve_constraints` is true for all first-pass items except explicitly approved broadening fallback items
4. `kind` is one of:
   - `main`
   - `paraphrase`
   - `subquery`
   - `hyde`
   - `retry`
5. `strategy_source` is one of:
   - `canonical`
   - `planner_llm`
   - `lexicon`
   - `fallback`
6. fragment-only or orphaned phrase queries are rejected before entering `query_items`

### 8.4 Removed query item categories

The live contract no longer contains these implicit categories:

- regex-derived alias fragments
- mechanical constraint variants
- variant buckets with no explicit trigger reason

## 9. Query generation policy

### 9.1 Main query

Always retain one canonical query item:

- source: `normalized_query`, falling back to resolved/original query if needed
- kind: `main`
- retrieval mode: `hybrid`
- priority: highest

### 9.2 Paraphrase expansion

Allowed only when at least one of these holds:

- mixed-language terminology
- acronym-heavy query
- user phrasing likely diverges from corpus phrasing
- high recall risk detected in normalization metadata

Rules:

- maximum 1 to 2 paraphrases in first pass
- each paraphrase must preserve entities, time, metric, scope, errors, versions, and exclusions
- each paraphrase must be semantically complete and independently retrievable

### 9.3 Decomposition

Allowed only when the question is genuinely multi-target, comparative, or process-like.

Rules:

- decomposition is not a generic recall booster
- subqueries must each have explicit purpose and coverage tags
- subqueries must remain independent enough for parallel retrieval
- no decomposition for simple factual questions

### 9.4 HyDE

HyDE is retained but demoted to controlled use:

- preferred as fallback after weak first-pass retrieval
- may be first-pass only for clearly abstract or sparse lexical-match questions
- always marked as `dense_only`
- must not replace the canonical main query

### 9.5 Structured constraints

Constraint information extracted by `query_normalize` remains in metadata but is not converted into concatenated search strings.

Near-term policy:

- preserve structured constraint fields in state and diagnostics
- planner uses them to validate rewrites and reject drift
- retrieval can continue to rely on query text plus existing runtime config in phase one

Follow-on policy:

- future phases may convert some constraints into retrieval filters once retrieval infrastructure supports it cleanly

## 10. Two-stage retrieval strategy

### 10.1 First pass

First pass should run only high-confidence planned items:

- main query
- up to two planner-approved paraphrases or subqueries
- no fragment items
- no broadening variants
- HyDE only when explicitly triggered

### 10.2 Fallback pass

Fallback is triggered only if retrieval diagnostics indicate weak evidence quality, empty/near-empty recall, or repeated low-quality results.

Fallback order:

1. planner broadening retry
2. HyDE if not already used
3. transform-query retry path

This replaces the current approach of preparing many candidate query types before retrieval quality is known.

## 11. Trace and UI redesign

### 11.1 Node naming

Rename `prepare_messages` to `query_plan`.

Removed live nodes from trace catalog:

- `complexity_classify`
- `generate_variants_mod`
- `decomposition`
- `generate_variants`
- `entity_expand`
- `hyde`
- `prepare_messages`

### 11.2 Display contract

Replace the current `[main]` and `[variant]` only display with richer planner-oriented formatting.

Recommended list rendering:

1. `[main|canonical] 解释agent的记忆系统`
2. `[paraphrase|planner_llm] 智能体记忆系统`
3. `[hyde|fallback] ...`

Per item, display should be able to surface:

- `kind`
- `strategy_source`
- `trigger_reason`
- `semantic_complete`
- `retrieval_mode`
- `purpose`

### 11.3 Planner summary

Trace summary for `query_plan` should show:

- selected strategy
- selected item count
- fallback allowances
- rejection counts by reason, such as:
  - `fragment_rejected`
  - `constraint_drift_rejected`
  - `duplicate_rejected`
  - `over_budget_rejected`

## 12. File-level refactor map

### 12.1 New modules

- `backend/src/app/services/kb_query_planner_service.py`
  - owns planner entry point, validation, policy application, and query item construction
- `backend/src/app/services/kb_query_policy.py`
  - owns deterministic acceptance/rejection rules for query items
- `backend/src/app/prompts/templates/kb_chat/query_plan.yaml`
  - owns structured planner prompt

### 12.2 Major modifications

- `backend/src/app/agents/preprocess_subgraph.py`
  - replace live node registration and edge wiring for the current enhancement chain with `query_plan`
- `backend/src/app/agents/kb_chat_agentic/preprocess.py`
  - delete current late query bundling path
  - add `query_plan` node
- `backend/src/app/services/query_rewrite_service.py`
  - keep `normalize_rewrite` and optional HyDE helper
  - stop owning live query planning heuristics
- `backend/src/app/agents/kb_chat_agentic_state.py`
  - add `query_plan_result` / `query_plan_diagnostics`
  - remove obsolete enhancement state from the live contract
- `backend/src/app/schemas/query_enhancement.py`
  - redefine query item schema around planner fields
- `backend/src/app/agents/retrieval_subgraph.py`
  - accept planner output directly
  - implement staged fallback behavior
- `backend/src/app/agents/kb_chat_agentic/reflection.py`
  - retry paths rebuild planner output instead of recreating old enhancement chain
- `backend/src/app/agents/kb_chat_trace_display_contract.py`
  - render richer query-plan items
- `backend/src/app/agents/kb_chat_trace_nodes.py`
  - update node ids, labels, and phase ordering

### 12.3 Retired prompts or logic

Retire from the live path:

- `backend/src/app/prompts/templates/kb_chat/multi_query.yaml`
- `backend/src/app/prompts/templates/kb_chat/entity_expand.yaml`
- `backend/src/app/prompts/templates/kb_chat/decomposition.yaml`
- `_build_constraint_variants(...)`
- `_compose_query_terms(...)`
- `aliases = entities[:2]`-driven live expansion

HyDE prompt remains but is called only by planner/fallback policy.

## 13. Testing and verification strategy

### 13.1 Contract tests

Add or update tests to guarantee:

- fragment queries never enter `query_items`
- planner keeps canonical main query
- planner emits only semantically complete items
- mixed-language queries can yield planner-approved complete paraphrases
- decomposition occurs only on appropriate question types
- HyDE is not always-on
- retry/fallback rebuilds planner output instead of reviving retired logic

### 13.2 Trace tests

Add or update tests to guarantee:

- `query_plan` is the live node label
- removed nodes are absent from the trace catalog
- query item rendering includes planner metadata
- planner diagnostics are visible and grep-friendly

### 13.3 Robustness evaluation

Create a query perturbation evaluation set covering:

- synonym substitution
- word-order shifts
- bilingual phrasing
- acronym expansion/contraction
- conversational vs formal wording
- noisy filler words

Measure:

- retrieval recall@k
- rerank quality
- citation precision
- query count per request
- latency p50 and p95
- fallback rate

## 14. Rollout plan

### Phase 0: Shadow planner

- compute `query_plan_result` in parallel with old logic
- do not execute it live
- compare planner outputs, query counts, and retrieval diagnostics

### Phase 1: Gated live rollout

- enable planner for high `recall_risk`, mixed-language, and acronym-heavy requests
- keep old path for the remainder while metrics stabilize

### Phase 2: Full cutover

- remove retired nodes from graph, state, and trace contracts
- switch retrieval execution to planner-driven items only

### Phase 3: Follow-on retrieval improvements

- structured filtering
- controlled lexicon/synonym tables
- query-feedback adaptive optimization

## 15. Risks and mitigations

### Risk 1: Planner over-compresses the current chain and hides useful observability

Mitigation:

- keep planner diagnostics explicit
- keep item-level metadata in trace and state
- preserve retry/fallback summaries

### Risk 2: Planner under-produces expansion on long-tail queries

Mitigation:

- staged fallback with planner broadening and HyDE
- shadow-mode metric comparison before cutover

### Risk 3: Trace/frontend churn is larger than backend-only changes

Mitigation:

- make trace contract migration explicit in the same batch
- keep labels business-readable and grep-friendly

### Risk 4: Existing heuristics still leak through retry paths

Mitigation:

- remove retired helper usage from retry code paths
- add negative tests for fragment items and retired nodes

## 16. Approval result

This design is approved for implementation planning.
The next artifact should be a task-by-task implementation plan that assumes zero context and uses explicit files, commands, and verification steps.

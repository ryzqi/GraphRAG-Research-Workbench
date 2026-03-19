# KB Chat Query Planner Redesign Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace KB Chat's current heuristic multi-step query enhancement chain with a single adaptive `query_plan` stage that emits only complete, policy-approved retrieval queries and supports staged fallback.

**Architecture:** Keep `resolve_reference` and `query_normalize` as explicit preprocess nodes, but collapse the later enhancement chain into one `query_plan` node backed by a dedicated planner service and planner policy. Retrieval consumes planner-approved `query_items`, while trace/UI shift from opaque `[variant]` rendering to strategy-aware planner metadata.

**Tech Stack:** Python 3.13, FastAPI, LangGraph, LangChain, Pydantic, pytest, React/TypeScript, vitest

---

## File map

### Backend runtime and services

- Create: `backend/src/app/services/kb_query_planner_service.py`
  - planner orchestration, structured prompt call, deterministic validation, query-item assembly
- Create: `backend/src/app/services/kb_query_policy.py`
  - semantic completeness checks, fragment rejection, budget clamps, fallback eligibility
- Modify: `backend/src/app/agents/preprocess_subgraph.py`
  - replace live node registration and edge wiring for the current enhancement chain with `query_plan`
- Modify: `backend/src/app/agents/kb_chat_agentic/preprocess.py`
  - remove retired enhancement nodes from the live path, add `query_plan`, persist planner state
- Modify: `backend/src/app/services/query_rewrite_service.py`
  - keep normalization and HyDE helpers, remove live ownership of heuristic alias/constraint query generation
- Modify: `backend/src/app/agents/kb_chat_agentic_state.py`
  - add planner result fields, remove retired live-state fields
- Modify: `backend/src/app/schemas/query_enhancement.py`
  - redefine `QueryItem` contract around planner metadata
- Modify: `backend/src/app/agents/retrieval_subgraph.py`
  - consume planner items directly and implement staged fallback
- Modify: `backend/src/app/agents/kb_chat_agentic/reflection.py`
  - rebuild planner outputs on retry instead of reviving old paths

### Prompts

- Create: `backend/src/app/prompts/templates/kb_chat/query_plan.yaml`
- Modify: `backend/src/app/prompts/templates/kb_chat/hyde.yaml`
  - narrow prompt role to fallback/dense-only planner use
- Retire from live path: `backend/src/app/prompts/templates/kb_chat/multi_query.yaml`
- Retire from live path: `backend/src/app/prompts/templates/kb_chat/entity_expand.yaml`
- Retire from live path: `backend/src/app/prompts/templates/kb_chat/decomposition.yaml`

### Trace and frontend contracts

- Modify: `backend/src/app/agents/kb_chat_trace_nodes.py`
- Modify: `backend/src/app/agents/kb_chat_trace_display_contract.py`
- Modify: `backend/src/app/agents/kb_chat_agentic_graph.py`
- Modify: `frontend/src/services/kbNodeCatalog.ts`
- Modify: `frontend/src/services/kbNodeCatalog.test.ts`
- Modify: `frontend/src/services/kbNodeLabels.ts`
- Modify: `frontend/src/services/kbNodeLabels.test.ts`
- Modify: `frontend/src/services/kbChatTraceNodes.ts`
- Modify: `frontend/src/services/kbChatTraceNodes.test.ts`

### Tests and docs

- Create: `backend/tests/services/test_kb_query_planner_service.py`
- Create: `backend/tests/agents/test_kb_query_planner_contract.py`
- Modify: `backend/tests/agents/test_kb_chat_state_schema.py`
- Modify: `backend/tests/agents/test_kb_chat_state_contract.py`
- Modify: `backend/tests/agents/test_kb_chat_routing_contract.py`
- Modify: `backend/tests/agents/test_kb_chat_trace_nodes.py`
- Modify: `docs/流程图.md`
- Modify: `docs/langgraph_constraints.md`

---

### Task 1: Lock the new planner contract with failing tests

**Files:**
- Create: `backend/tests/services/test_kb_query_planner_service.py`
- Create: `backend/tests/agents/test_kb_query_planner_contract.py`
- Modify: `backend/tests/agents/test_kb_chat_state_schema.py`
- Modify: `backend/tests/agents/test_kb_chat_state_contract.py`
- Modify: `backend/tests/agents/test_kb_chat_routing_contract.py`
- Modify: `backend/tests/agents/test_kb_chat_trace_nodes.py`

- [ ] **Step 1: Add a planner-unit test for fragment rejection**

```python
def test_query_planner_rejects_fragment_only_candidates() -> None:
    result = build_validated_query_items(
        normalized_query="解释agent的记忆系统",
        planned_items=[
            {"kind": "main", "query": "解释agent的记忆系统"},
            {"kind": "paraphrase", "query": "agent"},
            {"kind": "paraphrase", "query": "的记忆系统"},
        ],
    )
    assert [item["query"] for item in result.items] == ["解释agent的记忆系统"]
    assert result.rejections["fragment_rejected"] == 2
```

- [ ] **Step 2: Add a planner-unit test for constraint-preserving paraphrases**

```python
def test_query_planner_keeps_complete_mixed_language_paraphrase() -> None:
    result = build_validated_query_items(
        normalized_query="解释agent的记忆系统",
        planned_items=[
            {"kind": "main", "query": "解释agent的记忆系统"},
            {"kind": "paraphrase", "query": "智能体记忆系统"},
        ],
    )
    assert [item["query"] for item in result.items] == [
        "解释agent的记忆系统",
        "智能体记忆系统",
    ]
```

- [ ] **Step 3: Add a planner-contract test for the new live node id**

```python
def test_query_plan_replaces_prepare_messages_in_live_catalog() -> None:
    assert "query_plan" in KB_CHAT_NODE_METADATA
    assert "prepare_messages" not in KB_CHAT_NODE_METADATA
```

- [ ] **Step 4: Add negative contract tests for retired live nodes**

Cover absence of:
- `complexity_classify`
- `generate_variants_mod`
- `decomposition`
- `generate_variants`
- `entity_expand`
- `hyde`
- `prepare_messages`

- [ ] **Step 5: Add state-schema tests for new planner fields**

Cover presence of:
- `query_plan_result`
- `query_plan_diagnostics`

Cover absence from the live contract of:
- `multi_queries`
- `decomposition_plan`
- `entity_expand_meta`
- `message_plan`
- `query_bundle`
- `prepare_diagnostics`

- [ ] **Step 6: Run the focused backend tests to confirm RED**

Run: `cd backend; uv run pytest tests/services/test_kb_query_planner_service.py tests/agents/test_kb_query_planner_contract.py tests/agents/test_kb_chat_state_schema.py tests/agents/test_kb_chat_state_contract.py tests/agents/test_kb_chat_routing_contract.py tests/agents/test_kb_chat_trace_nodes.py -q`

Expected: failures cite missing planner files, stale node ids, and stale state fields.

- [ ] **Step 7: Commit the red tests**

Run:
- `git add backend/tests/services/test_kb_query_planner_service.py backend/tests/agents/test_kb_query_planner_contract.py backend/tests/agents/test_kb_chat_state_schema.py backend/tests/agents/test_kb_chat_state_contract.py backend/tests/agents/test_kb_chat_routing_contract.py backend/tests/agents/test_kb_chat_trace_nodes.py`
- `git commit -m "test: lock KB Chat query planner contract"`

### Task 2: Create deterministic planner policy and validation helpers

**Files:**
- Create: `backend/src/app/services/kb_query_policy.py`
- Create: `backend/tests/services/test_kb_query_planner_service.py`

- [ ] **Step 1: Write a failing unit test for semantic completeness checks**

```python
def test_is_semantically_complete_rejects_orphaned_phrases() -> None:
    assert is_semantically_complete("agent") is False
    assert is_semantically_complete("的记忆系统") is False
    assert is_semantically_complete("智能体记忆系统") is True
```

- [ ] **Step 2: Run the single test to confirm RED**

Run: `cd backend; uv run pytest tests/services/test_kb_query_planner_service.py -q -k semantic_complete`

Expected: FAIL because policy helpers do not exist.

- [ ] **Step 3: Implement minimal semantic-completeness and fragment-rejection helpers**

Implement helpers for:
- language-aware completeness heuristics
- duplicate rejection
- constraint-drift rejection
- candidate budget trimming

- [ ] **Step 4: Add a failing unit test for policy-controlled fallback eligibility**

```python
def test_should_enable_hyde_only_for_allowed_conditions() -> None:
    assert should_enable_hyde(strategy="direct", recall_risk="low", first_pass_failed=False) is False
    assert should_enable_hyde(strategy="direct", recall_risk="high", first_pass_failed=True) is True
```

- [ ] **Step 5: Implement minimal fallback policy helpers**

Add small pure functions for:
- HyDE eligibility
- broadening retry eligibility
- retry rewrite eligibility

- [ ] **Step 6: Run planner-policy tests to confirm GREEN**

Run: `cd backend; uv run pytest tests/services/test_kb_query_planner_service.py -q`

Expected: PASS with pure-policy coverage.

- [ ] **Step 7: Commit the policy slice**

Run:
- `git add backend/src/app/services/kb_query_policy.py backend/tests/services/test_kb_query_planner_service.py`
- `git commit -m "feat: add KB Chat query planner policy"`

### Task 3: Build the new planner service and prompt

**Files:**
- Create: `backend/src/app/services/kb_query_planner_service.py`
- Create: `backend/src/app/prompts/templates/kb_chat/query_plan.yaml`
- Modify: `backend/src/app/services/query_rewrite_service.py`
- Modify: `backend/tests/services/test_kb_query_planner_service.py`

- [ ] **Step 1: Write a failing unit test for planner output normalization**

```python
@pytest.mark.asyncio
async def test_query_planner_normalizes_prompt_output_into_query_items() -> None:
    planner = KbQueryPlannerService(settings=_settings())
    result = await planner.plan(
        normalized_query="解释agent的记忆系统",
        normalized_meta={"recall_risk": "high", "aliases": ["智能体"]},
    )
    assert result.strategy in {"direct", "paraphrase", "decomposition"}
    assert result.items[0]["kind"] == "main"
    assert all(item["semantic_complete"] is True for item in result.items)
```

- [ ] **Step 2: Run planner-service tests to confirm RED**

Run: `cd backend; uv run pytest tests/services/test_kb_query_planner_service.py -q -k planner`

Expected: FAIL because the planner service and prompt are absent.

- [ ] **Step 3: Create the structured planner prompt**

Prompt requirements:
- emit direct vs paraphrase vs decomposition strategy
- keep constraints intact
- produce only complete retrieval-ready queries
- explain why no expansion is needed when direct strategy is chosen
- declare fallback allowances separately from first-pass items

- [ ] **Step 4: Implement the planner service with fail-open behavior**

Service behavior:
- always seed the canonical main query
- call the structured planner prompt when enabled
- validate planner candidates through `kb_query_policy`
- drop incomplete candidates
- return deterministic fallback result on prompt failure

- [ ] **Step 5: Remove live planner ownership from `query_rewrite_service.py`**

Stop relying on:
- alias derivation from first entity tokens
- mechanical constraint-variant generation
- multi-query/entity-expand orchestration for the live path

- [ ] **Step 6: Run planner-service tests to confirm GREEN**

Run: `cd backend; uv run pytest tests/services/test_kb_query_planner_service.py -q`

Expected: PASS with fail-open planner behavior.

- [ ] **Step 7: Commit the planner service slice**

Run:
- `git add backend/src/app/services/kb_query_planner_service.py backend/src/app/prompts/templates/kb_chat/query_plan.yaml backend/src/app/services/query_rewrite_service.py backend/tests/services/test_kb_query_planner_service.py`
- `git commit -m "feat: add KB Chat query planner service"`

### Task 4: Replace the preprocess enhancement chain with `query_plan`

**Files:**
- Modify: `backend/src/app/agents/preprocess_subgraph.py`
- Modify: `backend/src/app/agents/kb_chat_agentic/preprocess.py`
- Modify: `backend/src/app/agents/kb_chat_agentic_state.py`
- Modify: `backend/src/app/agents/kb_chat_agentic_graph.py`
- Modify: `backend/tests/agents/test_kb_query_planner_contract.py`
- Modify: `backend/tests/agents/test_kb_chat_state_schema.py`

- [ ] **Step 1: Write a failing graph-contract test for the new preprocess path**

Expected live preprocess path:
`merge_context -> resolve_reference -> query_normalize -> query_plan`

- [ ] **Step 2: Run the focused graph-contract test to confirm RED**

Run: `cd backend; uv run pytest tests/agents/test_kb_query_planner_contract.py tests/agents/test_kb_chat_state_schema.py -q -k query_plan`

Expected: FAIL because old enhancement nodes are still registered.

- [ ] **Step 3: Add `query_plan` node implementation in preprocess**

Implementation:
- gather `normalized_query`, `normalized_meta`, retry/failure context
- call `KbQueryPlannerService.plan(...)`
- persist `query_plan_result`, `query_items`, and planner diagnostics
- merge stage summaries with planner statistics and rejection counts

- [ ] **Step 4: Remove retired enhancement nodes from the live preprocess graph**

Delete or stop wiring:
- `complexity_classify`
- `generate_variants_mod`
- `decomposition`
- `generate_variants`
- `entity_expand`
- `hyde`
- `prepare_messages`

- [ ] **Step 5: Remove retired state fields from the live contract**

Update initial state, typed dicts, and schema tests accordingly.

- [ ] **Step 6: Run preprocess and state-schema tests to confirm GREEN**

Run: `cd backend; uv run pytest tests/agents/test_kb_query_planner_contract.py tests/agents/test_kb_chat_state_schema.py tests/agents/test_kb_chat_state_contract.py -q`

Expected: planner node and state contract pass.

- [ ] **Step 7: Commit the preprocess-graph slice**

Run:
- `git add backend/src/app/agents/preprocess_subgraph.py backend/src/app/agents/kb_chat_agentic/preprocess.py backend/src/app/agents/kb_chat_agentic_state.py backend/src/app/agents/kb_chat_agentic_graph.py backend/tests/agents/test_kb_query_planner_contract.py backend/tests/agents/test_kb_chat_state_schema.py backend/tests/agents/test_kb_chat_state_contract.py`
- `git commit -m "refactor: replace KB Chat enhancement chain with query planner"`

### Task 5: Rework retrieval execution around staged fallback

**Files:**
- Modify: `backend/src/app/agents/retrieval_subgraph.py`
- Modify: `backend/src/app/agents/kb_chat_agentic/reflection.py`
- Modify: `backend/tests/agents/test_kb_chat_routing_contract.py`
- Modify: `backend/tests/services/test_kb_query_planner_service.py`

- [ ] **Step 1: Write a failing test for planner-driven first-pass retrieval**

Cover:
- retrieval consumes only planner-approved items
- no retired `message_plan/query_bundle` dependence

- [ ] **Step 2: Run the focused retrieval test to confirm RED**

Run: `cd backend; uv run pytest tests/agents/test_kb_chat_routing_contract.py -q -k retrieval`

Expected: FAIL because retrieval still expects old preparation outputs.

- [ ] **Step 3: Update retrieval budget/planning code to consume planner items**

Implementation:
- derive query count and budget from `query_items`
- remove dependency on retired preparation diagnostics
- keep conservative clamps and fail-open behavior

- [ ] **Step 4: Update retry/reflection path to rebuild planner output**

Implementation:
- retry rewrite regenerates `query_plan_result` and `query_items`
- no old multi-query/decomposition/entity-expand resurrection

- [ ] **Step 5: Implement staged fallback gating**

Behavior:
- first pass uses planner-selected items only
- second pass may enable planner broadening or HyDE based on diagnostics

- [ ] **Step 6: Run routing and planner tests to confirm GREEN**

Run: `cd backend; uv run pytest tests/agents/test_kb_chat_routing_contract.py tests/services/test_kb_query_planner_service.py -q`

Expected: PASS with planner-driven retries and fallback.

- [ ] **Step 7: Commit the retrieval slice**

Run:
- `git add backend/src/app/agents/retrieval_subgraph.py backend/src/app/agents/kb_chat_agentic/reflection.py backend/tests/agents/test_kb_chat_routing_contract.py backend/tests/services/test_kb_query_planner_service.py`
- `git commit -m "refactor: drive KB Chat retrieval from query planner"`

### Task 6: Update trace and frontend contracts

**Files:**
- Modify: `backend/src/app/agents/kb_chat_trace_nodes.py`
- Modify: `backend/src/app/agents/kb_chat_trace_display_contract.py`
- Modify: `frontend/src/services/kbNodeCatalog.ts`
- Modify: `frontend/src/services/kbNodeCatalog.test.ts`
- Modify: `frontend/src/services/kbNodeLabels.ts`
- Modify: `frontend/src/services/kbNodeLabels.test.ts`
- Modify: `frontend/src/services/kbChatTraceNodes.ts`
- Modify: `frontend/src/services/kbChatTraceNodes.test.ts`

- [ ] **Step 1: Add a failing backend trace-display test for planner metadata rendering**

Expected rendered format includes strategy metadata, not only `[variant]`.

- [ ] **Step 2: Add failing frontend tests for node catalog and planner item display assumptions**

Cover:
- `query_plan` label exists
- retired node ids are absent
- planner metadata can be surfaced in timeline/details

- [ ] **Step 3: Run trace/frontend tests to confirm RED**

Run:
- `cd backend; uv run pytest tests/agents/test_kb_chat_trace_nodes.py -q`
- `cd frontend; npx vitest run src/services/kbNodeCatalog.test.ts src/services/kbNodeLabels.test.ts src/services/kbChatTraceNodes.test.ts`

Expected: FAIL on stale node ids and stale `[variant]` assumptions.

- [ ] **Step 4: Update backend node catalog and display builders**

Implement:
- `query_plan` node metadata and ordering
- richer query item formatting including `kind|strategy_source`
- planner summary/rejection diagnostics

- [ ] **Step 5: Update frontend catalog/labels/trace helpers**

Implement:
- new node id and label
- updated phase order
- display support for richer planner item annotations

- [ ] **Step 6: Run backend and frontend trace tests to confirm GREEN**

Run:
- `cd backend; uv run pytest tests/agents/test_kb_chat_trace_nodes.py -q`
- `cd frontend; npx vitest run src/services/kbNodeCatalog.test.ts src/services/kbNodeLabels.test.ts src/services/kbChatTraceNodes.test.ts`

Expected: PASS with synchronized planner contracts.

- [ ] **Step 7: Commit the trace/frontend slice**

Run:
- `git add backend/src/app/agents/kb_chat_trace_nodes.py backend/src/app/agents/kb_chat_trace_display_contract.py frontend/src/services/kbNodeCatalog.ts frontend/src/services/kbNodeCatalog.test.ts frontend/src/services/kbNodeLabels.ts frontend/src/services/kbNodeLabels.test.ts frontend/src/services/kbChatTraceNodes.ts frontend/src/services/kbChatTraceNodes.test.ts`
- `git commit -m "feat: expose KB Chat query planner trace contract"`

### Task 7: Retire obsolete prompts, docs, and full verification

**Files:**
- Modify: `docs/流程图.md`
- Modify: `docs/langgraph_constraints.md`
- Modify: `backend/tests/agents/test_kb_chat_state_schema.py`
- Modify: `backend/tests/agents/test_kb_chat_state_contract.py`

- [ ] **Step 1: Add a failing test or assertion guarding against retired prompt/node references**

Cover that the live path no longer references retired enhancement nodes.

- [ ] **Step 2: Run the docs/contract guard test to confirm RED**

Run: `cd backend; uv run pytest tests/agents/test_kb_chat_state_schema.py tests/agents/test_kb_chat_state_contract.py -q -k retired`

Expected: FAIL while stale references remain.

- [ ] **Step 3: Update docs to match the new live architecture**

Document:
- preprocess path ending in `query_plan`
- planner output contract
- staged fallback retrieval
- retired node ids and rationale

- [ ] **Step 4: Remove or annotate obsolete prompt usage**

Implementation:
- ensure `multi_query/entity_expand/decomposition` are no longer used by live code
- add explicit superseded comments or delete dead wiring in code paths

- [ ] **Step 5: Run backend verification**

Run: `cd backend; uv run pytest tests/agents/test_kb_query_planner_contract.py tests/agents/test_kb_chat_state_schema.py tests/agents/test_kb_chat_state_contract.py tests/agents/test_kb_chat_routing_contract.py tests/agents/test_kb_chat_trace_nodes.py tests/services/test_kb_query_planner_service.py -q`

Expected: PASS.

- [ ] **Step 6: Run lint and frontend verification**

Run:
- `cd backend; uv run ruff check .`
- `cd frontend; npm run typecheck`
- `cd frontend; npx vitest run src/services/kbNodeCatalog.test.ts src/services/kbNodeLabels.test.ts src/services/kbChatTraceNodes.test.ts`

Expected: PASS.

- [ ] **Step 7: Commit docs and cleanup**

Run:
- `git add docs/流程图.md docs/langgraph_constraints.md backend/tests/agents/test_kb_chat_state_schema.py backend/tests/agents/test_kb_chat_state_contract.py`
- `git commit -m "docs: align KB Chat docs with query planner redesign"`

### Task 8: Shadow rollout instrumentation and launch checklist

**Files:**
- Modify: `backend/src/app/agents/kb_chat_agentic/preprocess.py`
- Modify: `backend/src/app/agents/retrieval_subgraph.py`
- Modify: `backend/tests/agents/test_kb_chat_routing_contract.py`

- [ ] **Step 1: Write a failing test for planner shadow metrics**

Cover:
- planner emits selected count and rejection counts
- retrieval can record whether fallback was activated

- [ ] **Step 2: Run the focused instrumentation test to confirm RED**

Run: `cd backend; uv run pytest tests/agents/test_kb_chat_routing_contract.py -q -k shadow`

Expected: FAIL until planner instrumentation is persisted.

- [ ] **Step 3: Persist planner shadow metrics in stage summaries**

Track:
- selected item count
- rejection counts by reason
- fallback activations
- first-pass vs second-pass strategy

- [ ] **Step 4: Add rollout checklist comments or docs for staged enablement**

Checklist should cover:
- shadow-only mode
- gated live enablement
- full cutover prerequisites

- [ ] **Step 5: Run the focused instrumentation test to confirm GREEN**

Run: `cd backend; uv run pytest tests/agents/test_kb_chat_routing_contract.py -q -k shadow`

Expected: PASS.

- [ ] **Step 6: Run final targeted regression bundle**

Run:
- `cd backend; uv run pytest tests/agents/test_kb_query_planner_contract.py tests/agents/test_kb_chat_state_schema.py tests/agents/test_kb_chat_state_contract.py tests/agents/test_kb_chat_routing_contract.py tests/agents/test_kb_chat_trace_nodes.py tests/services/test_kb_query_planner_service.py -q`
- `cd backend; uv run ruff check .`
- `cd frontend; npm run typecheck`
- `cd frontend; npx vitest run src/services/kbNodeCatalog.test.ts src/services/kbNodeLabels.test.ts src/services/kbChatTraceNodes.test.ts`

Expected: PASS.

- [ ] **Step 7: Commit rollout instrumentation**

Run:
- `git add backend/src/app/agents/kb_chat_agentic/preprocess.py backend/src/app/agents/retrieval_subgraph.py backend/tests/agents/test_kb_chat_routing_contract.py`
- `git commit -m "feat: add KB Chat query planner rollout instrumentation"`

---

## Review checklist for the implementing engineer

- [ ] No fragment-only query items can reach live retrieval.
- [ ] No retired enhancement node ids remain in live graph/schema/trace contracts.
- [ ] `query_plan` is the only live query-planning node after normalization.
- [ ] Planner metadata is visible in trace/UI and grep-friendly.
- [ ] Retry and fallback rebuild planner output rather than reviving retired logic.
- [ ] HyDE is controlled by planner/fallback policy rather than always-on preprocessing.
- [ ] Verification commands were run with observed PASS output before claiming completion.

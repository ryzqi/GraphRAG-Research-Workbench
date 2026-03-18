# KB Chat LLM-Driven Query and Review Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace KB Chat heuristic query understanding and rule-only retrieval gating with the approved LLM-driven query understanding/retrieval planning/review flow, while deleting the evidence gate and confidence calibration live contracts.

**Architecture:** Keep the top-level runtime path as `preprocess_subgraph -> retrieval_subgraph -> answer_subgraph`, but rename the requested live nodes to match their new semantics and delete the unwanted gate/finalize nodes entirely. Implement LLM-first, fail-open behavior for reference resolution, retrieval planning, context compression, and factual review; keep downstream contracts stable where they reduce blast radius, and synchronize backend graph/state/trace contracts with frontend schema/catalog/reveal logic and docs.

**Tech Stack:** Python 3.13, FastAPI, LangGraph, LangChain, Pydantic, pytest, React/TypeScript, vitest

---

## File map

### Backend runtime

- Modify: `backend/src/app/agents/preprocess_subgraph.py`
  - owns preprocess node registration, node ids, edge wiring, retry policy for preprocess live nodes
- Modify: `backend/src/app/agents/kb_chat_agentic/preprocess.py`
  - owns `merge_context`, reference resolution, ambiguity check, query normalization, and preprocess stage summaries
- Modify: `backend/src/app/services/query_rewrite_service.py`
  - owns current heuristic `coref_rewrite` and current rule-first `normalize_rewrite`; likely becomes the home for the new LLM reference resolution and updated normalization pipeline
- Modify: `backend/src/app/agents/retrieval_subgraph.py`
  - owns `retrieval_budget_plan`, retrieval subgraph node registration, `context_compress`, and retrieval-stage summaries
- Delete or stop using: `backend/src/app/agents/evidence_gate_subgraph.py`
  - currently owns `doc_gate_sufficiency` and `doc_gate_route`; the new live path removes this subgraph entirely
- Modify: `backend/src/app/agents/kb_chat_agentic/answer_subgraph.py`
  - owns draft generation review fan-out/fuse/repair/commit and factual review truncation behavior
- Modify: `backend/src/app/agents/kb_chat_agentic/reflection.py`
  - owns `generate_draft`, `transform_query_for_retry`, `route_after_answer_review`, and `confidence_calibrate`
- Modify: `backend/src/app/agents/kb_chat_agentic_graph.py`
  - owns top-level node registration, subgraph composition, route-after hooks, graph schema exposure, and parent-level finalize routing
- Modify: `backend/src/app/agents/kb_chat_agentic_state.py`
  - owns live state keys, output state, routing/state schema compatibility, and initial state shape

### Backend observability and service exposure

- Modify: `backend/src/app/agents/kb_chat_trace_nodes.py`
  - owns node catalog metadata, labels, phase, and order used by trace/schema/frontend
- Modify: `backend/src/app/agents/kb_chat_trace_display_contract.py`
  - owns display-oriented node input/output shaping and any node-specific display summaries
- Modify: `backend/src/app/services/kb_chat_service.py`
  - owns graph schema serialization used by frontend graph schema consumers

### Prompts

- Create: `backend/src/app/prompts/templates/kb_chat/resolve_reference.yaml`
- Modify or replace: `backend/src/app/prompts/templates/kb_chat/normalize_query.yaml`
- Create: `backend/src/app/prompts/templates/kb_chat/retrieval_plan.yaml`
- Modify: `backend/src/app/prompts/templates/kb_chat/context_compress.yaml`
- Modify or reuse: `backend/src/app/prompts/templates/kb_chat/answer_review.yaml`

### Frontend

- Modify: `frontend/src/services/chats.ts`
  - owns typed SSE/response contracts that currently still mention `confidence_score` and `confidence_level`
- Modify: `frontend/src/views/KbChatPage.tsx`
  - owns KB Chat page state updates that currently still read `confidence_score` and `confidence_level`
- Modify: `frontend/src/services/kbNodeCatalog.ts`
  - owns node labels, stage ids, order, phase, and default catalog entries
- Modify: `frontend/src/services/kbNodeCatalog.test.ts`
  - guards node id presence/order/phase against backend live contract
- Modify: `frontend/src/services/kbNodeLabels.ts`
  - resolves label fallbacks when schema is absent or partial
- Modify: `frontend/src/services/kbNodeLabels.test.ts`
  - guards renamed and removed labels
- Modify: `frontend/src/services/kbChatAnswerReveal.ts`
  - currently keys off finalize-phase nodes; must be updated after removing `confidence_calibrate`
- Create: `frontend/src/services/kbChatAnswerReveal.test.ts`
  - protects the new terminal reveal logic after finalize-node removal
- Modify: `frontend/src/services/kbChatTraceNodes.ts`
  - if needed, synchronize any frontend-side trace assumptions with backend node ids
- Modify: `frontend/src/services/kbChatTraceNodes.test.ts`
  - protect any trace node assumptions touched by the rename/removal set

### Tests and docs

- Modify: `backend/tests/agents/test_kb_chat_state_schema.py`
- Modify: `backend/tests/agents/test_kb_chat_state_contract.py`
- Modify: `backend/tests/agents/test_kb_chat_routing_contract.py`
- Modify: `backend/tests/agents/test_kb_chat_retry_cache.py`
- Modify: `backend/tests/agents/test_kb_chat_runtime_context.py`
- Modify: `backend/tests/agents/test_kb_chat_trace_nodes.py`
- Modify: `backend/tests/services/test_kb_chat_graph_schema.py`
- Modify: `backend/tests/services/test_kb_chat_service_semantic_cache.py`
- Modify: `backend/tests/services/test_kb_chat_service_state_restore.py`
- Modify: `docs/流程图.md`
- Modify: `docs/langgraph_constraints.md`

---

### Task 1: Plan guardrails and execution scaffolding

**Files:**
- Create: `TASK_TODO_MEDIUM.md`
- Create: `TASK_TODO_FINE.md`
- Modify: `docs/superpowers/plans/2026-03-18-kb-chat-llm-driven-query-and-review-implementation.md`

- [ ] **Step 1: Write the medium todo with scope, non-goals, and verification commands**

Capture the approved boundaries:
- KB Chat only
- no retrieval engine redesign
- no frontend interaction redesign
- evidence gate deleted
- confidence calibration deleted
- fail-open for all new LLM-driven nodes

- [ ] **Step 2: Write the fine todo with task order and stop points**

Break work into backend contract cleanup -> backend node implementation -> frontend alignment -> docs -> verification, so the executor can stop cleanly after any green checkpoint.

- [ ] **Step 3: Add execution notes referencing relevant skills**

Record:
- `@test-driven-development`
- `@verification-before-completion`
- `@systematic-debugging`

- [ ] **Step 4: Re-read the plan header and todo scope before editing code**

Goal: avoid scope drift before the first failing test is written.

- [ ] **Step 5: Commit planning artifacts**

Run:
- `git add TASK_TODO_MEDIUM.md TASK_TODO_FINE.md docs/superpowers/plans/2026-03-18-kb-chat-llm-driven-query-and-review-implementation.md`
- `git commit -m "docs: add KB Chat LLM-driven query/review implementation plan"`

Expected: plan/todo-only commit succeeds.

### Task 2: Write failing tests for the new live contract

**Files:**
- Modify: `backend/tests/agents/test_kb_chat_state_schema.py`
- Modify: `backend/tests/agents/test_kb_chat_state_contract.py`
- Modify: `backend/tests/agents/test_kb_chat_routing_contract.py`
- Modify: `backend/tests/agents/test_kb_chat_retry_cache.py`
- Modify: `backend/tests/agents/test_kb_chat_runtime_context.py`
- Modify: `backend/tests/agents/test_kb_chat_trace_nodes.py`
- Modify: `backend/tests/services/test_kb_chat_graph_schema.py`
- Modify: `backend/tests/services/test_kb_chat_service_semantic_cache.py`
- Modify: `backend/tests/services/test_kb_chat_service_state_restore.py`
- Modify: `frontend/src/services/kbNodeCatalog.test.ts`
- Modify: `frontend/src/services/kbNodeLabels.test.ts`

- [ ] **Step 1: Add backend schema assertions for removed live nodes and fields**

Cover:
- `evidence_gate_subgraph` absent from graph schema
- `doc_gate_sufficiency` absent from graph schema
- `doc_gate_route` absent from graph schema
- `confidence_calibrate` absent from graph schema
- `confidence_score` absent from public output schema
- `confidence_level` absent from public output schema
- `doc_gate_runs` absent from internal live state
- stale service-state expectations for `confidence_score/confidence_level` removed

- [ ] **Step 2: Add backend rename assertions for preprocess/retrieval nodes**

Cover:
- `resolve_reference` present where `coref_rewrite` used to be
- `query_normalize` present where `normalize_rewrite` used to be
- `retrieval_plan` present where `retrieval_budget_plan` used to be
- old ids rejected by negative guards

- [ ] **Step 3: Add routing-contract tests for the new terminal path**

Cover:
- no parent route from answer review to `confidence_calibrate`
- pass path converges at `answer_commit -> END`
- retry path still reaches `transform_query`
- exit path still reaches `force_exit`

- [ ] **Step 4: Add runtime-context tests for fail-open planning behavior**

Cover:
- invalid retrieval plan LLM output falls back to conservative budget
- retrieval plan values are clamped when over limits

- [ ] **Step 5: Add frontend catalog/label tests for renamed and removed nodes**

Cover:
- renamed ids and orders
- removed gate/finalize ids absent
- label fallback resolves new names
- no stale labels for removed node ids

- [ ] **Step 6: Run targeted tests and confirm RED**

Run:
- `cd backend; uv run pytest tests/agents/test_kb_chat_state_schema.py tests/agents/test_kb_chat_state_contract.py tests/agents/test_kb_chat_routing_contract.py tests/agents/test_kb_chat_retry_cache.py tests/agents/test_kb_chat_runtime_context.py tests/agents/test_kb_chat_trace_nodes.py tests/services/test_kb_chat_graph_schema.py tests/services/test_kb_chat_service_semantic_cache.py tests/services/test_kb_chat_service_state_restore.py -q`
- `cd frontend; npx vitest run src/services/kbNodeCatalog.test.ts src/services/kbNodeLabels.test.ts`

Expected:
- failures point to old node ids/old output fields/old routing still being present

- [ ] **Step 7: Commit the red tests**

Run:
- `git add backend/tests/agents/test_kb_chat_state_schema.py backend/tests/agents/test_kb_chat_state_contract.py backend/tests/agents/test_kb_chat_routing_contract.py backend/tests/agents/test_kb_chat_retry_cache.py backend/tests/agents/test_kb_chat_runtime_context.py backend/tests/agents/test_kb_chat_trace_nodes.py backend/tests/services/test_kb_chat_graph_schema.py backend/tests/services/test_kb_chat_service_semantic_cache.py backend/tests/services/test_kb_chat_service_state_restore.py frontend/src/services/kbNodeCatalog.test.ts frontend/src/services/kbNodeLabels.test.ts`
- `git commit -m "test: lock KB Chat LLM-driven live contract"`

Expected: commit contains only failing contract tests.

### Task 3: Replace heuristic coreference with `resolve_reference`

**Files:**
- Modify: `backend/src/app/services/query_rewrite_service.py`
- Modify: `backend/src/app/agents/kb_chat_agentic/preprocess.py`
- Modify: `backend/src/app/agents/preprocess_subgraph.py`
- Modify: `backend/src/app/agents/kb_chat_agentic_state.py`
- Create: `backend/src/app/prompts/templates/kb_chat/resolve_reference.yaml`

- [ ] **Step 1: Add a focused preprocess test for fail-open reference resolution**

Test:
- model failure => returns original query
- structured success => returns `resolved_query`
- old `coref_query/coref_meta` keys are no longer the canonical outputs

- [ ] **Step 2: Run the focused preprocess test and confirm RED**

Run:
- `cd backend; uv run pytest tests/agents/test_kb_chat_state_schema.py -q -k "resolve_reference or coref"`

Expected: fail because `coref_rewrite` is still live.

- [ ] **Step 3: Add structured prompt and service entry point for reference resolution**

Implement:
- prompt template with strict JSON output
- service helper for LLM-only reference resolution
- no reuse of the old heuristic candidate scoring path as fallback logic

- [ ] **Step 4: Rename preprocess node registration and state outputs**

Implement:
- `coref_rewrite` node id -> `resolve_reference`
- `coref_query` -> `resolved_query`
- `coref_meta` -> `reference_resolution_meta`
- `stage_summaries.coref_rewrite` -> `stage_summaries.resolve_reference`

- [ ] **Step 5: Remove heuristic-only helper usage from the live path**

Delete or stop calling:
- old heuristic candidate scoring
- marker replacement/prefix fallback logic from the runtime path

- [ ] **Step 6: Run focused backend tests and confirm GREEN**

Run:
- `cd backend; uv run pytest tests/agents/test_kb_chat_state_schema.py tests/agents/test_kb_chat_trace_nodes.py -q -k "resolve_reference or preprocess"`

Expected: renamed node and fail-open behavior pass.

- [ ] **Step 7: Commit the reference-resolution slice**

Run:
- `git add backend/src/app/services/query_rewrite_service.py backend/src/app/agents/kb_chat_agentic/preprocess.py backend/src/app/agents/preprocess_subgraph.py backend/src/app/agents/kb_chat_agentic_state.py backend/src/app/prompts/templates/kb_chat/resolve_reference.yaml backend/tests/agents/test_kb_chat_state_schema.py backend/tests/agents/test_kb_chat_trace_nodes.py`
- `git commit -m "feat: make KB Chat reference resolution LLM-driven"`

### Task 4: Rename and harden `query_normalize` as rule-first then LLM

**Files:**
- Modify: `backend/src/app/services/query_rewrite_service.py`
- Modify: `backend/src/app/agents/kb_chat_agentic/preprocess.py`
- Modify: `backend/src/app/agents/preprocess_subgraph.py`
- Modify: `backend/src/app/agents/kb_chat_agentic_state.py`
- Modify: `backend/src/app/prompts/templates/kb_chat/normalize_query.yaml`

- [ ] **Step 1: Add tests that lock constraint preservation**

Cover:
- numbers preserved
- time ranges preserved
- comparison targets preserved
- negation/exceptions preserved
- LLM failure falls back to rule output

- [ ] **Step 2: Run targeted normalization tests and confirm RED**

Run:
- `cd backend; uv run pytest tests/agents/test_kb_chat_state_schema.py -q -k "normalize or constraint"`

Expected: fail because old node id/old summary key or missing invariants are still in place.

- [ ] **Step 3: Rename the live node and summary keys**

Implement:
- `normalize_rewrite` -> `query_normalize`
- `stage_summaries.normalize_rewrite` -> `stage_summaries.query_normalize`

- [ ] **Step 4: Update prompt and runtime metadata to emphasize conservative normalization**

Implement:
- stricter prompt language against widening scope
- explicit preservation of numeric/temporal/scope constraints
- `decision_source`, `fallback_used`, `fallback_reason` in summary/meta

- [ ] **Step 5: Run focused backend tests and confirm GREEN**

Run:
- `cd backend; uv run pytest tests/agents/test_kb_chat_state_schema.py tests/agents/test_kb_chat_routing_contract.py -q -k "query_normalize or normalize"`

Expected: renamed normalization node and rule-first fallback behavior pass.

- [ ] **Step 6: Commit the normalization slice**

Run:
- `git add backend/src/app/services/query_rewrite_service.py backend/src/app/agents/kb_chat_agentic/preprocess.py backend/src/app/agents/preprocess_subgraph.py backend/src/app/agents/kb_chat_agentic_state.py backend/src/app/prompts/templates/kb_chat/normalize_query.yaml backend/tests/agents/test_kb_chat_state_schema.py backend/tests/agents/test_kb_chat_routing_contract.py`
- `git commit -m "feat: make KB Chat query normalization rule-first plus LLM"`

### Task 5: Replace `retrieval_budget_plan` with LLM `retrieval_plan`

**Files:**
- Modify: `backend/src/app/agents/retrieval_subgraph.py`
- Modify: `backend/src/app/agents/kb_chat_agentic_state.py`
- Modify: `backend/src/app/agents/kb_chat_trace_nodes.py`
- Create: `backend/src/app/prompts/templates/kb_chat/retrieval_plan.yaml`
- Modify: `backend/tests/agents/test_kb_chat_runtime_context.py`
- Modify: `backend/tests/services/test_kb_chat_graph_schema.py`

- [ ] **Step 1: Add a focused test for planner clamp and fallback**

Cover:
- over-limit values are clamped to settings
- invalid structured output falls back to conservative budget
- summary records `decision_source` and fallback markers

- [ ] **Step 2: Run the focused planner test and confirm RED**

Run:
- `cd backend; uv run pytest tests/agents/test_kb_chat_runtime_context.py -q -k "retrieval_plan or budget"`

Expected: fail because the planner is still deterministic and old node id is still present.

- [ ] **Step 3: Implement structured LLM planner while keeping `retrieval_budget` stable**

Implement:
- new prompt
- LLM-first planner call
- clamp logic after parse
- fallback to current conservative formula

- [ ] **Step 4: Rename node registration and trace metadata**

Implement:
- `retrieval_budget_plan` -> `retrieval_plan`
- `stage_summaries.retrieval_budget_plan` -> `stage_summaries.retrieval_plan`
- keep downstream `retrieval_budget` object name unchanged

- [ ] **Step 5: Run focused backend tests and confirm GREEN**

Run:
- `cd backend; uv run pytest tests/agents/test_kb_chat_runtime_context.py tests/services/test_kb_chat_graph_schema.py -q -k "retrieval_plan or budget"`

Expected: planner behavior and renamed graph contract pass.

- [ ] **Step 6: Commit the retrieval-planner slice**

Run:
- `git add backend/src/app/agents/retrieval_subgraph.py backend/src/app/agents/kb_chat_agentic_state.py backend/src/app/agents/kb_chat_trace_nodes.py backend/src/app/prompts/templates/kb_chat/retrieval_plan.yaml backend/tests/agents/test_kb_chat_runtime_context.py backend/tests/services/test_kb_chat_graph_schema.py`
- `git commit -m "feat: make KB Chat retrieval planning LLM-driven"`

### Task 6: Strengthen `context_compress` prompt and fail-open checks

**Files:**
- Modify: `backend/src/app/agents/retrieval_subgraph.py`
- Modify: `backend/src/app/prompts/templates/kb_chat/context_compress.yaml`
- Modify: `backend/tests/agents/test_kb_chat_runtime_context.py`

- [ ] **Step 1: Add tests for evidence-preserving compression fallback**

Cover:
- empty compression output => original context
- non-compacting output => original context
- missing citation labels => original context
- summary records fallback reason

- [ ] **Step 2: Run focused compression tests and confirm RED**

Run:
- `cd backend; uv run pytest tests/agents/test_kb_chat_runtime_context.py -q -k "context_compress or compress"`

Expected: fail because current prompt/guardrails do not cover the new invariants.

- [ ] **Step 3: Update prompt with explicit preservation rules**

Add explicit preservation of:
- citation tags
- numbers/thresholds
- time conditions
- exceptions/limitations
- comparison baselines
- causal/prerequisite relations

- [ ] **Step 4: Add the new suspicious-output fallback checks**

Implement the minimum checks needed for safe fail-open without overengineering semantic diff logic.

- [ ] **Step 5: Run focused backend tests and confirm GREEN**

Run:
- `cd backend; uv run pytest tests/agents/test_kb_chat_runtime_context.py -q -k "context_compress or compress"`

Expected: new prompt contract and fallback checks pass.

- [ ] **Step 6: Commit the compression slice**

Run:
- `git add backend/src/app/agents/retrieval_subgraph.py backend/src/app/prompts/templates/kb_chat/context_compress.yaml backend/tests/agents/test_kb_chat_runtime_context.py`
- `git commit -m "feat: harden KB Chat context compression prompt"`

### Task 7: Delete evidence gate and remove `confidence_calibrate`

**Files:**
- Modify: `backend/src/app/agents/kb_chat_agentic_graph.py`
- Modify: `backend/src/app/agents/kb_chat_agentic/reflection.py`
- Modify: `backend/src/app/agents/kb_chat_agentic_state.py`
- Modify: `backend/src/app/agents/kb_chat_trace_nodes.py`
- Modify: `backend/src/app/agents/kb_chat_trace_display_contract.py`
- Modify: `backend/src/app/services/kb_chat_service.py`
- Delete or stop importing: `backend/src/app/agents/evidence_gate_subgraph.py`
- Modify: `backend/tests/agents/test_kb_chat_retry_cache.py`
- Modify: `backend/tests/agents/test_kb_chat_state_contract.py`
- Modify: `backend/tests/agents/test_kb_chat_routing_contract.py`
- Modify: `backend/tests/services/test_kb_chat_graph_schema.py`
- Modify: `backend/tests/services/test_kb_chat_service_semantic_cache.py`
- Modify: `backend/tests/services/test_kb_chat_service_state_restore.py`

- [ ] **Step 1: Add focused tests for gate/finalize removal**

Cover:
- no `build_evidence_gate_subgraph` in live graph
- no `route_after_doc_grader` in parent graph
- no `confidence_calibrate` route target after answer review
- no public output confidence fields

- [ ] **Step 2: Run the focused removal tests and confirm RED**

Run:
- `cd backend; uv run pytest tests/agents/test_kb_chat_state_contract.py tests/agents/test_kb_chat_routing_contract.py tests/agents/test_kb_chat_retry_cache.py tests/services/test_kb_chat_graph_schema.py tests/services/test_kb_chat_service_semantic_cache.py tests/services/test_kb_chat_service_state_restore.py -q -k "doc_gate or confidence or finalize or evidence_gate"`

Expected: fail because old subgraph and finalize node still exist.

- [ ] **Step 3: Remove evidence gate wiring from the parent graph**

Implement:
- delete evidence gate node registration/imports
- connect retrieval subgraph directly to answer subgraph or the new retry path
- remove `route_after_doc_grader` live usage

- [ ] **Step 4: Remove confidence calibration from state, routing, and service output**

Implement:
- remove `confidence_score`
- remove `confidence_level`
- remove confidence summary generation
- remove any service/schema exposure that still emits them

- [ ] **Step 5: Update trace metadata/display contracts for the removed nodes**

Remove:
- `evidence_gate_subgraph`
- `doc_gate_sufficiency`
- `doc_gate_route`
- `confidence_calibrate`

- [ ] **Step 6: Run focused backend tests and confirm GREEN**

Run:
- `cd backend; uv run pytest tests/agents/test_kb_chat_state_contract.py tests/agents/test_kb_chat_routing_contract.py tests/agents/test_kb_chat_retry_cache.py tests/services/test_kb_chat_graph_schema.py tests/services/test_kb_chat_service_semantic_cache.py tests/services/test_kb_chat_service_state_restore.py tests/agents/test_kb_chat_trace_nodes.py -q`

Expected: old gate/finalize live contracts are gone.

- [ ] **Step 7: Commit the contract-removal slice**

Run:
- `git add backend/src/app/agents/kb_chat_agentic_graph.py backend/src/app/agents/kb_chat_agentic/reflection.py backend/src/app/agents/kb_chat_agentic_state.py backend/src/app/agents/kb_chat_trace_nodes.py backend/src/app/agents/kb_chat_trace_display_contract.py backend/src/app/services/kb_chat_service.py backend/tests/agents/test_kb_chat_state_contract.py backend/tests/agents/test_kb_chat_routing_contract.py backend/tests/agents/test_kb_chat_retry_cache.py backend/tests/services/test_kb_chat_graph_schema.py backend/tests/services/test_kb_chat_service_semantic_cache.py backend/tests/services/test_kb_chat_service_state_restore.py backend/tests/agents/test_kb_chat_trace_nodes.py`
- `git commit -m "refactor: remove KB Chat evidence gate and confidence calibration"`

### Task 8: Update draft generation and full-context factual review

**Files:**
- Modify: `backend/src/app/agents/kb_chat_agentic/reflection.py`
- Modify: `backend/src/app/agents/kb_chat_agentic/answer_subgraph.py`
- Modify: `backend/tests/agents/test_kb_chat_state_schema.py`
- Modify: `backend/tests/agents/test_kb_chat_state_contract.py`

- [ ] **Step 1: Add failing tests for unlimited draft generation and untruncated factual review**

Cover:
- `generate_draft` no longer binds `max_tokens=1024`
- `_answer_review_llm_check(...)` passes full `final_context`
- `_answer_review_llm_check(...)` passes full `draft_answer`

- [ ] **Step 2: Run focused answer-generation/review tests and confirm RED**

Run:
- `cd backend; uv run pytest tests/agents/test_kb_chat_state_schema.py tests/agents/test_kb_chat_state_contract.py -q -k "draft_generate or answer_review_factual or factual"`

Expected: fail because current code still binds max tokens and truncates review input.

- [ ] **Step 3: Remove `max_tokens` binding from draft generation**

Implement:
- call the chat model without passing `max_tokens=1024`
- keep existing generation fail-open/refusal behavior

- [ ] **Step 4: Remove truncation from factual review input construction**

Implement:
- remove `final_context[:4000]`
- remove `draft[:2000]`
- preserve existing fallback-open behavior for review failures

- [ ] **Step 5: Run focused backend tests and confirm GREEN**

Run:
- `cd backend; uv run pytest tests/agents/test_kb_chat_state_schema.py tests/agents/test_kb_chat_state_contract.py -q -k "draft_generate or answer_review_factual or factual"`

Expected: answer generation and full-review behavior pass.

- [ ] **Step 6: Commit the answer-generation/review slice**

Run:
- `git add backend/src/app/agents/kb_chat_agentic/reflection.py backend/src/app/agents/kb_chat_agentic/answer_subgraph.py backend/tests/agents/test_kb_chat_state_schema.py backend/tests/agents/test_kb_chat_state_contract.py`
- `git commit -m "feat: remove KB Chat draft limit and factual review truncation"`

### Task 9: Align frontend catalog, labels, and answer reveal behavior

**Files:**
- Modify: `frontend/src/services/chats.ts`
- Modify: `frontend/src/views/KbChatPage.tsx`
- Modify: `frontend/src/services/kbNodeCatalog.ts`
- Modify: `frontend/src/services/kbNodeCatalog.test.ts`
- Modify: `frontend/src/services/kbNodeLabels.ts`
- Modify: `frontend/src/services/kbNodeLabels.test.ts`
- Modify: `frontend/src/services/kbChatAnswerReveal.ts`
- Create: `frontend/src/services/kbChatAnswerReveal.test.ts`
- Modify: `frontend/src/services/kbChatTraceNodes.ts`
- Modify: `frontend/src/services/kbChatTraceNodes.test.ts`

- [ ] **Step 1: Update frontend node catalog for renamed and removed nodes**

Implement:
- `coref_rewrite` -> `resolve_reference`
- `normalize_rewrite` -> `query_normalize`
- `retrieval_budget_plan` -> `retrieval_plan`
- remove `evidence_gate_subgraph`
- remove `doc_gate_sufficiency`
- remove `doc_gate_route`
- remove `confidence_calibrate`
- compact stage/order layout without inventing extra placeholder nodes

- [ ] **Step 2: Update label fallbacks and trace assumptions**

Implement:
- new labels for renamed nodes
- no stale fallbacks for removed nodes
- any frontend-side trace node list updated to the new live contract

- [ ] **Step 3: Update answer reveal final-node logic**

Implement:
- stop relying on `confidence_calibrate` as the terminal finalize signal
- use the new terminal node set derived from graph schema after finalize-node removal

- [ ] **Step 4: Remove stale confidence fields from frontend types and page state**

Implement:
- remove `confidence_score` and `confidence_level` from KB Chat service types if they are no longer emitted
- stop reading these fields in `KbChatPage.tsx`
- keep the page resilient if historical responses still include them

- [ ] **Step 5: Run targeted frontend tests and confirm GREEN**

Run:
- `cd frontend; npx vitest run src/services/kbNodeCatalog.test.ts src/services/kbNodeLabels.test.ts src/services/kbChatAnswerReveal.test.ts src/services/kbChatTraceNodes.test.ts`

Expected: renamed/removed nodes and new answer-reveal behavior pass.

- [ ] **Step 6: Commit the frontend-alignment slice**

Run:
- `git add frontend/src/services/chats.ts frontend/src/views/KbChatPage.tsx frontend/src/services/kbNodeCatalog.ts frontend/src/services/kbNodeCatalog.test.ts frontend/src/services/kbNodeLabels.ts frontend/src/services/kbNodeLabels.test.ts frontend/src/services/kbChatAnswerReveal.ts frontend/src/services/kbChatAnswerReveal.test.ts frontend/src/services/kbChatTraceNodes.ts frontend/src/services/kbChatTraceNodes.test.ts`
- `git commit -m "feat: align KB Chat frontend catalog with new live contract"`

### Task 10: Update docs and run full verification

**Files:**
- Modify: `docs/流程图.md`
- Modify: `docs/langgraph_constraints.md`
- Modify: `docs/superpowers/specs/2026-03-18-kb-chat-llm-driven-query-and-review-design.md`

- [ ] **Step 1: Update docs/流程图.md to the new live path and node names**

Replace all live mentions of:
- `coref_rewrite`
- `normalize_rewrite`
- `retrieval_budget_plan`
- `evidence_gate_subgraph`
- `doc_gate_sufficiency`
- `doc_gate_route`
- `confidence_calibrate`

with the new approved architecture and terminal path.

- [ ] **Step 2: Update docs/langgraph_constraints.md to the new graph contract**

Document:
- no evidence gate live path
- no confidence calibration live path
- new preprocess/retrieval node ids
- new terminal convergence behavior

- [ ] **Step 3: Re-read the spec and trim any wording that no longer matches implementation decisions**

Only update the spec if implementation changed any approved naming or state decisions.

- [ ] **Step 4: Run the full backend verification suite for the touched KB Chat contract**

Run:
- `cd backend; uv run pytest tests/agents/test_kb_chat_state_schema.py tests/agents/test_kb_chat_state_contract.py tests/agents/test_kb_chat_routing_contract.py tests/agents/test_kb_chat_retry_cache.py tests/agents/test_kb_chat_runtime_context.py tests/agents/test_kb_chat_trace_nodes.py tests/services/test_kb_chat_graph_schema.py tests/services/test_kb_chat_service_semantic_cache.py tests/services/test_kb_chat_service_state_restore.py -q`
- `cd backend; uv run ruff check .`

Expected: all targeted backend tests and lint pass.

- [ ] **Step 5: Run the full frontend verification suite for the touched KB Chat contract**

Run:
- `cd frontend; npm run typecheck`
- `cd frontend; npx vitest run src/services/kbNodeCatalog.test.ts src/services/kbNodeLabels.test.ts src/services/kbChatAnswerReveal.test.ts src/services/kbChatTraceNodes.test.ts`

Expected: typecheck and targeted vitest suite pass.

- [ ] **Step 6: Run a final git diff review before completion**

Confirm:
- no stray references to removed node ids in runtime code
- no stale docs for removed gate/finalize nodes
- no accidental unrelated refactors

- [ ] **Step 7: Commit docs and final verification state**

Run:
- `git add docs/流程图.md docs/langgraph_constraints.md docs/superpowers/specs/2026-03-18-kb-chat-llm-driven-query-and-review-design.md`
- `git commit -m "docs: align KB Chat docs with LLM-driven live contract"`

- [ ] **Step 8: Prepare execution handoff summary**

Record:
- exact tests run
- exact files changed
- any skipped live validation
- any follow-up risks left for a later slice

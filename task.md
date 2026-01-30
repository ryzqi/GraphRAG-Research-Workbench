# Tasks (KB Agent UX & Correctness)

Date: 2026-01-30

## Goal
Fix KB chat evidence alignment, unify embedding inputs between ingestion and index rebuild, and align KB/Chat UX with user expectations.

## How To Verify
- Backend tests: `cd backend; uv run pytest` (or `backend/.venv/Scripts/python.exe -m pytest`)
- Backend lint: `cd backend; uv run ruff check .` (or `backend/.venv/Scripts/ruff.exe check .`)
- Frontend typecheck/build: `cd frontend; npx tsc -p tsconfig.json --noEmit; npm run build`

## Task 1 - KB Chat Evidence Alignment
- [x] Backend: ensure returned `evidence[]` order matches the latest retrieval context numbering (`[1]...[n]`).
- [x] Backend: stop accumulating evidence across retrieval retries (transform_query loops).
- [x] Tests: add regression coverage for multi-retrieval flows to prevent citation/evidence mismatch.
- [x] (Optional) Evidence excerpt should match what the model saw when parent/child strategy uses `context_text`.

Acceptance criteria:
- When the agent performs multiple retrieval attempts, answer citations like `[1]` always refer to `evidence[0]` in the UI.
- No evidence numbering mismatch after retries.
- All existing tests pass.

Likely touch points:
- `backend/src/app/services/kb_chat_service.py`
- `backend/src/app/agents/tools/kb_retrieve.py`
- `backend/src/app/services/context_builder.py`
- `frontend/src/components/EvidenceList.tsx`

## Task 2 - index_rebuild vs ingestion Embedding Input Consistency
- [x] Extract shared helper for building embedding inputs (parent/child prefix + heading_path injection + contextual context).
- [x] Apply helper in both ingestion and index rebuild tasks.
- [x] Tests: cover heading_path injection in the shared path (and ensure index_rebuild uses it).

Acceptance criteria:
- For the same chunk items/contexts, ingestion and index_rebuild build identical embedding input strings.
- Tests cover heading_path injection behavior.
- All existing tests pass.

Likely touch points:
- `backend/src/app/worker/tasks/ingestion.py`
- `backend/src/app/worker/tasks/index_rebuild.py`
- `backend/tests/*`

## Task 3 - UX Alignment

### 3a - Archived KB Listing
- [x] Backend: `/api/v1/knowledge-bases` supports `status=active|archived|all` (default keeps current behavior).
- [x] Frontend: KnowledgeBasesPage can actually show archived KBs (fetch `all` and filter locally, or pass the status param).
- [x] Keep KB selector for KB chat showing only active KBs.

Acceptance criteria:
- Archived filter in UI works and matches backend data.
- No breaking changes for existing callers (default still returns active only).

Likely touch points:
- `backend/src/app/api/v1/endpoints/knowledge_bases.py`
- `backend/src/app/services/knowledge_base_service.py`
- `frontend/src/services/knowledgeBases.ts`
- `frontend/src/hooks/queries/useKnowledgeBases.ts`
- `frontend/src/pages/KnowledgeBasesPage.tsx`
- `frontend/src/pages/KbChatPage.tsx`

### 3b - Chat Reload Behavior
- [x] Frontend: stop auto-creating a new session on browser reload; reload should keep the same `sessionId` and load history when possible.
- [x] If the `sessionId` is stale/deleted (404), clear it and guide the user to start a new chat (KB chat requires selecting KBs).

Acceptance criteria:
- Reload does not silently start a new session and wipe history.
- Stale session handling remains graceful.

Likely touch points:
- `frontend/src/pages/KbChatPage.tsx`
- `frontend/src/pages/GeneralChatPage.tsx`

## Progress Log
- 2026-01-29: Created this task tracker.
- 2026-01-29: Completed Task 1 (backend + tests).
- 2026-01-29: Completed Task 2 (shared embedding input helper + refactor ingestion/index_rebuild + tests).
- 2026-01-29: Completed Task 3 (archived KB listing + chat reload UX fixes).


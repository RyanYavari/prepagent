# Spec: RAG Retrieval Node

Source of truth: `ARCHITECTURE_DECISIONS.md` §3 (RAG Retrieval Design), §1 (fixed DAG), §6 (guardrails).

## Problem
Resume chunks are embedded and stored in `resume_embeddings`, but nothing reads them. `backend/agents/rag.py` is empty, so the synthesis step has no way to obtain the user's resume context or prior briefings for the same company. (CLAUDE.md's "Next Task" still lists Day 5 dashboard polish, which is already committed; this is the next unbuilt item.)

## Goal
A `rag_retrieval` node (fixed-DAG step after company/interviewer research, before synthesis) that returns, for a given user and target company, all of the user's resume chunks plus only that user's prior briefing chunks for the same company.

## Non-goals
- No Cohere Rerank (ADR §3: dropped; corpus <100 vectors per user).
- No vector-similarity query, similarity threshold, or query embedding. ADR §3: "This is a SQL filter, not a vector similarity problem. Don't over-engineer it."
- No writing/embedding of briefing chunks (that happens post-synthesis, a later slice). This slice only adds the columns and reads them.
- No LangGraph `StateGraph` wiring, no company/interviewer/synthesis nodes, no HTTP endpoint. The node is a plain function with LangGraph node signature (state dict in, partial state dict out) so it can be registered later.
- No Tavily or other external calls.

## Design
- Migration `003_retrieval_metadata.sql`: add nullable `company TEXT`, `role TEXT` to `resume_embeddings`, plus index on `(user_id, doc_type, lower(company))`. Resume rows leave them NULL.
- `models/retrieval.py`: `RetrievedChunk` (`doc_type`, `section`, `content`, `company`, `role`, `created_at`) and `RetrievalResult` (`resume_chunks`, `briefing_chunks`).
- `services/retrieval.py`: `retrieve_user_context(user_id, company) -> RetrievalResult`. Two Supabase queries, both always filtered on `user_id`:
  1. `doc_type = 'resume'`
  2. `doc_type = 'briefing'` and `company` equal to target, case-insensitive (`ilike` with wildcard characters escaped), newest first.
  The `embedding` column is never selected.
- `agents/rag.py`: `rag_retrieval_node(state)`. Reads `user_id` and `company` from state (identity comes from the JWT upstream, never from the request body). Returns `{"retrieved_context": RetrievalResult-as-dict, "warnings": [...]}`.

## Acceptance Criteria

### Scenario 1: Resume and same-company briefings exist
- **Given** a user with 3 resume chunks and briefing chunks for "Stripe" and "Acme"
- **When** retrieval runs for company "Stripe"
- **Then** all 3 resume chunks and only the "Stripe" briefing chunks are returned; no "Acme" chunk appears.

### Scenario 2: Cross-user isolation
- **Given** two users with resume and briefing chunks
- **When** retrieval runs for user A
- **Then** both queries are filtered by `user_id = A`, and no row belonging to user B can be returned.

### Scenario 3: Company match is case-insensitive and literal
- **Given** stored briefing chunks with company "Stripe"
- **When** retrieval runs for "stripe" or " STRIPE "
- **Then** the chunks match. A company containing `%` or `_` (e.g. "100%_Co") is matched literally and does not act as a wildcard.

### Scenario 4: No resume on file
- **Given** a user with no resume chunks
- **When** the node runs
- **Then** it returns an empty `resume_chunks` list, does not raise, and adds a warning "No resume on file; talking points will not reference your background."

### Scenario 5: No prior briefings for company
- **Given** a user with resume chunks but no briefings for the company
- **When** the node runs
- **Then** `briefing_chunks` is empty, no warning is added (this is the normal first-time case).

### Scenario 6: Missing inputs
- **Given** state without `user_id` or with a blank `company`
- **When** the node runs
- **Then** it raises `ValueError` (programmer error upstream; fail loudly rather than query unscoped).

### Scenario 7: Database failure
- **Given** Supabase raises an exception
- **When** the node runs
- **Then** the exception propagates (no silent empty result that would look like "no resume" and produce a misleading briefing).

### Scenario 8: Embedding vectors not leaked
- **Given** any retrieval
- **When** results are returned
- **Then** `embedding` is not selected from the DB nor present on returned objects.

## Affected Files
- `supabase/migrations/003_retrieval_metadata.sql` (new)
- `supabase/README.md` (list migration)
- `backend/models/retrieval.py` (new)
- `backend/services/retrieval.py` (new)
- `backend/agents/rag.py` (implement)
- `backend/tests/test_retrieval.py` (new)
- `backend/tests/test_rag_node.py` (new)
- `CLAUDE.md` (update Current State / Next Task)

## Dependencies
- Migration 003 must be applied to Supabase before briefing-chunk retrieval works in a real environment (unit tests mock Supabase).
- `SUPABASE_URL`, `SUPABASE_SERVICE_KEY` (already used by embeddings service).

## Open Questions
- Fuzzy company matching ("Stripe" vs "Stripe, Inc.") is not handled; exact case-insensitive only. ADR §3 allows a high-threshold semantic fallback; deferred until it proves a problem.
- Should the briefing-chunk writer (post-synthesis) normalize company names before storing? Decide when that slice is specced.

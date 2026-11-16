# Spec: Briefing Chunk Writer

## Problem
Retrieval (`services/retrieval.py`) already reads `doc_type = 'briefing'` chunks for the same company, but nothing ever writes them, so prior-briefing context is always empty.

## Goal
After a briefing completes, its four sections are chunked, embedded and stored in `resume_embeddings` with `doc_type='briefing'` plus company/role metadata, without ever affecting the briefing's own status (ARCHITECTURE_DECISIONS.md §3).

## Non-goals
- No similarity search, rerank or retrieval changes (ADR §3: SQL filter only).
- No backfill of briefings completed before this ships.
- No re-embedding when a briefing is edited (briefings are immutable once complete).
- No new graph node: this runs in `run_pipeline` after persistence, not in the DAG (ADR §1).

## Design
- One chunk per output section, from the stored `BriefingSections`: `company_overview`, `interviewer_profile`, `role_insights`, `talking_points`. `warnings` is not embedded. Section content is rendered to plain text (labelled lines per field, citation tags kept). Sections that render empty are skipped.
- Row: `user_id`, `doc_type='briefing'`, `section`, `content`, `embedding`, `company`, `role`, `briefing_id`. `created_at` defaults to now.
- New column `briefing_id UUID REFERENCES briefings(id) ON DELETE CASCADE` (migration 006) so a write is idempotent (delete existing chunks for the briefing id, then insert) and chunks disappear with their briefing.
- Runs only after the row is marked `complete`. Any failure (OpenAI, Supabase) is logged and swallowed; the briefing stays `complete`.
- Identity: `user_id` is the JWT user id already passed to `run_pipeline`; all deletes/inserts are scoped by `user_id`.

## Acceptance Criteria

### Scenario 1: Happy path
- **Given** a pipeline run that completes with all four sections populated
- **When** `run_pipeline` finishes
- **Then** four rows are stored with `doc_type='briefing'`, the section names above, the briefing's company and role, its `briefing_id` and the user's id, and each has a 1536-dim embedding

### Scenario 2: Retrieval round trip
- **Given** chunks written for a Stripe briefing
- **When** `retrieve_user_context(user, "stripe")` runs
- **Then** the briefing chunks are returned (company match is case-insensitive), and a different company or user does not see them

### Scenario 3: Empty sections skipped
- **Given** a briefing whose interviewer profile is empty (no interviewer)
- **When** chunks are written
- **Then** no `interviewer_profile` chunk is stored and the others are

### Scenario 4: Nothing to embed
- **Given** a briefing with every section empty
- **When** chunks are written
- **Then** no embedding call or insert happens

### Scenario 5: Embedding failure does not fail the briefing
- **Given** `embed_text` raises (OpenAI outage or missing key)
- **When** `run_pipeline` finishes synthesis
- **Then** the briefing is `complete` with content saved, the error is logged, and `run_pipeline` does not raise

### Scenario 6: Storage failure does not fail the briefing
- **Given** the chunk insert raises
- **When** `run_pipeline` finishes
- **Then** same as scenario 5

### Scenario 7: Failed pipeline writes nothing
- **Given** the graph raises
- **When** `run_pipeline` handles it
- **Then** the briefing is `failed` and no chunk writer call is made

### Scenario 8: Idempotent
- **Given** chunks already exist for a `briefing_id`
- **When** the writer runs again for it
- **Then** the old rows are deleted first (scoped by user_id and briefing_id), so the briefing has exactly its current chunks

### Scenario 9: Warnings and metadata
- **Given** `content.warnings` is non-empty
- **When** chunks are written
- **Then** warning text appears in no chunk; a `None` role is stored as NULL

## Affected Files
- `supabase/migrations/006_briefing_chunk_link.sql` (new), `supabase/README.md`
- `backend/services/briefing_chunks.py` (new: `render_sections`, `write_briefing_chunks`)
- `backend/agents/pipeline.py` (call writer after `complete`, errors swallowed)
- `backend/tests/test_briefing_chunks.py` (new), `backend/tests/test_pipeline.py`
- `CLAUDE.md` (Current State / Next Task)

## Dependencies
- Migrations 002, 003 applied; **006 must be applied to Supabase**
- `OPENAI_API_KEY`, `SUPABASE_*` env vars (already required)

## Open Questions
- Prior briefing text is derived from web results and is fed back into synthesis; synthesis already wraps `prior_briefings` as untrusted data, so no change is planned. Confirm during review.
- Calendar-created briefings use the same `run_pipeline`, so they are covered; no separate hook.

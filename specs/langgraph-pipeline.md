# Spec: LangGraph Pipeline Wiring and Trigger

Source of truth: `ARCHITECTURE_DECISIONS.md` §1 (fixed DAG: company + interviewer in parallel, then RAG, then synthesis; no supervisor; LangGraph `StateGraph` kept for state management and LangSmith tracing), §3 (retrieval scoped by `user_id`), §6 (guardrail 2: low-result warnings must reach the user).

## Problem
The four nodes (`company_research_node`, `interviewer_research_node`, `rag_retrieval_node`, `synthesis_node`) exist but are not connected, and `POST /briefings` only inserts a `pending` row (`routers/research.py` has `# TODO: Kick off LangGraph pipeline`). Briefings never get content, and node warnings have nowhere to be stored.

## Goal
`POST /briefings` returns immediately with a `pending` briefing and runs a fixed-DAG `StateGraph` in the background that moves the row `pending → running → complete` with `content` persisted (or `→ failed` on error), readable via the existing `GET /briefings/{id}`.

## Non-goals
- No supervisor, no conditional edges, no retries at graph level (retry lives inside nodes, ADR §1).
- No briefing chunk writer (embedding finished briefings) and no RAGAS.
- No frontend briefing viewer or polling UI.
- No external job queue; FastAPI `BackgroundTasks` only. A server crash mid-run leaves the row `running` (recovery is out of scope).
- No hard 90s timeout or cancellation.
- No new DB migration: `briefings.status` and `briefings.content` are already used by the router.
- No persisted error message column; failures are logged server-side only.

## Design
- **`agents/state.py`**: `PipelineState` TypedDict: `user_id`, `company`, `interviewer`, `role`, `company_research`, `interviewer_research`, `retrieved_context`, `briefing_content`, `warnings`. `warnings` has a merge reducer (append items from the update not already present, order preserved) because the two parallel branches each return the full warnings list they were given.
- **`agents/pipeline.py`**: `build_graph()` returns a compiled `StateGraph`: `START → company_research`, `START → interviewer_research`, both `→ rag_retrieval → synthesis → END`. Fixed edges only. `run_pipeline(briefing_id, user_id, company, interviewer, role)`:
  1. set row status `running`;
  2. `graph.invoke(initial_state, config={run_name, tags, metadata={briefing_id}})` (LangSmith traces via env vars, no code needed);
  3. on success, persist `content` = `BriefingSections` dict (with `warnings`) and status `complete`;
  4. on any exception, log it and set status `failed` (content left null). Never raises out of the background task.
  All DB updates filter on both `id` and `user_id`.
- **`models/briefing.py`**: `BriefingSections` gains `warnings: list[str] = []` so guardrail warnings persist and are returned by `GET /briefings/{id}` (existing rows without the key still parse).
- **`routers/research.py`**: after insert, `background_tasks.add_task(run_pipeline, ...)` with `user_id` from the JWT, never from the body. Response unchanged (201, `pending`, no content). Resume embedding failures still abort before insert as today, so no pipeline runs.
- Identity: `user_id` in graph state always comes from the authenticated user.

## Acceptance Criteria

### Scenario 1: Graph topology is the fixed DAG
- **Given** the compiled graph
- **When** its edges are inspected
- **Then** company and interviewer nodes both start from START, both feed `rag_retrieval`, which feeds `synthesis`, which ends; there is no supervisor node.

### Scenario 2: Happy path end to end
- **Given** all four nodes mocked to return their partial state
- **When** the graph is invoked with company, interviewer, role and user_id
- **Then** `briefing_content` is returned, each node received the original inputs, `rag_retrieval` saw both research outputs in state, and `synthesis` saw `retrieved_context`.

### Scenario 3: Parallel branches' warnings are merged
- **Given** company and interviewer nodes each return a different warning
- **When** the graph runs
- **Then** final `warnings` contains both once, plus any later node warnings, with no duplicates.

### Scenario 4: No interviewer
- **Given** a briefing with no interviewer
- **When** the graph runs
- **Then** it still completes and produces `briefing_content` (interviewer node returns an empty profile).

### Scenario 5: Status lifecycle on success
- **Given** `run_pipeline` with a working graph
- **When** it runs
- **Then** the row is updated to `running` first, then to `complete` with `content` equal to the briefing sections (including `warnings`), each update filtered by `id` and `user_id`.

### Scenario 6: Failure marks the briefing failed
- **Given** any node raises
- **When** `run_pipeline` runs
- **Then** the status is set to `failed`, content is not written, the exception is logged, and nothing propagates.

### Scenario 7: Failure to write the failed status is contained
- **Given** the node raised and the `failed` update itself raises
- **When** `run_pipeline` runs
- **Then** the error is logged and nothing propagates.

### Scenario 8: POST triggers the pipeline with JWT identity
- **Given** an authenticated user posting a briefing whose body tries to include a different user id
- **When** `POST /briefings` succeeds
- **Then** the response is 201 `pending` with `content` null, and `run_pipeline` was scheduled once with the JWT user's id, the new briefing id, company, interviewer and role.

### Scenario 9: No pipeline when creation fails
- **Given** resume embedding or the insert fails
- **When** `POST /briefings` runs
- **Then** the existing error response is returned and `run_pipeline` is not scheduled.

### Scenario 10: Viewing a completed briefing
- **Given** a row with status `complete` and persisted content including `warnings`
- **When** `GET /briefings/{id}` is called by its owner
- **Then** the response contains the sections and the warnings; a legacy row whose content lacks `warnings` still returns with an empty list.

## Affected Files
- `backend/agents/state.py` (new)
- `backend/agents/pipeline.py` (new)
- `backend/models/briefing.py` (add `warnings`)
- `backend/routers/research.py` (trigger)
- `backend/tests/test_pipeline.py` (new)
- `backend/tests/test_research_router.py` (trigger tests)
- `CLAUDE.md` (Current State / Next Task)

## Dependencies
- `langgraph` already pinned in `requirements.txt`.
- Migration `003_retrieval_metadata.sql` applied to Supabase; `TAVILY_API_KEY`, `ANTHROPIC_API_KEY`, `OPENAI_API_KEY` set for a real run.
- Optional `LANGSMITH_TRACING` / `LANGSMITH_API_KEY` for traces.

## Open Questions
- Warnings are stored inside `content` JSON (decided here) rather than a separate column; revisit if the viewer wants them separate.
- Failure reason is not surfaced to the user (only `failed` status); add an `error` column later if needed.
- A stuck `running` row after a crash has no recovery; acceptable until a queue exists.

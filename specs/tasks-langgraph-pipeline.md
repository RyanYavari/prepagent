# Tasks: LangGraph Pipeline Wiring and Trigger

Spec: `specs/langgraph-pipeline.md`

## Slice plan

### Slice 1: State and graph topology
- [x] Write failing tests in `backend/tests/test_pipeline.py` (scenarios 1, 2, 3, 4; nodes mocked)
- [x] Implement `agents/state.py` (with warnings reducer) and `build_graph()` in `agents/pipeline.py`
- [x] Run /review

### Slice 2: run_pipeline lifecycle and persistence
- [x] Write failing tests (scenarios 5, 6, 7; Supabase mocked)
- [x] Add `warnings` to `BriefingSections`; implement `run_pipeline` status updates and content persistence
- [x] Write test for scenario 10 (GET returns warnings, legacy rows parse)
- [x] Run /review

### Slice 3: POST /briefings trigger
- [x] Write failing tests in `backend/tests/test_research_router.py` (scenarios 8, 9)
- [x] Schedule `run_pipeline` via `BackgroundTasks` in `routers/research.py`
- [x] Update CLAUDE.md Current State / Next Task
- [x] Run /review

## Done checklist
- [x] All acceptance criteria have passing tests
- [x] `pytest -x -q` passes
- [x] `ruff check` clean for new/changed files
- [x] /review returns APPROVE
- [ ] Reviewer agent returns APPROVE
- [x] /commit with conventional commit message (no Co-Authored-By)
- [ ] /why entry if any architectural decisions were made

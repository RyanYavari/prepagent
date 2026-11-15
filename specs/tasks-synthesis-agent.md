# Tasks: Synthesis Agent

Spec: `specs/synthesis-agent.md`

## Slice plan

### Slice 1: Validation, passthrough assembly, no-LLM paths
- [x] Write failing tests in `backend/tests/test_synthesis_node.py` (scenarios 1, 9, 11, 12, 13, 15, 16; `_generate` mocked)
- [x] Implement input validation, allowed-source/section collection, passthrough assembly, interviewer gating, no-context skip, `sources` in code in `backend/agents/synthesis.py`
- [ ] Run /review

### Slice 2: LLM generation + source-attribution prompt
- [x] Write failing tests (scenarios 2, 14, plus structured-output wiring with mocked ChatAnthropic)
- [x] Implement `SynthesisOutput`, `_generate` with the attribution prompt and context formatting
- [ ] Run /review

### Slice 3: Citation validation + warnings
- [x] Write failing tests (scenarios 3, 4, 5, 6, 7, 8, 10)
- [x] Implement citation parsing/validation, item dropping, dropped-items and empty-talking-points warnings
- [x] Update CLAUDE.md Current State / Next Task
- [ ] Run /review

## Done checklist
- [ ] All acceptance criteria have passing tests
- [ ] `pytest -x -q` passes
- [ ] `ruff check` clean for new/changed files
- [ ] /review returns APPROVE
- [ ] Reviewer agent returns APPROVE
- [ ] /commit with conventional commit message (no Co-Authored-By)
- [ ] /why entry if any architectural decisions were made

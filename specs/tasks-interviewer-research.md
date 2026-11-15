# Tasks: Interviewer Research Agent

Spec: `specs/interviewer-research.md`

## Slice plan

### Slice 1: Skip, validation, query ladder, relevance filter, retry loop
- [x] Write failing tests in `backend/tests/test_interviewer_node.py` (scenarios 1, 2, 3, 5, 6, 8, 9, 10, 12, 14; search and `_summarize` mocked)
- [x] Implement skip/validation, query ladder, name-relevance filter, URL de-dup, retry loop in `backend/agents/interviewer.py`
- [ ] Run /review

### Slice 2: Warnings (low-result + wrong-person)
- [x] Write failing tests (scenarios 4, 7)
- [x] Implement `low_result_warning`, wrong-person warning, company-confirmed check
- [ ] Run /review

### Slice 3: LLM summarization + sources guardrail
- [x] Write failing tests (scenarios 11, 13, plus prompt/structured-output wiring with mocked ChatAnthropic)
- [x] Implement `_summarize` with grounding prompt; overwrite `sources` from results
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

# Tasks: Company Intelligence Agent

Spec: `specs/company-intelligence.md`

## Slice plan

### Slice 1: Search model + Tavily service
- [ ] Add `backend/models/research.py` (`SearchResult`)
- [ ] Write failing tests in `backend/tests/test_web_search.py` (missing key, result mapping, Scenario 10 service half)
- [ ] Implement `backend/services/web_search.py` (`search_web`)
- [ ] Run /review

### Slice 2: Retry loop + low-result warning
- [ ] Write failing tests in `backend/tests/test_company_node.py` (scenarios 2, 3, 4, 5, 6, 8, 9, 11; LLM and search mocked)
- [ ] Implement query ladder, URL de-dup, threshold logic, warnings, input validation in `backend/agents/company.py`
- [ ] Run /review

### Slice 3: LLM summarization + sources guardrail
- [ ] Write failing tests (scenarios 1, 7, 10)
- [ ] Implement structured-output Claude call with grounding prompt; overwrite `sources` from results
- [ ] Update CLAUDE.md Current State / Next Task
- [ ] Run /review

## Done checklist
- [ ] All acceptance criteria have passing tests
- [ ] `pytest -x -q` passes
- [ ] `ruff check` clean for new/changed files
- [ ] /review returns APPROVE
- [ ] Reviewer agent returns APPROVE
- [ ] /commit with conventional commit message (no Co-Authored-By)
- [ ] /why entry if any architectural decisions were made

# Tasks: RAG Retrieval Node

Spec: `specs/rag-retrieval.md`

## Slice plan

### Slice 1: Schema + models
- [x] Add `supabase/migrations/003_retrieval_metadata.sql` (company, role columns, index)
- [x] Document migration in `supabase/README.md`
- [x] Add `backend/models/retrieval.py` (`RetrievedChunk`, `RetrievalResult`)
- [ ] Run /review

### Slice 2: Retrieval service
- [x] Write failing tests in `backend/tests/test_retrieval.py` (scenarios 1, 2, 3, 7, 8)
- [x] Implement `backend/services/retrieval.py` (`retrieve_user_context`)
- [ ] Run /review

### Slice 3: RAG node
- [ ] Write failing tests in `backend/tests/test_rag_node.py` (scenarios 4, 5, 6)
- [ ] Implement `rag_retrieval_node` in `backend/agents/rag.py`
- [ ] Update CLAUDE.md Current State / Next Task
- [ ] Run /review

## Done checklist
- [ ] All acceptance criteria have passing tests
- [ ] `pytest -x -q` passes
- [ ] `ruff check` clean for new/changed files (repo has 11 pre-existing errors)
- [ ] /review returns APPROVE
- [ ] Reviewer agent returns APPROVE
- [ ] /commit with conventional commit message (no Co-Authored-By)
- [ ] /why entry if any architectural decisions were made

# Tasks: Briefing Chunk Writer

Spec: `specs/briefing-chunk-writer.md`

## Slice plan

### Slice 1: Schema + rendering
- [x] Add `supabase/migrations/006_briefing_chunk_link.sql` (`briefing_id` + index) and document in `supabase/README.md`
- [x] Write failing tests for `render_sections` (scenarios 3, 4, 9)
- [x] Implement `render_sections` in `backend/services/briefing_chunks.py`
- [x] Run /review

### Slice 2: Writer service
- [x] Write failing tests for `write_briefing_chunks` (scenarios 1, 2, 8)
- [x] Implement `write_briefing_chunks` (delete by briefing_id, embed, insert)
- [x] Run /review

### Slice 3: Pipeline wiring
- [x] Write failing tests in `test_pipeline.py` (scenarios 5, 6, 7)
- [x] Call the writer from `run_pipeline` after `complete`, swallowing errors
- [x] Update CLAUDE.md Current State / Next Task
- [x] Run /review

## Done checklist
- [x] All acceptance criteria have passing tests
- [x] `pytest -x -q` passes
- [x] `ruff check` clean for changed files
- [x] /review returns APPROVE
- [ ] Reviewer agent returns APPROVE
- [ ] /commit with conventional commit message (no Co-Authored-By)
- [ ] /why entry if any architectural decisions were made

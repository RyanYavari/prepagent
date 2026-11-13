# Tasks: Resume Ingestion with pgvector Embedding Storage

Spec: `specs/resume-ingestion.md`

## Slice plan

Break the spec into the smallest shippable slices. Each slice should be independently testable.

### Slice 1: Database migration and pgvector table
- [ ] Create `supabase/migrations/002_resume_embeddings.sql`
- [ ] Add `resume_embeddings` table with pgvector extension
- [ ] Add indexes (ivfflat on embedding, composite on user_id/doc_type)
- [ ] Run migration in Supabase
- [ ] Verify table exists with correct schema

### Slice 2: Resume chunking service (no embedding)
- [ ] Create `backend/services/embeddings.py`
- [ ] Implement `chunk_resume(resume_text: str) -> List[ResumeChunk]`
- [ ] Section header regex: `(Experience|Education|Skills|Projects|Summary|Certifications)`
- [ ] Fallback: if no headers, return single chunk with `section: "other"`
- [ ] Create `backend/tests/test_embeddings.py`
- [ ] Test scenario: multi-section resume yields correct chunks
- [ ] Test scenario: no headers yields single "other" chunk
- [ ] Test scenario: empty/None input returns empty list

### Slice 3: OpenAI embedding integration
- [ ] Add `openai>=1.0.0` to `backend/requirements.txt`
- [ ] Add `OPENAI_API_KEY` to `.env.example`
- [ ] Implement `embed_text(text: str) -> List[float]` using text-embedding-3-small
- [ ] Implement `store_resume_embeddings(user_id, chunks, embeddings)` — inserts to Supabase
- [ ] Implement `delete_user_resume_embeddings(user_id)` — deletes existing resume chunks
- [ ] Test: mock OpenAI API, verify embedding dimension is 1536
- [ ] Test: verify Supabase insert with user_id, doc_type, section, content, embedding

### Slice 4: Integration into POST /briefings endpoint
- [ ] Modify `backend/routers/research.py` after line 48
- [ ] Call `process_resume_embedding(user_id, resume_text)` which:
  1. Deletes old embeddings
  2. Chunks resume
  3. Embeds each chunk
  4. Stores in pgvector
- [ ] Handle OpenAI API errors: catch exceptions, raise HTTPException 503
- [ ] Test: POST /briefings with resume_text creates embeddings
- [ ] Test: POST /briefings without resume_text skips embedding
- [ ] Test: POST /briefings with updated resume_text deletes old embeddings
- [ ] Test: OpenAI API failure returns 503 and doesn't create briefing

## Done checklist
- [ ] All acceptance criteria have passing tests
- [ ] `pytest -x -q` passes
- [ ] `ruff check` clean
- [ ] /review returns APPROVE
- [ ] /commit with conventional commit message
- [ ] /why entry documenting pgvector over Pinecone decision (already in ARCHITECTURE_DECISIONS.md)

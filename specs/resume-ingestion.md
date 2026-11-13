# Spec: Resume Ingestion with pgvector Embedding Storage

## Problem
Resume text is saved to the Supabase `users.resume_text` column (backend/routers/research.py:44-48) but not chunked, embedded, or stored in pgvector for RAG retrieval. The briefing synthesis agent will need to retrieve relevant resume sections when generating talking points, but no vector search capability exists yet.

## Goal
When a user provides resume_text via POST /briefings, the system chunks it by section header, embeds each chunk via OpenAI text-embedding-3-small, and stores the embeddings in a Supabase pgvector table for later retrieval.

## Non-goals
- Resume upload UI (frontend form) — out of scope; will be tackled after backend service is working
- PDF parsing — v1 accepts plain text only; PDF extraction is a future enhancement
- Automatic section detection via LLM — use simple regex/heuristic splitting by common headers
- Briefing chunk embedding — only resume chunks in this slice; briefing embedding happens post-synthesis
- Retrieval endpoint — only embedding/storage; retrieval logic comes with the RAG agent implementation

## Acceptance Criteria

### Scenario 1: Resume text provided for first time
- **Given** a user with no existing resume embeddings in pgvector
- **When** they create a briefing with `resume_text` containing "## Experience\nSenior Engineer at Acme\n\n## Education\nBS Computer Science"
- **Then** the system:
  1. Saves raw text to `users.resume_text` (existing behavior)
  2. Chunks text into 2 sections: "Experience" and "Education"
  3. Calls OpenAI text-embedding-3-small for each chunk
  4. Inserts 2 rows into `resume_embeddings` table with `{user_id, doc_type: "resume", section: "experience", content, embedding}`
  5. Returns 201 with briefing created

### Scenario 2: Resume text updated (re-embedding)
- **Given** a user with existing resume embeddings in pgvector (5 chunks)
- **When** they create a briefing with NEW `resume_text`
- **Then** the system:
  1. Deletes all existing rows in `resume_embeddings` WHERE `user_id = <user_id>` AND `doc_type = 'resume'`
  2. Chunks the new resume text
  3. Embeds and stores new chunks
  4. Returns 201

### Scenario 3: No resume text provided
- **Given** a user creating a briefing
- **When** `resume_text` is null or empty string
- **Then** the system skips chunking/embedding and returns 201 (no error; resume is optional)

### Scenario 4: OpenAI API failure
- **Given** a user provides resume_text
- **When** OpenAI embedding API returns 429 (rate limit) or 500 (server error)
- **Then** the system:
  1. Logs the error with user_id and retry-able flag
  2. Raises HTTPException 503 "Embedding service temporarily unavailable"
  3. Does NOT save partial embeddings to pgvector
  4. Does NOT create the briefing record

### Scenario 5: Chunking yields zero sections
- **Given** a user provides resume_text = "Just a random paragraph with no headers"
- **When** the chunker finds no section markers
- **Then** the system treats the entire text as a single chunk with `section: "other"`, embeds it, and continues

## Affected Files

### New Files
- `backend/services/embeddings.py` — OpenAI embedding client, chunking logic, pgvector storage
- `backend/tests/test_embeddings.py` — Unit tests for chunking and embedding service
- `supabase/migrations/002_resume_embeddings.sql` — Create `resume_embeddings` table with pgvector extension

### Modified Files
- `backend/routers/research.py` — After saving resume_text (line 48), call embeddings service to chunk and store
- `backend/requirements.txt` — Add `openai` and `tiktoken` (for token counting)
- `.env.example` — Add `OPENAI_API_KEY` placeholder

## Dependencies

### Required before implementation
1. **Supabase pgvector extension enabled** — Run `CREATE EXTENSION IF NOT EXISTS vector;` in Supabase SQL editor
2. **OpenAI API key** — Must be set in `.env` as `OPENAI_API_KEY`
3. **Database migration** — Create `resume_embeddings` table schema:
   ```sql
   CREATE TABLE resume_embeddings (
     id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
     user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
     doc_type TEXT NOT NULL DEFAULT 'resume',
     section TEXT NOT NULL,  -- 'experience', 'education', 'skills', 'projects', 'other'
     content TEXT NOT NULL,
     embedding VECTOR(1536),  -- OpenAI text-embedding-3-small dimension
     created_at TIMESTAMPTZ DEFAULT NOW()
   );

   CREATE INDEX ON resume_embeddings USING ivfflat (embedding vector_cosine_ops);
   CREATE INDEX ON resume_embeddings (user_id, doc_type);
   ```

### Python packages to add
- `openai>=1.0.0` — Official OpenAI SDK
- `tiktoken` — Token counting for OpenAI models (optional but useful for chunk validation)

## Open Questions

1. **Chunking heuristic:** What section headers should we recognize?
   - **Proposed:** Case-insensitive regex for common headers: `(Experience|Education|Skills|Projects|Summary|Certifications)`
   - **Fallback:** If no headers found, treat entire text as one chunk with `section: "other"`

2. **Token limit per chunk:** Should we validate that chunks don't exceed OpenAI's context window?
   - **Proposed:** Log a warning if any chunk exceeds 8k tokens but don't reject it (text-embedding-3-small supports up to 8191 tokens)

3. **Embedding model:** Stick with text-embedding-3-small or use text-embedding-3-large?
   - **Decision:** text-embedding-3-small (1536 dims, $0.02/1M tokens) — per ARCHITECTURE_DECISIONS.md "industry standard for RAG"

4. **Re-embedding logic:** Should updating resume_text always delete old embeddings, or track versions?
   - **Decision:** Always delete and re-embed (no versioning in v1) — keeps it simple, user resume changes infrequently

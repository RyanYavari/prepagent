-- Enable pgvector extension for vector similarity search
CREATE EXTENSION IF NOT EXISTS vector;

-- Resume embeddings table for RAG retrieval
-- Stores chunked resume sections with their embeddings
CREATE TABLE IF NOT EXISTS resume_embeddings (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  doc_type TEXT NOT NULL DEFAULT 'resume',
  section TEXT NOT NULL,  -- 'experience', 'education', 'skills', 'projects', 'other'
  content TEXT NOT NULL,
  embedding VECTOR(1536),  -- OpenAI text-embedding-3-small dimension
  created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Index for vector similarity search using IVFFlat
-- vector_cosine_ops for cosine similarity (most common for embeddings)
CREATE INDEX IF NOT EXISTS resume_embeddings_embedding_idx
  ON resume_embeddings
  USING ivfflat (embedding vector_cosine_ops)
  WITH (lists = 100);  -- IVFFlat parameter: number of clusters

-- Index for filtering by user_id and doc_type during retrieval
CREATE INDEX IF NOT EXISTS resume_embeddings_user_doc_idx
  ON resume_embeddings (user_id, doc_type);

-- Comment for documentation
COMMENT ON TABLE resume_embeddings IS 'Stores resume and briefing chunks with vector embeddings for RAG retrieval';
COMMENT ON COLUMN resume_embeddings.embedding IS 'OpenAI text-embedding-3-small (1536 dimensions)';
COMMENT ON COLUMN resume_embeddings.section IS 'Resume section type: experience, education, skills, projects, or other';

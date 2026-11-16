-- Link briefing chunks to their briefing so the writer is idempotent and chunks
-- are removed with the briefing (specs/briefing-chunk-writer.md). Resume rows leave it NULL.
ALTER TABLE resume_embeddings
  ADD COLUMN IF NOT EXISTS briefing_id UUID REFERENCES briefings(id) ON DELETE CASCADE;

CREATE INDEX IF NOT EXISTS resume_embeddings_briefing_idx
  ON resume_embeddings (briefing_id);

COMMENT ON COLUMN resume_embeddings.briefing_id IS 'Source briefing for doc_type = ''briefing'' chunks; NULL for resume chunks';

-- Metadata for briefing chunks so retrieval can filter by target company
-- (ARCHITECTURE_DECISIONS.md section 3). Resume rows leave these NULL.
ALTER TABLE resume_embeddings
  ADD COLUMN IF NOT EXISTS company TEXT,
  ADD COLUMN IF NOT EXISTS role TEXT;

-- Case-insensitive company lookup scoped to a user and doc type
CREATE INDEX IF NOT EXISTS resume_embeddings_user_doc_company_idx
  ON resume_embeddings (user_id, doc_type, lower(company));

COMMENT ON COLUMN resume_embeddings.company IS 'Target company for doc_type = ''briefing'' chunks; NULL for resume chunks';
COMMENT ON COLUMN resume_embeddings.role IS 'Target role for doc_type = ''briefing'' chunks; NULL for resume chunks';

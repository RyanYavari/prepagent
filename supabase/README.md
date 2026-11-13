# Supabase Migrations

## Running Migrations

### Option 1: Supabase Dashboard (Recommended for local dev)

1. Go to your Supabase project dashboard
2. Navigate to **SQL Editor**
3. Copy the contents of the migration file
4. Paste and execute

### Option 2: Supabase CLI

```bash
# Initialize Supabase (first time only)
supabase init

# Link to your remote project
supabase link --project-ref <your-project-ref>

# Run migrations
supabase db push

# Or run a specific migration
psql $DATABASE_URL -f supabase/migrations/002_resume_embeddings.sql
```

### Option 3: Direct SQL execution (if you have connection string)

```bash
psql "$SUPABASE_DATABASE_URL" -f supabase/migrations/002_resume_embeddings.sql
```

## Migration Files

- `002_resume_embeddings.sql` - Creates `resume_embeddings` table with pgvector support
- `003_retrieval_metadata.sql` - Adds `company`, `role` columns and a case-insensitive company index for briefing-chunk retrieval

## Verifying Migration

After running the migration, verify in Supabase SQL editor:

```sql
-- Check table exists
SELECT table_name, column_name, data_type
FROM information_schema.columns
WHERE table_name = 'resume_embeddings';

-- Check indexes
SELECT indexname, indexdef
FROM pg_indexes
WHERE tablename = 'resume_embeddings';

-- Verify pgvector extension
SELECT * FROM pg_extension WHERE extname = 'vector';
```

-- Calendar interview detection (specs/calendar-detection.md).
-- Both tables are server-only: RLS is enabled with no policies, so only the
-- service key (which bypasses RLS) can read or write them.

CREATE TABLE IF NOT EXISTS calendar_connections (
  user_id UUID PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
  encrypted_refresh_token TEXT NOT NULL,
  scope TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'revoked')),
  connected_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  last_synced_at TIMESTAMPTZ,
  last_error_code TEXT
);

CREATE TABLE IF NOT EXISTS calendar_detections (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  google_event_id TEXT NOT NULL,
  event_etag TEXT,
  event_start TIMESTAMPTZ,
  status TEXT NOT NULL CHECK (
    status IN ('processing', 'ignored', 'needs_confirmation', 'briefing_created', 'dismissed')
  ),
  classification JSONB,
  briefing_id UUID REFERENCES briefings(id) ON DELETE SET NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  -- One detection (and so at most one briefing) per calendar event per user.
  CONSTRAINT calendar_detections_user_event_key UNIQUE (user_id, google_event_id)
);

CREATE INDEX IF NOT EXISTS calendar_detections_user_status_idx
  ON calendar_detections (user_id, status);

ALTER TABLE calendar_connections ENABLE ROW LEVEL SECURITY;
ALTER TABLE calendar_detections ENABLE ROW LEVEL SECURITY;

COMMENT ON COLUMN calendar_connections.encrypted_refresh_token IS 'Fernet ciphertext; key in TOKEN_ENCRYPTION_KEY. Never store plaintext.';
COMMENT ON COLUMN calendar_detections.classification IS 'Extracted fields + confidence only; raw event text is never stored.';

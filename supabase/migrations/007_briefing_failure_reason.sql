-- Generic, user-visible reason for a failed briefing (timeout, error, interrupted).
-- Never holds exception text. The backend falls back to status-only updates when
-- this column is missing, so applying it is not required for runs to be marked failed.
ALTER TABLE briefings
  ADD COLUMN IF NOT EXISTS failure_reason TEXT;

COMMENT ON COLUMN briefings.failure_reason IS 'Generic reason shown when status = ''failed''; never exception text';

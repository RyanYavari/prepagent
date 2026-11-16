-- Drop the plaintext sign-in Google tokens (specs/signin-token-removal.md).
--
-- ORDER: deploy the code that stops storing tokens, then run
--   python -m scripts.revoke_stored_tokens     (from backend/)
-- which revokes each stored token at Google and nulls the columns, and only then
-- apply this migration. The guard below refuses to run while any token remains,
-- so it cannot destroy grants that were never revoked.

DO $$
BEGIN
  IF EXISTS (
    SELECT 1 FROM users
    WHERE google_access_token IS NOT NULL OR google_refresh_token IS NOT NULL
  ) THEN
    RAISE EXCEPTION
      'users still holds Google tokens: run backend/scripts/revoke_stored_tokens.py first';
  END IF;
END $$;

ALTER TABLE users DROP COLUMN IF EXISTS google_access_token;
ALTER TABLE users DROP COLUMN IF EXISTS google_refresh_token;

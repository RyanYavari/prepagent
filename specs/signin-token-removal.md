# Spec: Stop Storing Sign-in Google Tokens

## Problem
`/auth/callback` stores Google's access and refresh tokens in plaintext in `users.google_access_token` / `users.google_refresh_token`. Nothing reads them (the only reference outside the write is the unused `refresh_access_token` helper), and sign-in now requests identity scopes only. Rows created before the scope trim may hold refresh tokens carrying broad Gmail, Drive and Calendar grants.

## Goal
Sign-in persists and logs no Google token; existing stored tokens are revoked at Google (best effort) and then removed, and the columns are dropped.

## Decisions (ARCHITECTURE_DECISIONS.md has no section on sign-in token storage; these follow §4 amendment / §7, where calendar access lives in `calendar_connections` with an encrypted token, and the "never mix with sign-in tokens" rule)
1. **Stop storing, do not encrypt.** Sign-in needs Google only to learn the user's email; our own JWT is the session. The access token is used once, in memory, for the userinfo call. No feature needs a sign-in refresh token. Encrypting would keep a secret with no consumer.
2. **Stop minting a refresh token too.** Sign-in switches from `access_type=offline` + `prompt=consent` to online access with default prompting, so Google issues no refresh token. `exchange_code_for_tokens` returns only `email` and `name`.
3. **Revoke before delete, via a one-off script, then a migration.** The tokens live only in the DB, so revocation must run before the data is destroyed. `backend/scripts/revoke_stored_tokens.py` revokes each stored refresh token (best effort; the summary counts `revoked` vs `unconfirmed`, and unconfirmed includes tokens Google had already invalidated), then nulls both columns for every row, whether or not revocation succeeded, and reports counts. Migration `005` then drops the columns. Order: deploy code, run script, run migration.
4. **Migration guard.** `005` raises if any row still holds a token, so running it before the script cannot silently destroy unrevoked grants. It then drops both columns.
5. **Known side effect:** Google may treat a revoke as revoking the whole grant for that user and client, including a calendar connection made via the separate consent. The calendar code already handles this (`invalid_grant` -> status `revoked` -> user reconnects).

## Non-goals
- Logging the authorization `code` query parameter (single-use, appears in server access logs; separate concern).
- Changing JWT sessions, calendar tokens or `calendar_connections`.
- Purging Supabase backups/PITR snapshots that may still contain the old values (note in the runbook; cannot be done from code).
- Running the revocation script against production from this session.

## Acceptance Criteria

### Given a successful sign-in for a new user
### When `/auth/callback` runs
### Then the `users` insert payload contains only `email`; no token value appears in it.

### Given a successful sign-in for an existing user
### When `/auth/callback` runs
### Then no `users` update carrying token values is issued, and the session JWT is returned.

### Given sign-in with sentinel token values from Google, including a failing DB or failing token exchange
### When the request completes
### Then no sentinel appears in the response body or in any captured log record (including exception text).

### Given the sign-in authorization URL
### When it is built
### Then it has no `access_type=offline` and no `prompt=consent`, and still `include_granted_scopes=false` and the identity-only scopes.

### Given `exchange_code_for_tokens`
### When it succeeds
### Then the result has only `email` and `name`, and the unused `refresh_access_token` helper is gone.

### Given users with stored refresh tokens
### When the revoke script runs
### Then each token is sent to Google's revoke endpoint, both columns are nulled for all rows, and the summary reports scanned / revoked / unconfirmed / scrubbed counts.

### Given a revoke call that errors (network or non-200/400)
### When the script runs
### Then that row is still scrubbed, counted as unconfirmed, and the script does not raise.

### Given rows with null tokens
### When the script runs
### Then no revoke calls are made.

### Given the script's output and logs
### When it runs with sentinel tokens
### Then no token value is printed or logged.

### Given migration 005 and rows that still hold a token
### When it is applied
### Then it fails with a message pointing at the script; with no tokens left it drops both columns.

### Given the code base
### When searched for `google_access_token` / `google_refresh_token`
### Then the only hits are the revoke script, migration 005, tests, and historical docs.

## Affected Files
- `backend/routers/auth.py` (stop writing tokens)
- `backend/services/google_auth.py` (online access, drop tokens from result, remove `refresh_access_token`)
- `backend/scripts/revoke_stored_tokens.py` (new), `backend/scripts/__init__.py`
- `supabase/migrations/005_drop_signin_tokens.sql` (new), `supabase/README.md`
- `backend/tests/test_signin_tokens.py` (new), `backend/tests/test_revoke_stored_tokens.py` (new), `backend/tests/test_google_auth.py` (adjust)
- `grounding_docs/full_architecture.md`, `CLAUDE.md`, `docs/decisions.md` (/why entry), `ARCHITECTURE_DECISIONS.md` (short note)

## Dependencies
- `SUPABASE_URL`, `SUPABASE_SERVICE_KEY`, `GOOGLE_CLIENT_ID/SECRET` available when running the script.
- Existing `revoke_token` in `services/google_auth.py`.

## Open Questions
- None blocking. Whether to also remove the app's Gmail/Drive grants in the Google account page for the owner's own account: the revoke script covers it if a token is stored.

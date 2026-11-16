# Tasks: Stop Storing Sign-in Google Tokens

Spec: `specs/signin-token-removal.md`

One commit for the whole spec, made after all slices are built, `pytest -x -q` passes and /review is APPROVE. Write failing tests first in each slice. No Co-Authored-By lines.

## Slice plan

### Slice 1: Sign-in persists and logs no token
- [x] `routers/auth.py`: insert only `email`; no token update for existing users
- [x] `services/google_auth.py`: online access / no forced consent, return only `email` + `name`, remove `refresh_access_token`
- [x] Tests (`test_signin_tokens.py`, adjust `test_google_auth.py`): insert/update payloads, sentinel tokens absent from response and logs (success, DB failure, exchange failure), URL params
- [x] Run /review

### Slice 2: Revoke-then-scrub script
- [x] `scripts/revoke_stored_tokens.py`: revoke each stored refresh token (best effort), null both columns for all rows, print counts, never log tokens
- [x] Tests (`test_revoke_stored_tokens.py`): revoke called per token, scrub on revoke failure, null rows skipped, no token in output/logs
- [x] Run /review

### Slice 3: Migration, docs, reference check
- [x] `supabase/migrations/005_drop_signin_tokens.sql` with guard, then drop; `supabase/README.md` runbook (order: deploy, script, migration)
- [x] Update `grounding_docs/full_architecture.md`, `CLAUDE.md`, `ARCHITECTURE_DECISIONS.md` note, `docs/decisions.md` (/why)
- [x] Grep proving nothing else reads the columns
- [x] Run /review

## Done checklist
- [x] All acceptance criteria have passing tests
- [x] `pytest -x -q` passes
- [x] `ruff check` clean (changed files only)
- [x] /review returns APPROVE
- [ ] Reviewer agent returns APPROVE (not run; inline /review only)
- [x] /commit with conventional commit message
- [x] /why entry if any architectural decisions were made

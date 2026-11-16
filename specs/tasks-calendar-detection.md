# Tasks: Calendar Interview Detection

Spec: `specs/calendar-detection.md`

One commit for the whole spec, made after all slices are built, `pytest -x -q` passes and /review is APPROVE. Write failing tests first in each slice. No Co-Authored-By lines.

## Slice plan

### Slice 1: Migration and token encryption
- [x] `supabase/migrations/004_calendar_integration.sql`: `calendar_connections`, `calendar_detections` (`UNIQUE (user_id, google_event_id)`), RLS on, no policies; document in `supabase/README.md`
- [x] `services/token_crypto.py`: Fernet encrypt/decrypt from `TOKEN_ENCRYPTION_KEY`, fail closed on missing/invalid key
- [x] Tests: round-trip, ciphertext != plaintext, missing/invalid key raises, wrong key fails to decrypt
- [x] Run /review

### Slice 2: Calendar connect, status, disconnect
- [x] `services/google_auth.py`: calendar authorization URL (only `calendar.events.readonly`, `include_granted_scopes=false`, offline, consent, PKCE), state bound to the initiating `user_id`, callback exchange with exact-scope check (revoke + reject on mismatch), revoke helper
- [x] `models/calendar.py`, `routers/calendar.py`: `GET /calendar/connect`, `POST /calendar/callback`, `GET /calendar/status`, `DELETE /calendar/connection`; register in `main.py`; identity from JWT only
- [x] Tests: URL params/scope, state mismatch between users, unknown/expired/reused state, extra-scope rejection + revoke, no refresh token, encrypted storage, key-missing fails closed, disconnect (revoke ok / revoke fails / no connection), generic error messages with logged real errors, sign-in scopes unchanged
- [x] Run /review

### Slice 3: Calendar API client and token refresh
- [x] `services/google_auth.py`: calendar refresh raising `CalendarAuthError` (`invalid_grant`) vs `CalendarUnavailableError` (network/5xx/429)
- [x] `services/calendar.py`: `events.list` over httpx (primary, window, `singleEvents`, cap 100), event normalization/truncation (title 200, description 2,000 HTML-stripped, 10 attendees as name + domain only)
- [x] Tests: `invalid_grant` marks connection `revoked` and later syncs short-circuit with 409, transient errors leave `active` (503), empty window, Google error body never reaches the client, access token not persisted/logged
- [x] Run /review

### Slice 4: Detection classifier gate
- [x] `agents/calendar_detect.py`: `InterviewDetection` (`extra="forbid"`, bounds), prompt with delimited untrusted data, `classify_event` via `structured_llm` with no tools, field sanitization, grounding check, pure `decide()`
- [x] Pre-filter in `services/calendar.py` and `MAX_LLM_CALLS_PER_SYNC`
- [x] Tests: pre-filter skips (cancelled/all-day/declined/past/no-attendee-no-keyword), decide matrix (ignore / auto / confirm: uncertain, below threshold, ungrounded, not accepted, per-sync cap, threshold > 1), sanitization (URL, brackets, control chars, length), schema rejection of extra fields/out-of-range confidence, prompt-injection event (mock returns attacker output: at most a pending briefing, no other side effect), LLM-raises path, assert no tools bound
- [x] Live smoke: `RUN_LIVE_LLM_TESTS=1` classification of a normal and an adversarial event against the real model
- [x] Run /review

### Slice 5: Sync orchestration, dedupe, confirm/dismiss
- [x] `services/briefings.py`: extract `create_pending_briefing` from `POST /briefings` (insert + schedule only); `routers/research.py` uses it; existing research tests stay green
- [x] `sync_user_calendar(user_id)`: claim-then-act insert-ignore on `(user_id, google_event_id)`, etag re-classification rule, stale `processing` reclaim, auto/confirm/ignore outcomes, `last_synced_at`, 30s cooldown
- [x] Routes: `POST /calendar/sync`, `GET /calendar/detections`, `POST /calendar/detections/{id}/confirm` (atomic transition, edits validated like `BriefingCreate`, forbid extras), `POST .../dismiss`; 404 for other users' rows
- [x] Tests: no duplicate on re-sync, concurrent claim yields one briefing, reconnect does not duplicate, etag change re-classifies once, dismissed never reprocessed, double confirm yields one briefing, cross-user 404, generic errors, pipeline patched (`run_pipeline` patched in both routers)
- [x] Run /review

### Slice 6: Frontend
- [x] Calendar API helpers, `/calendar/callback` page, dashboard section (Connect / status / Sync now / awaiting-confirmation list with Confirm/Dismiss / reconnect prompt); extracted fields rendered as plain text
- [x] Vitest tests for helpers and rendering states
- [ ] Manual browser check (unticked until actually done; otherwise report as unverified): connect round-trip, sync, confirm, dismiss, revoked state
- [x] Run /review

### Slice 7: Downstream prompt hardening
- [x] `agents/prompting.py`: helper that wraps untrusted values/results in delimited data blocks, bounds query strings
- [x] Audit and harden company, interviewer and synthesis prompts (fields and Tavily results are data, never instructions); `BriefingCreate` validator for company/interviewer/role
- [x] Tests: delimiter and untrusted-data wording present in each prompt, injection-like field values only appear inside the data block, query bounds, validator accepts normal names ("AT&T", "O'Brien") and rejects URLs/brackets/control chars; existing agent tests green
- [x] Run /review

### Slice 8: Optional polling loop (can be deferred)
- [x] Lifespan task running `sync_user_calendar` over active connections every `CALENDAR_POLL_INTERVAL_MINUTES` (default 0 = off), errors per user isolated and logged
- [x] Tests: disabled by default, one user's failure does not stop others
- [x] Run /review

## Done checklist
- [x] All acceptance criteria have passing tests
- [x] `pytest -x -q` passes
- [x] `ruff check` clean (format only changed files; stage by name)
- [x] /review returns APPROVE
- [ ] Reviewer agent returns APPROVE
- [x] Live smoke run for the classifier with real keys
- [ ] Migration 004 applied; Google Cloud (Calendar API, scope, redirect URI, test users) set up
- [ ] /commit with conventional commit message (no Co-Authored-By)
- [x] ADR 7 + §4 amendment in `ARCHITECTURE_DECISIONS.md` and /why entries in `docs/decisions.md` (approved)
- [x] CLAUDE.md "Current State" and env vars updated

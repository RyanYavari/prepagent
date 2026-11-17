# Tasks: Deployment (EC2 backend, Vercel frontend)

Spec: `specs/deployment.md`

Status: **approved; Slices 1-8 built and reviewed (independent reviewer: CHANGES REQUESTED, fixed, re-review APPROVE). Slice 9 partly done (README, CLAUDE.md; no /why entry). Not verified: Docker build/run, Caddyfile, deploy scripts, frontend in a browser.** Slices 1-8 are repo changes, built test-first. Part B is the operator runbook: the owner performs it by hand, and nothing in it is run by an agent. It creates cloud resources and spends money.

Commit rules (CLAUDE.md): ONE commit for the whole spec (spec and tasks docs may be committed first on their own) after `pytest -x -q` passes and /review is APPROVE, conventional commit, no Co-Authored-By. Format and `ruff check --fix` only the files changed, stage by name. Frontend slices are not done until checked in a real browser, otherwise they are reported as unverified. Do not touch `backend/.env`, the root `docker-compose.yml` or `.github/workflows/ci.yml` (the spec adds `deploy/docker-compose.prod.yml`; the root file stays as is). Do not start Slice 1 until the open questions that block it are answered (noted per slice).

## Part A: repo changes

### Slice 1: Production config guard and secret hygiene (no open questions blocking)
- [x] Write failing tests: production start refuses with missing `JWT_SECRET`, the dev default, or under 32 chars; invalid Fernet `TOKEN_ENCRYPTION_KEY`; `FRONTEND_URL` that is http, localhost or has a trailing slash; the error lists variable **names only**, never values; non-production start is unchanged
- [x] `services/prod_config.py` `validate_production_config()`, called at startup when `APP_ENV=production`
- [x] Remove the `dev-secret-change-me` fallback in `routers/auth.py` and `dependencies/auth.py` when `APP_ENV=production` (tests keep working without it); one shared accessor so the two cannot drift
- [x] `docs_url`/`redoc_url`/`openapi_url` off in production; `/health` unchanged
- [x] Startup warning when `WEB_CONCURRENCY` or `UVICORN_WORKERS` is above 1
- [x] Update `backend/.env.example` (current variables, `TOKEN_ENCRYPTION_KEY`, `APP_ENV`, cap and flag names; remove Cohere/Pinecone); do not touch `backend/.env`
- [x] Run /review

### Slice 2: Handlers that block the event loop
- [x] Write a failing test: a slow patched Supabase/embedding call in `POST /briefings` does not delay a concurrent `GET /health`
- [x] Convert handlers in `routers/research.py` and `routers/calendar.py` that call blocking clients from `async def` to `def` (keep `async def` where they `await` Google calls); check the verifier-store lock is still the only shared state touched
- [x] Existing router tests still pass unchanged
- [x] Run /review

### Slice 3: Kill switches and signup gate (blocked on Q1 if the allowlist semantics change)
- [x] Write failing tests: `SIGNUPS_ENABLED=false` returns 403 for a new email, inserts nothing, lets an existing user in; `ALLOWED_EMAILS` blocks others on sign-in and signup, unset means no allowlist; `BRIEFINGS_ENABLED=false` gives 503 on `POST /briefings` and calendar confirm while reads still work; `CALENDAR_ENABLED=false` disables calendar routes
- [x] `services/limits.py` flag readers (read at call time, bad values fall back to the safe default)
- [x] Wire flags into `routers/auth.py`, `routers/research.py`, `routers/calendar.py`; no email addresses in log lines
- [x] Run /review

### Slice 4: Briefing caps (blocked on Q3 and Q12 for the default numbers)
- [x] Write failing tests with `FakeSupabase`: per-user rolling 24 h cap, per-user active cap (`pending`+`running`), global daily cap; 429 with `Retry-After` and a generic body; cap checked **before** the resume embedding call (no OpenAI call, no insert, no pipeline); calendar-created briefings count; a capped calendar confirm leaves the detection unconfirmed; bad env values fall back to defaults; the body never contains other users' counts
- [x] `services/limits.py` counts (one query each) and `BriefingLimitExceeded`; enforce in `create_pending_briefing` and the `POST /briefings` pre-check
- [x] Map to 429 in `routers/research.py` and `routers/calendar.py` (endpoint tests patch `routers.research.run_pipeline`)
- [x] Run /review

### Slice 5: Unauthenticated endpoint limits and PKCE store caps
- [x] Write failing tests: per-IP sliding window on `/auth/*` and overall (injected clock, no real sleeps; patch the module's own `time`); `X-Forwarded-For` honored only through the proxy-headers path; both verifier stores capped with oldest-first eviction; a flood cannot evict an entry younger than the newest N; concurrent access under the lock
- [x] `services/rate_limit.py` and middleware wiring in `main.py`; hard cap in `services/google_auth.py`
- [x] Run /review

### Slice 6: CORS tightening, log hygiene, size limits
- [x] Write failing tests: preflight from `FRONTEND_URL` allowed; other origin gets no allow-origin; no `Access-Control-Allow-Credentials`; methods/headers restricted
- [x] `main.py` CORS change
- [x] Log-hygiene test: unique markers in resume, JD, company and interviewer never appear in captured logs on success, node error and timeout (extend the existing JD log test); a forced Supabase error whose message carries a marker on the save-resume path is not logged with the marker (fix `research.py` to log the class only if the test fails)
- [x] Confirm `job_description` 12,001 chars still gives 422 without echo (existing test), no change expected
- [x] Run /review

### Slice 7: Container and proxy files
- [x] `backend/.dockerignore` (excludes `.env*`, `venv/`, `evals/cache/`, `evals/results/`, `tests/`, caches)
- [x] `backend/Dockerfile` (Python 3.12 slim, non-root user, `--workers 1 --proxy-headers --no-access-log`, `HEALTHCHECK` on `/health`); requirements split into `requirements-runtime.txt` **only if Q4 is yes**, after a grep proves nothing in `agents/ services/ routers/` imports the dropped packages
- [x] `deploy/docker-compose.prod.yml` (services `api` and `caddy`, `env_file: /etc/prepagent/backend.env`, no published `api` port, log rotation `max-size 10m` `max-file 3`, `restart: unless-stopped`, image tag from `IMAGE_TAG`)
- [x] `deploy/Caddyfile` (`api.{$DOMAIN}`, `request_body { max_size 512KB }`, query-stripped access log, redaction check noted)
- [x] `deploy/deploy.sh` (pull, build tagged by SHA, refresh env, `up -d`, wait healthy, run quick smoke, keep last 3 images) and `deploy/render-env.sh` (SSM to env file, mode 0600, never echoes values)
- [ ] `docker build` locally with a decoy `backend/.env` containing a marker, then confirm the marker is absent from the image (local, free, makes no cloud call)
- [x] `deploy/RUNBOOK.md` (Part B below, as a checklist)
- [x] Run /review

### Slice 8: Frontend
- [x] Write failing vitest: `lib/api.ts` throws in production when `NEXT_PUBLIC_API_URL` is unset, falls back to localhost in development; the 429, 503 and 403 messages on `/prep/new` and sign-in error
- [x] `lib/api.ts` single constant; replace the six `|| "http://localhost:8000"` fallbacks (`app/page.tsx`, `app/auth/callback/page.tsx`, `app/prep/new/page.tsx`, `app/prep/[id]/page.tsx`, `app/dashboard/page.tsx`, `lib/calendar.ts`)
- [x] Hide the calendar panel when the backend reports calendar disabled
- [x] Security headers in `next.config.ts` (CSP in Report-Only first)
- [x] `.env.local.example`: `NEXT_PUBLIC_API_URL` only, unless something reading `NEXT_PUBLIC_SUPABASE_*` is found
- [x] `npm run lint`, `npx tsc --noEmit`, `npm test`, `npm run build`
- [ ] Manual browser check (backend + frontend running): cap message, kill-switch message, normal flow still works. Tick only if actually done; otherwise state it is unverified
- [x] Run /review

### Slice 9: Docs
- [x] README: Deployment section (draft in spec section 9) and the tech-stack line (replace "planned"; correct the "Docker Compose built" claim, since the root file is empty)
- [x] `CLAUDE.md` current state and gotchas (`--workers 1` and why, `APP_ENV=production` guard, kill-switch env names, caps, no dev JWT fallback in production, `.dockerignore`)
- [ ] `/why` entry in `docs/decisions.md` (Docker + Caddy on one small instance, app-level caps over edge limits, Testing mode as the invite list)
- [x] Run /review

## Part B: operator runbook (owner does these by hand, after approval; every step marked $ creates or bills a resource)

Nothing here is run by an agent. Do the steps in order; stop and ask before anything that is not in the spec.

### B1. Accounts and limits first (no spend yet)
- [ ] Decide Q1-Q12 in the spec
- [ ] Create **production** API keys for Anthropic, OpenAI, Tavily (separate from the laptop `.env`); set a monthly spend limit or credit cap on each before the key is used anywhere
- [ ] Supabase: create or choose the production project; apply migrations `002`-`007` as needed (`006` required for the chunk writer, `007` optional); note the plan and backup behavior
- [ ] Generate `JWT_SECRET` (random, at least 32 bytes) and `TOKEN_ENCRYPTION_KEY` (Fernet); store a copy of the Fernet key in a password manager

### B2. Domain and Google ($ domain)
- [ ] $ Register or choose a domain; decide `app.` and `api.` hostnames
- [ ] Google Cloud: create the production OAuth client; redirect URIs `https://<frontend-origin>/auth/callback` and `/calendar/callback`; consent screen fields; add test users (Testing mode) per Q1; enable the Calendar API if Calendar is used; keep localhost URIs on a separate dev client
- [ ] (Later, separate effort) Calendar scope verification: domain verification, privacy policy, homepage, demo video

### B3. AWS ($ EC2, EBS, public IPv4)
- [ ] IAM role for the instance: `AmazonSSMManagedInstanceCore` plus read on `/prepagent/prod/*` SSM parameters only
- [ ] SSM Parameter Store: one SecureString per backend variable under `/prepagent/prod/` (values from a file or stdin, never an argument)
- [ ] $ Launch `t3.micro` (x86_64, us-east-2), Amazon Linux 2023, 10 GB gp3, CPU credits standard, 2 GB swap file, IMDSv2 required, role attached, security group 80/443 only (no 22 unless Q9 says so)
- [ ] $ Allocate and attach an Elastic IP; DNS `A` record `api.<domain>` to it
- [ ] Install Docker and the Compose plugin; enable unattended security updates; clone the repo at the release SHA

### B4. First backend deploy (invite-only)
- [ ] Render the env file (0600, root) with `APP_ENV=production`, `FRONTEND_URL=https://<frontend-origin>`, `SIGNUPS_ENABLED=false`, `ALLOWED_EMAILS=<owner>`, caps set, `LANGSMITH_TRACING` off (Q6)
- [ ] `deploy/deploy.sh`; wait for `healthy`; confirm Caddy obtained the certificate
- [ ] Uptime monitor on `https://api.<domain>/health` (free tier)

### B5. Vercel (Hobby is $0; Pro $20/mo)
- [ ] Import the repo, Root Directory `frontend`, Node 20, production branch `main`
- [ ] Production env var `NEXT_PUBLIC_API_URL=https://api.<domain>`; custom domain; redirect other hostnames to it; Deployment Protection on for previews
- [ ] Deploy; confirm the build did not fall back to localhost

### B6. Smoke test and open up
- [ ] Run the spec's smoke checklist (items 1-12); record the measured cost of one briefing in the spec and re-derive the caps (Q3, Q12)
- [ ] Rehearse rollback once: deploy a throwaway tag, then roll back to the previous SHA; do the Vercel instant rollback once
- [ ] Loosen `SIGNUPS_ENABLED`/`ALLOWED_EMAILS` to the intended audience only after the checks pass
- [ ] Put the live URL into the README (replace the placeholders)

### B7. Standing operations
- [ ] Calendar in Testing mode: users reconnect weekly (refresh tokens expire after 7 days)
- [ ] Watch provider usage dashboards for the first week; re-check the caps against real cost
- [ ] Rotation drill for one low-risk key (for example Tavily) to prove the SSM-to-restart path works before it is needed in an incident

## Done checklist
- [x] All acceptance criteria have passing tests (Slices 1-8) or a passed smoke item (Part B6)
- [x] `pytest -x -q` passes
- [x] `ruff check` clean (on changed files only)
- [x] mypy clean (`mypy . --ignore-missing-imports --cache-dir=/dev/null --no-sqlite-cache` from `backend/`)
- [ ] Frontend lint, `tsc`, `npm test`, `npm run build` pass, and the browser check is either done or reported as unverified
- [x] /review returns APPROVE and each slice's "Run /review" box was ticked only if a review actually ran
- [x] Reviewer agent returns APPROVE
- [x] No change to `backend/.env`, the root `docker-compose.yml` or `.github/workflows/ci.yml`
- [ ] /commit with a conventional commit message, no Co-Authored-By

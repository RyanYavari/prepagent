# Spec: Deployment (backend on AWS EC2, frontend on Vercel)

Status: **approved with the answers below; repo changes (Slices 1-8) built on branch `deploy/prod-readiness`.** No cloud resource exists, and no `.env`, root `docker-compose.yml` or CI file has been touched. The operator runbook (Part B) is done by the owner by hand. Facts about this repo are from reading the code on 2026-11-15. Facts about AWS, Vercel, Google and Supabase pricing and policy are from general knowledge, are marked **(confirm)**, and must be checked in the vendor console before anyone relies on them.

## Problem
PrepAgent only runs on localhost. The backend has no Dockerfile (the root `docker-compose.yml` is an empty file, although the README lists Docker Compose as built), no production config guard, no rate limit or spend cap on briefing creation, and no way to switch signups off. Put on a public URL as-is, anyone with a Google account could sign in and run the Anthropic, OpenAI and Tavily pipeline until the keys are empty.

## Goal
A public deployment (Vercel frontend, one small EC2 instance behind HTTPS for the backend) where a bounded, reviewable amount of money can be spent, signups can be switched off in under a minute, no secret or personal text reaches a log, and a bad release can be rolled back.

## Non-goals
- Multi-instance or multi-worker scaling, load balancers, autoscaling, ECS/EKS/Lambda.
- Terraform/CloudFormation (the runbook is manual; revisit if a second environment is wanted).
- Changing auth to cookies, adding refresh tokens or JWT revocation (accepted risk, see Frontend).
- Moving the PKCE store to a shared store (not needed at one worker; see Single-process constraint).
- Gmail/Drive, new product features, changes to the research pipeline or prompts.
- Google OAuth app verification itself (this spec says what it takes and what stays in Testing; doing it is a separate effort).
- Creating any cloud resource, buying a domain, or spending money as part of writing this spec. Every step that costs money is in the operator runbook, run by the owner after approval.

## Repo facts this design rests on
- `services/google_auth.py`: PKCE verifiers live in two process-local dicts (`_pending_verifiers` for sign-in, `_pending_calendar` for calendar connect), TTL 600 s, guarded by a `threading.Lock`. The file's own comment says multiple workers need a shared store.
- `routers/auth.py` and `dependencies/auth.py` both fall back to `JWT_SECRET="dev-secret-change-me"` when the variable is unset. In production that is a silent forged-token hole.
- `main.py`: CORS is one origin (`FRONTEND_URL`, default `http://localhost:3000`) with `allow_credentials=True` and `*` methods/headers. FastAPI `/docs` and `/openapi.json` are on. `/health` is static (no dependency check).
- There is **no rate limiting, no per-user cap and no signup gate** anywhere. `POST /briefings` runs up to 2 Tavily-backed agents, 3 Claude calls and (when `resume_text` is sent) an OpenAI embedding pass, for any holder of a valid JWT. A new Google account is a new user.
- `GET /auth/google` stores one verifier per call with no size cap and no auth, so unauthenticated callers can grow process memory (bounded only by the 10-minute purge).
- Handlers in `routers/research.py` and `routers/calendar.py` are `async def` but call the synchronous Supabase client and, for `POST /briefings` with a resume, a synchronous OpenAI embedding call (timeout 15 s, up to 2 retries). Under one worker such a call blocks the event loop, so `/health` and every other request stall while it runs.
- Frontend: JWT in `localStorage`, sent as a Bearer header; `NEXT_PUBLIC_API_URL` is read in six files with a silent fallback to `http://localhost:8000`. `NEXT_PUBLIC_SUPABASE_*` appear in `.env.local.example` but no frontend source reads them (confirm before dropping).
- Backend limits already present: `company/interviewer/role` 200 chars, `resume_text` 50,000, `job_description` 12,000 (422, never echoed, never stored or logged), per-call timeouts and `PIPELINE_DEADLINE_SECONDS=120`.
- `requirements.txt` includes eval-only and unused packages (`ragas`, `datasets`, `pandas`, `pyarrow`, `pyiceberg`, `scipy`, `cohere`, `pinecone-client`). That inflates the image and resident memory on a small box.
- Env vars the backend reads: `SUPABASE_URL`, `SUPABASE_SERVICE_KEY`, `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `TAVILY_API_KEY`, `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `FRONTEND_URL`, `JWT_SECRET`, `TOKEN_ENCRYPTION_KEY`, plus optional `AGENT_MODEL`, the `*_TIMEOUT_SECONDS`/`*_MAX_RETRIES` family, `CALENDAR_*`, `LANGSMITH_*`. `.env.example` is stale (lists Cohere/Pinecone, omits `TOKEN_ENCRYPTION_KEY`).

## Decisions

### 1. Backend runtime: Docker Compose on one EC2 instance, Caddy in front
Chosen (revised 2026-11-16 for the AWS Free plan, see the tailoring note below): **one `t3.micro` (2 vCPU burstable x86_64, 1 GB) in `us-east-2`, Docker Compose with two services, `api` (uvicorn) and `caddy`**, EBS gp3 **10 GB**, a **2 GB swap file**, CPU credits in **standard** mode, an Elastic IP, domain `useprepagent.app` with an `A` record for `api.useprepagent.app`. (The original pick was a `t4g.small`, 2 GB ARM, 20 GB.) Caddy gets and renews the Let's Encrypt certificate itself (no certbot, no cron), redirects HTTP to HTTPS, and proxies to `api:8000` on the Docker network. The `api` port is not published to the host.

| Option | Cost vs the pick | Verdict |
|---|---|---|
| Docker + Caddy (pick) | baseline; ~100-150 MB extra RAM for the Docker daemon | Pinned Python 3.12, rollback is "start the previous image tag", config is a file in the repo |
| systemd + venv + Caddy/nginx | same instance price, a little less RAM | Cheapest by a rounding error, but Amazon Linux's default Python is not 3.12, deploys are `git pull` + `pip install` on the live box, and rollback is manual. Acceptable fallback if memory is tight |
| nginx instead of Caddy | same | nginx has `limit_req` built in and Caddy's stock build does not; but certificate handling is manual. See the rate-limit decision: limits live in the app, so Caddy wins on simplicity |
| `t4g.small` (2 GB ARM), the original pick | ~$4.7/mo more | Comfortable memory, but an ARM image (the build runs on the instance, so no cross-build, but Compose plugin and wheels must be aarch64) and it does not fit six months of the $100 credits next to everything else |
| `t3.micro` (1 GB), **now chosen** | baseline | The earlier objection (eval-only dependencies in the image) is gone: Q4 was done, `requirements-runtime.txt` is the image set. Risks accepted: ~700 MB resident at idle with Docker, Caddy and the SSM agent, so a 2 GB swap file is part of the setup; unlimited-mode CPU credits must be switched to standard; heavy swapping would look like the earlier "hung on running" incident, so the smoke test times one briefing and watches swap. Fallback if it is not enough: `t3.small` (also Free-plan eligible **(confirm)**, about +$7.6/mo) |

Build on the instance (`docker build`, image tagged with the git SHA, previous tag kept). No registry and no CI changes. On a `t3.micro` the first build takes several minutes (burstable CPU, swap in use); the runtime-only requirements keep it far smaller than the full set. Disk is 10 GB: Amazon Linux ~2.5 GB, swap 2 GB, images and build cache ~3 GB, so run `docker builder prune -f` after deploys and watch `df -h /`.

`uvicorn main:app --host 0.0.0.0 --port 8000 --workers 1 --proxy-headers --forwarded-allow-ips="*"` (the `*` is safe only because the container port is reachable only from Caddy on the Docker network). No `--reload`. Docker `HEALTHCHECK` hits `GET /health` (static, no Supabase/LLM calls, so health checks cost nothing). An external uptime monitor (free tier) hits `https://api.<domain>/health` every 5 minutes. `restart: unless-stopped`. json-file log driver with `max-size: 10m`, `max-file: 3` (the default has no rotation and will fill the disk).

Security group: 80 and 443 from anywhere; **no 22**. Shell access through AWS Systems Manager Session Manager (the instance role gets `AmazonSSMManagedInstanceCore`); if SSH is preferred, 22 from the owner's IP only (Q9). IMDSv2 required. Unattended security updates on.

Production hardening that goes with this: `docs_url=None, redoc_url=None, openapi_url=None` when `APP_ENV=production`.

### 2. Single-process constraint
**`--workers 1` is required.** The two PKCE verifier stores (and the in-app rate limiter added below, and the optional calendar poller) are process-local.

What breaks with 2+ workers: `GET /auth/google` runs in worker A and stores the verifier there; Google redirects back; `GET /auth/callback` lands on worker B, `pop_code_verifier` raises `InvalidOAuthStateError`, and the user gets "Invalid or expired OAuth state" roughly half the time with N=2 (`1 - 1/N`). Calendar connect fails the same way. Rate limits would be per worker (N times the cap). The poller, if enabled, would run N times (harmless, wasteful).

What also breaks at one worker, and is accepted:
- A restart or deploy drops in-flight OAuth attempts (10-minute window); users just click sign-in again.
- A restart kills running background pipelines. Rows stuck on `running` are failed by the existing startup sweep after `STALE_RUNNING_MINUTES` (10); a row still `pending` is **not** swept (known gap). The deploy step checks for `running`/`pending` rows first and the runbook says when to wait.

Event-loop blocking is the real one-worker risk (see repo facts). Fix in scope: convert the handlers that do blocking Supabase/OpenAI calls from `async def` to `def` so FastAPI runs them in its thread pool. The verifier stores already use a `threading.Lock`, so this is safe. A startup assertion logs a warning if `WEB_CONCURRENCY` or `UVICORN_WORKERS` is set above 1.

Moving to more than one worker later means: a Supabase table (or Redis) for verifiers, and a shared rate-limit store. Out of scope here.

### 3. Configuration and secrets
Principle: secrets live in **AWS SSM Parameter Store (SecureString, standard tier, no cost)** under `/prepagent/prod/`, are read by the instance role at deploy time, and are rendered into a root-owned `0600` file **outside the repo** (`/etc/prepagent/backend.env`) that Compose passes with `env_file`. Never in the git repo, the image, Vercel's browser bundle, a command-line argument, or a log.

Rules:
- A new `backend/.dockerignore` excludes `.env*`, `venv/`, `evals/cache/`, `evals/results/`, `tests/`, `__pycache__`. Today `backend/.env` holds real credentials and there is no `.dockerignore`, so a naive `COPY . .` would bake them into the image. A test/CI-free check (`docker run --rm <image> sh -c 'ls -a /app | grep -c "^\.env"'` returns 0) is part of the smoke checklist.
- Put values into SSM from a file or stdin (`--value file://`), never as a command-line argument (shell history, process list).
- Do not run `docker compose config` or `docker inspect` on the box and paste the output anywhere: both print resolved env values.
- Use **separate production credentials** from the ones in the laptop `.env`: new Anthropic, OpenAI and Tavily keys (each with a provider spend limit, see Cost controls), a separate Google OAuth client, a freshly generated `JWT_SECRET` and `TOKEN_ENCRYPTION_KEY`, and (recommended, Q5) a separate Supabase project.
- Startup validation (`APP_ENV=production`): refuse to start (log the names of the failing variables, never values) if any required variable is missing, if `JWT_SECRET` is empty, shorter than 32 characters or equals the dev default, if `TOKEN_ENCRYPTION_KEY` is not a valid Fernet key, or if `FRONTEND_URL` is not `https://`, has a trailing slash, or is localhost. In non-production the current behavior is unchanged.
- LangSmith tracing off in production at launch (Q6): with it on, resume text and job description text go to a third party.

| Secret | Where it matters | Rotation |
|---|---|---|
| `JWT_SECRET` | signs/validates sessions | Change, restart. Every user is signed out (JWTs last 7 days and have no revocation). This is also the emergency "log everyone out" lever |
| `TOKEN_ENCRYPTION_KEY` | Fernet key for stored calendar refresh tokens | `token_crypto.py` supports one key only. Changing it makes every stored token undecryptable (users must reconnect Calendar). Zero-downtime rotation needs `MultiFernet` and re-encryption (not in scope; flagged Q8). Back the key up outside the server, since losing it has the same effect |
| `SUPABASE_SERVICE_KEY` | bypasses RLS, full DB access: the most dangerous key here | Rotate per the Supabase dashboard (which mechanism depends on the project's key system) **(confirm)**. Backend only, never in Vercel |
| `GOOGLE_CLIENT_SECRET` | OAuth code exchange | Google lets a client hold two secrets: add the new one, deploy, disable the old |
| `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `TAVILY_API_KEY` | spend | Create new, update SSM, redeploy, revoke old. Also the response to any suspected leak or cost spike |

Rotation runbook (per secret): update the SSM parameter, run the deploy script's "refresh env" step (re-render the file, `docker compose up -d` recreates the container), run the smoke checks for the affected feature, then revoke the old value at the provider.

### 4. Google OAuth
Plainly:

**What is required for production regardless of verification:** an OAuth client of type Web application whose authorized redirect URIs are exactly `https://<frontend-domain>/auth/callback` and `https://<frontend-domain>/calendar/callback` (the backend builds both from `FRONTEND_URL`, so `FRONTEND_URL` must be the exact canonical frontend origin, no trailing slash, and one origin only). Consent screen needs app name, support email, developer contact email; for publishing also a homepage and privacy-policy URL on an authorized domain **(confirm)**. Keep `localhost` URIs out of the production client; use a separate dev client.

**Sign-in scopes** (`openid`, `userinfo.email`, `userinfo.profile`) are non-sensitive **(confirm)**: the app can be set to "In production" for them without Google's sensitive-scope verification. No refresh token is minted at sign-in and none is stored.

**The Calendar scope** (`calendar.events.readonly`) is sensitive **(confirm)**. Using it for the general public requires Google OAuth verification: a verified domain you own, a privacy policy and homepage on it, a scope justification, and a demo video. Expect days to weeks and possible back-and-forth. The repo has none of those yet, and `*.vercel.app` is on the public suffix list so it cannot serve as the authorized/verified domain **(confirm)**: a custom domain is effectively required.

**What stays in Testing mode until then:** a Google Cloud project is either Testing or In production as a whole, not per scope. In Testing mode only listed test users (up to 100) can sign in, the consent screen shows an "unverified app" warning, and refresh tokens (so Calendar connections) expire after 7 days, already noted in CLAUDE.md. In production-unverified, any Google user can sign in, a sensitive scope shows the warning screen and the project is capped at 100 users for that scope **(confirm)**.

Recommendation (Q1): **launch in Testing mode with the owner's allowlist.** It is a Google-enforced invite list, it doubles as a signup kill switch (remove a test user), and Calendar works with a weekly reconnect. Publish to production (sign-in only, Calendar hidden behind a `CALENDAR_ENABLED=false` flag, added in this spec) only if a truly open signup is wanted, and start Calendar verification as its own follow-up spec. In both modes the app-level caps below still apply, because test users can still spend credits.

### 5. Frontend on Vercel
- Project: import the repo, **Root Directory `frontend`**, framework Next.js, Node 20 (matches CI), install `npm ci`, build `npm run build`, **production branch `main`** (day-to-day work is on `dev`).
- Env var, **Production scope only**: `NEXT_PUBLIC_API_URL=https://api.<domain>` (no trailing slash). `NEXT_PUBLIC_*` values are inlined into the browser bundle at build time: never put a secret in one, and changing it needs a redeploy. Do not set `NEXT_PUBLIC_SUPABASE_*` unless something is found that uses them.
- Silent localhost fallback: the six `|| "http://localhost:8000"` fallbacks mean a Vercel build with the variable missing ships a site that calls localhost. Fix in scope: one `lib/api.ts` constant that throws at build/start in production when unset, used by all six files.
- Preview deployments: their `*.vercel.app` URLs are not in CORS and not in Google's redirect URIs, so sign-in cannot work on them. Leave Vercel's Deployment Protection on for previews, or turn previews off. Not supported, by design.
- Custom domain: the **apex `useprepagent.app`** is the canonical origin (`www.useprepagent.app` redirects to it); redirect any other hostname (including `*.vercel.app`) to it, because CORS and Google both accept exactly one origin (Q2).
- Security headers via `next.config.ts` `headers()`: `X-Content-Type-Options: nosniff`, `Referrer-Policy: strict-origin-when-cross-origin` (the OAuth `code` is in the callback page URL), `X-Frame-Options: DENY`, and a CSP whose `connect-src` is `'self' https://api.<domain>` (CSP rollout needs a browser pass; Report-Only first).
- Vercel Hobby is for personal, non-commercial use **(confirm)**; Pro is $20/mo if this stops being a portfolio project.

**CORS and token handling.** The session is a Bearer token in `Authorization`, stored in `localStorage`; there are no cookies, so no `SameSite`, CSRF or cookie-domain questions and `allow_credentials=True` is unnecessary. Change to: `allow_origins=[FRONTEND_URL]` (unchanged, single origin), `allow_credentials=False`, `allow_methods=["GET","POST","DELETE","OPTIONS"]`, `allow_headers=["Authorization","Content-Type"]`. Verify by preflight from the real origin (allowed) and from another origin (no `Access-Control-Allow-Origin`).

Accepted risk, stated rather than fixed: a `localStorage` token is readable by any XSS, lasts 7 days and cannot be revoked per user (only `JWT_SECRET` rotation signs everyone out). The CSP above and the app's existing output handling (briefing text is rendered through `parseCitations`, http/https links only) are the mitigation. Moving to HttpOnly cookies would change CORS, CSRF and the whole auth flow, and is a separate spec if wanted.

### 6. Cost controls
Goal: no sequence of requests, from one user or many, can spend more than a number the owner picked.

**A. Provider hard limits (outside the app, set first, strongest).** Monthly spend limits on the Anthropic and OpenAI organizations and a plan/credit cap on Tavily. These are the backstop if the app-level controls have a bug. (Console setup is a runbook step; exact limit features vary by provider **(confirm)**.)

**B. Per-user cap, in the app.** In the shared `create_pending_briefing` helper (so calendar-created briefings count too, Q3) and *before* the resume embedding step in `POST /briefings`:
- rolling 24 h cap `MAX_BRIEFINGS_PER_USER_PER_DAY` (proposed default **5**);
- concurrency cap `MAX_ACTIVE_BRIEFINGS_PER_USER` of `pending`+`running` rows (default **2**);
- both counted from the `briefings` table (one indexed count query: `user_id`, `created_at`/`status`), so they hold across restarts and need no new table. Not atomic (two simultaneous requests can both pass); the overshoot is bounded by concurrent requests and accepted.
- Over the cap: `429` with `Retry-After` and a generic message (`{"detail": "Daily briefing limit reached"}`), no counts of other users, nothing logged beyond user id and event name.

**C. Global cap.** `MAX_BRIEFINGS_GLOBAL_PER_DAY` (proposed default **40**): the same count without the user filter, over the last 24 h. This is the number that turns a worst case into arithmetic: daily worst-case LLM spend = `global cap x measured cost per briefing` (cost per briefing is **unmeasured**; see Estimated cost). Existing users hit it too, which is the intended behavior.

**D. Unauthenticated endpoints.** `GET /auth/google` and `GET /auth/callback` need no JWT, and `/auth/google` grows the verifier dict. In-app sliding-window limiter per client IP (valid because there is one worker): proposed 20 requests/min/IP on `/auth/*`, 60/min/IP overall; a hard cap (e.g. 5,000) on live entries in each PKCE store, evicting the oldest. Client IP comes from `--proxy-headers`; Caddy overwrites `X-Forwarded-For`, and the limiter trusts it only because the app is not reachable except through Caddy.

**E. Kill switches** (env flags read at call time, no code change to flip, container recreate ~10 s):
- `SIGNUPS_ENABLED` (default `true`): when `false`, `/auth/callback` signs in existing users but returns `403` for an email with no `users` row, before any insert.
- `ALLOWED_EMAILS` (optional comma list): when set, only these emails may sign in or sign up (a code-side invite list that works in both Google modes).
- `BRIEFINGS_ENABLED` (default `true`): when `false`, `POST /briefings` and calendar confirm return `503`, existing briefings stay readable.
- `CALENDAR_ENABLED` (default `true`): when `false`, calendar routes return `404`/`503` and the frontend hides the panel.
- Emergency order, fastest first: (1) `BRIEFINGS_ENABLED=false`; (2) revoke the Anthropic/OpenAI key; (3) `docker compose stop api`; (4) rotate `JWT_SECRET` (signs everyone out); (5) remove test users in Google Console / Vercel "pause project".

Frontend: `/prep/new` shows a plain message for `429` and `503` (new copy), and the existing sign-in error page shows the `403`.

### 7. Abuse and safety
- **Request size.** Caddy `request_body { max_size 512KB }` on the API site. Basis: `resume_text` 50,000 + `job_description` 12,000 characters is up to 248 KB as UTF-8 (4 bytes/char worst case) and about 372 KB if a client `\u`-escapes every non-ASCII character; 512 KB covers both with headroom. Pydantic limits stay the semantic cap; Caddy stops big bodies before they are parsed. Oversize returns 413.
- **JD cap.** Confirm, not change: 12,000 characters, over the limit is 422 and never truncated, the 422 body never echoes the JD (`main.py` handler), the JD is never stored, logged, put in run metadata or embedded. A deployment smoke check re-asserts the 422 and the non-echo against the live URL with a marker string.
- **Timeouts and deadlines** already bound each call and the whole run (`net_config`, `PIPELINE_DEADLINE_SECONDS=120`); the deployment sets none of them differently.
- **Logs: no secrets or personal text.** Static review found log calls that carry ids, counts, node names and exception classes; `retry_call` logs the class only. Gaps this spec closes or must verify:
  1. Access logs include the request line. `GET /auth/callback?code=...&state=...` would put the OAuth code and state in uvicorn's and Caddy's access logs. The code is single-use and PKCE-bound, but treat it as sensitive: run uvicorn with `--no-access-log` and configure Caddy's log to drop the query string (and keep its default redaction of `Authorization`/`Cookie` headers, **confirm for the Caddy version used**).
  2. `logger.exception` records tracebacks. A database error message can echo the failing row (Postgres "Failing row contains ..." detail), which for a `users.resume_text` update would contain resume text **(plausible, verify)**. Task: a test that forces a Supabase error carrying a marker in `routers/research.py`'s save-resume path and asserts the marker is absent from captured logs; if present, log the exception class only on that path.
  3. Client IPs are personal data in Caddy logs; keep retention short (Docker rotation above, no shipping logs elsewhere).
  4. LangSmith (see Config).
  5. A runtime check in the smoke checklist: submit a briefing with unique markers in resume, JD, company and interviewer, then `grep` the container and Caddy logs for each marker. Must find none.
- **Misc hardening.** `/docs` and OpenAPI off in production; Docker `api` container runs as a non-root user with a read-only root filesystem where practical; no published port other than Caddy's 80/443.

### 8. Rollout, smoke test, rollback
**Order:** (1) merge this spec's code changes to `main` after `pytest -x -q` and review; (2) apply Supabase migrations `006` (required for the chunk writer) and `007` (optional) to the **production** Supabase project, plus `002`-`005` if it is a fresh project; (3) provision AWS (runbook); (4) domain DNS; (5) put secrets in SSM; (6) first deploy of the backend with `SIGNUPS_ENABLED=false` and `ALLOWED_EMAILS=<owner>`; (7) Google client + consent screen (Testing mode); (8) Vercel project and env var; (9) smoke checklist; (10) open to the intended audience by loosening the flags; (11) README live URL.

**Smoke-test checklist (run after every backend deploy; items 1-6 on every release, the rest at first launch and after config changes):**
1. `https://api.<domain>/health` returns `{"status":"ok"}` over a valid certificate; `http://` redirects to `https://`; `/docs` and `/openapi.json` return 404.
2. CORS: preflight from the Vercel origin allows it; from `https://example.com` it does not.
3. Sign in with the owner account through the real frontend; land on the dashboard.
4. Create a briefing without a JD; viewer polls to `complete`; sections render.
5. Create one with a JD; `[JD]` chip shows; a 12,001-char JD returns 422 without echoing it; a body over 512 KB returns 413.
6. Log check: markers in company/JD/resume do not appear in `docker compose logs api` or Caddy's log; the `/auth/callback` line has no `code=`.
7. Caps: from a scratch user (or temporarily lowered limits), hit the per-user cap and see `429` + `Retry-After`; the frontend shows the message.
8. Kill switches: `BRIEFINGS_ENABLED=false` gives 503; `SIGNUPS_ENABLED=false` refuses a new email and still lets the owner in.
9. Restart the container mid-flow: the app comes back healthy, the startup sweep logs, in-flight sign-in fails cleanly and retries.
10. Calendar (only if enabled): connect, sync, disconnect (needs the test-user listing in Testing mode).
11. Cost check: after item 4, read the Anthropic/OpenAI/Tavily usage for that one briefing and record it in the spec's cost table (this replaces the unmeasured number).
12. `docker run --rm <image> sh -c 'ls -a /app | grep "^\.env"'` prints nothing; the instance has no inbound 22 (or only the owner's IP).

**Deploy:** on the box, `git pull`, `docker build -t prepagent-api:<sha> backend`, refresh env from SSM, `docker compose up -d`, wait for `healthy`, run smoke items 1-6. Before restarting, `select count(*) from briefings where status in ('pending','running')`; if non-zero, wait or accept that those runs fail.

**Rollback:** backend: set the compose image tag back to the previous SHA and `docker compose up -d` (the previous image is kept; keep the last 3). Migrations in scope (006, 007) are additive, so the previous code runs against the new schema; no down-migrations. Config rollback: SSM parameter history keeps previous values; re-render and recreate. Frontend: Vercel "Instant Rollback" to the previous production deployment. If rollback does not help, apply the emergency order in 6E. Data: the Free Supabase plan has no point-in-time recovery **(confirm)**; Q5.

### 9. README Deployment section (to be added on build; draft)
```markdown
## Deployment

Live: https://<LIVE_URL_PLACEHOLDER> (frontend on Vercel) · API: https://api.<DOMAIN_PLACEHOLDER>/health

- **Backend:** one EC2 instance running Docker Compose (FastAPI under uvicorn with a single worker, Caddy for HTTPS). The single worker is required: the OAuth PKCE verifier store is in memory.
- **Frontend:** Vercel, root directory `frontend`, `NEXT_PUBLIC_API_URL` set for Production.
- **Secrets:** AWS SSM Parameter Store, rendered to a root-only env file on the server; never committed.
- **Access:** the app runs in Google OAuth Testing mode (invite list); per-user and global daily briefing caps and signup kill switches limit spend.
- Full design, smoke checklist and rollback: [specs/deployment.md](specs/deployment.md); operator steps in `deploy/RUNBOOK.md`.
```

## Deployment tailoring (2026-11-16)
The owner's concrete choices, applied to the runbook (`deploy/RUNBOOK.md`, now written as the Part B checklist with cost and verification per step):
- Domain `useprepagent.app`; frontend on the **apex** (`FRONTEND_URL=https://useprepagent.app`, Google redirect URIs `https://useprepagent.app/auth/callback` and `/calendar/callback`), `www` redirects to it; API `https://api.useprepagent.app`.
- AWS Free plan, $100 credits, plan ends 16 May 2027 **(confirm)**; one region, `us-east-2`; `t3.micro` x86_64, 10 GB gp3, 2 GB swap file, CPU-credit mode **standard** (T3 launches unlimited by default, which can bill surplus credits). No code or script change was needed: `Caddyfile` and `docker-compose.prod.yml` take the domain from `DOMAIN`, and nothing pins an architecture.
- Region changed from `us-west-2` to **`us-east-2` (Ohio)** on 2026-11-16 because the owner's AWS project is fixed to Ohio. Prices used here (t3.micro $0.0104/h, gp3 $0.08/GB-month, public IPv4 $0.005/h) are the same in both regions as far as general knowledge goes **(confirm)**. `render-env.sh` now passes the region explicitly, since the AWS CLI on EC2 does not necessarily infer it.
- Teardown checklist added (runbook section 12), because the Free plan closes the account at its end and an Elastic IP or detached volume left behind keeps billing.
- **Gap found while tailoring: no migration creates `users` or `briefings`** (`supabase/migrations` starts at `002` and references them). A new production Supabase project cannot be built from `002`-`007` alone; the runbook says to take a schema-only dump of the dev project and apply it first. Fixing this properly (a committed `001_base_schema.sql`) is a separate change.
- Still unverified: everything in the runbook, the Docker build on a 1 GB instance, memory and swap behaviour under a pipeline run, and the disk budget on 10 GB.

## Estimated monthly cost
Fixed infrastructure (US region list prices, approximate, **confirm** with the AWS calculator, taxes excluded):

| Item | Free-tier Supabase + Vercel Hobby | With Supabase Pro |
|---|---|---|
| EC2 `t3.micro` on-demand, us-east-2 (was `t4g.small` ~$12.3) | ~$7.6 | ~$7.6 |
| EBS gp3 10 GB (was 20 GB ~$1.6) | ~$0.8 | ~$0.8 |
| Public IPv4 / Elastic IP | ~$3.7 | ~$3.7 |
| Data transfer, SSM parameters, Let's Encrypt, uptime monitor, Caddy | $0 | $0 |
| Domain (~$10-15/yr) | ~$1 | ~$1 |
| Route 53 hosted zone (skip if registrar DNS is used) | ~$0.5 | ~$0.5 |
| Vercel Hobby | $0 | $0 (Pro $20) |
| Supabase | $0 (pauses after inactivity, small DB) | $25 |
| **Fixed total** | **about $13-14** (was $19-20) | **about $38-39** (was $44-45) |

The `t3.micro` saves about $4.7/mo against the original `t4g.small` pick (Decision 1, revised). On the AWS Free plan ($100 credits, ends 16 May 2027 **(confirm)**) the infrastructure is about $12-12.5/mo, roughly $75-95 for the six months including the domain, drawn from credits. Reserved or Savings Plan pricing would cut EC2 by ~30-40% for a 1-year commitment and is not worth it for a project that may not live a year.

Variable (LLM/search) cost: **not measured.** The only datapoint in the repo is the README's rough $1.50 for a 4-case eval run including judge calls, which puts generation under about $0.38 per briefing as a loose upper bound. OpenAI embeddings are negligible next to it. Tavily is up to 6 searches per briefing (3 attempts x 2 agents) against a plan whose price and quota are **(confirm)**. So: `monthly variable = briefings/month x measured cost per briefing`, with the worst case hard-capped by Decision 6: `40/day x 30 x measured cost`. With the loose bound that would be 1,200 x $0.38 = about $456/mo, which is why the proposed global cap is a starting number to be re-derived after smoke item 11, and why the provider-side spend limits are set first. A realistic invite-only month is a few dozen briefings.

## Acceptance Criteria

### Given `APP_ENV=production` and `JWT_SECRET` unset, equal to `dev-secret-change-me`, or shorter than 32 characters
### When the backend starts
### Then it refuses to start, logs the names (not values) of every failing variable, and never signs a token with a fallback secret

### Given `APP_ENV=production` and `FRONTEND_URL` is `http://...`, localhost, or ends with `/`, or `TOKEN_ENCRYPTION_KEY` is not a valid Fernet key
### When the backend starts
### Then it refuses to start with the variable names listed

### Given any `APP_ENV` other than production
### When the backend starts with today's `.env`
### Then behavior is unchanged and all existing tests pass

### Given `APP_ENV=production`
### When a client requests `/docs`, `/redoc` or `/openapi.json`
### Then the response is 404, and `/health` still returns 200

### Given a user at `MAX_BRIEFINGS_PER_USER_PER_DAY`
### When they `POST /briefings` (with or without `resume_text`)
### Then the response is 429 with `Retry-After`, no embedding call is made, no row is inserted, and no pipeline is scheduled

### Given a user with `MAX_ACTIVE_BRIEFINGS_PER_USER` rows `pending` or `running`
### When they create another
### Then 429, and after one finishes they can create again

### Given the global daily count is at `MAX_BRIEFINGS_GLOBAL_PER_DAY`
### When any user creates a briefing
### Then 429 with the same generic body, and the body never reveals other users' counts

### Given a calendar detection is confirmed into a briefing
### When the user is at a cap
### Then the same cap applies and the detection stays unconfirmed (nothing is lost)

### Given `BRIEFINGS_ENABLED=false`
### When a user creates a briefing or confirms a detection
### Then 503, and `GET /briefings` and `GET /briefings/{id}` still work

### Given `SIGNUPS_ENABLED=false`
### When an email with no `users` row completes sign-in
### Then 403, no `users` row is inserted; an existing user signs in normally

### Given `ALLOWED_EMAILS` is set
### When an email not on the list completes sign-in
### Then 403 and nothing is inserted; with it unset, there is no allowlist

### Given a single client IP exceeding the `/auth/*` limit
### When it calls `GET /auth/google` again
### Then 429, and the PKCE stores never exceed their hard entry cap (oldest evicted, newest kept)

### Given the PKCE verifier stores
### When `--workers` is greater than 1 is configured via `WEB_CONCURRENCY`/`UVICORN_WORKERS`
### Then a startup warning is logged naming the constraint, and the compose file and docs state `--workers 1`

### Given a Supabase call inside a request handler takes several seconds
### When another request (including `/health`) arrives
### Then it is served concurrently (handlers that do blocking calls are `def`, not `async def`)

### Given a request from `FRONTEND_URL`
### When the browser sends a CORS preflight for `POST /briefings` with `Authorization`
### Then it is allowed; from any other origin no `Access-Control-Allow-Origin` header is returned; `Access-Control-Allow-Credentials` is not sent

### Given a request body over 512 KB
### When it reaches Caddy
### Then 413 and the app never parses it; a body within the limit and over `job_description` 12,000 characters gets 422 that does not echo the JD

### Given unique marker strings in `resume_text`, `job_description`, company and interviewer, including a forced Supabase failure on the resume save path
### When the request is handled
### Then none of the markers appear in application logs, and the `/auth/callback` access-log line contains neither `code=` nor `state=`

### Given the production image
### When it is built from `backend/` with a `.env` present in that directory
### Then the image contains no `.env*` file and none of its values

### Given a Vercel production build with `NEXT_PUBLIC_API_URL` unset
### When the frontend builds
### Then the build fails (no silent localhost fallback in production); in development the fallback still works

### Given `/prep/new` receives 429, 503 or 403
### When the user submits
### Then a specific, non-technical message is shown (this is a frontend change and must be checked in a real browser before it is called done)

### Given the deployed stack
### When the smoke checklist (Decision 8) is run
### Then every item passes, the measured per-briefing cost is recorded, and the rollback steps have been exercised once against a throwaway tag

## Affected Files
Code and docs (built after approval, test-first, in repo; **none exist or are changed by writing this spec**):
- `backend/main.py` (production guard call, docs off, tighter CORS, rate-limit middleware wiring)
- `backend/services/prod_config.py` (new: `validate_production_config`)
- `backend/services/rate_limit.py` (new: in-process per-IP sliding window)
- `backend/services/limits.py` (new: per-user, active and global briefing caps; kill-switch flags)
- `backend/services/briefings.py` (`create_pending_briefing` enforces caps)
- `backend/services/google_auth.py` (hard cap on verifier stores)
- `backend/routers/auth.py` (signup gate, allowlist, drop the JWT fallback in production)
- `backend/dependencies/auth.py` (same fallback removal)
- `backend/routers/research.py`, `backend/routers/calendar.py` (429/503 mapping, `async def` to `def` where blocking)
- `backend/.env.example` (current variable set; remove Cohere/Pinecone)
- `backend/Dockerfile`, `backend/.dockerignore` (new)
- `deploy/docker-compose.prod.yml`, `deploy/Caddyfile`, `deploy/deploy.sh`, `deploy/render-env.sh`, `deploy/RUNBOOK.md` (new; the existing root `docker-compose.yml` is **not** touched)
- `frontend/lib/api.ts` (new, single API base constant), the six files that read `NEXT_PUBLIC_API_URL`, `frontend/app/prep/new/page.tsx` (429/503 messages), `frontend/next.config.ts` (headers), `frontend/.env.local.example`
- `backend/tests/` (new tests per slice), `specs/tasks-deployment.md`
- `README.md` (Deployment section, tech-stack line), `CLAUDE.md` (current state, gotchas), `docs/decisions.md` (/why entry: Caddy + Docker, app-level limits, Testing mode)

Not touched: `backend/.env`, `docker-compose.yml`, `.github/workflows/ci.yml`.

## Dependencies
- Owner-provided: an AWS account, a domain name, Vercel account, a Supabase project for production, new provider keys with spend limits. No agent action creates or pays for any of these.
- Migrations `006` (and optionally `007`) applied to the production Supabase project; for a new project, the base `users`/`briefings` schema first (not in the repo, see the tailoring note), then `002`-`005`.
- Google Cloud: production OAuth client, consent screen configured, redirect URIs for the final frontend origin, Calendar API enabled if Calendar is used.
- Decision on Q1-Q9 below before the matching slice starts.

## Approved answers to the open questions
- **Q1** Google Testing mode with an invite list. **Q2** the owner buys a domain; the spec assumes one (revised: `useprepagent.app` is the frontend, `api.useprepagent.app` the backend; the original wording was `app.<domain>`).
- **Q3/Q12** monthly budget ceiling **$20**; defaults **3 briefings/user/day**, **20/day global**, 2 concurrent per user, all env-configurable (`MAX_BRIEFINGS_PER_USER_PER_DAY`, `MAX_BRIEFINGS_GLOBAL_PER_DAY`, `MAX_ACTIVE_BRIEFINGS_PER_USER`). Calendar-created briefings count. **Caveat the caps cannot fix:** fixed infrastructure alone is about $19-20/mo (table above), and 20/day x 30 days = 600 briefings, which would stay under $20 of LLM spend only if a briefing cost under about $0.033 (unmeasured; the loose upper bound is $0.38). So the caps limit blast radius, they do not guarantee $20: the provider-side spend limits (Decision 6A, set to the real remaining budget) are the actual ceiling. Re-derive the numbers after smoke item 11.
- **Q5** separate production Supabase project on the free plan. Free-plan pausing after inactivity, the absence of point-in-time recovery and storage limits are **(confirm)** in the Supabase dashboard before launch; a paused project is an outage, so the uptime monitor should hit a path that touches the database weekly or the owner should plan for manual unpause.
- **Q6** LangSmith off in production by default (`LANGSMITH_TRACING` unset; the runbook leaves it unset).
- **Q4** split requirements: yes, `requirements-runtime.txt` after a grep proves nothing the app imports needs the dropped packages. **Q7** build the image on the instance. **Q8** accept that rotating `TOKEN_ENCRYPTION_KEY` forces Calendar reconnects (no MultiFernet). **Q9** SSM Session Manager only, no inbound 22. **Q10** also sweep stale `pending` rows at startup (same threshold as `running`). **Q11** app-level limits only, no Cloudflare. **Q1 follow-on:** `CALENDAR_ENABLED` defaults true; Testing-mode users reconnect weekly.

## Open Questions (original list, answered above)
1. **Google mode at launch.** Testing mode with the owner's invite list (recommended: free allowlist, Calendar works with weekly reconnects), or In production for sign-in only with Calendar off until verified? Is a public, open signup actually wanted?
2. **Domain and canonical origin.** Is there a domain to buy or reuse? Without one, HTTPS for the API is awkward and Google verification is blocked. Frontend on the apex or `app.`? Is `*.vercel.app` acceptable as the frontend origin if Google stays in Testing?
3. **Where caps apply.** Count calendar-created briefings against the user's cap (proposed), or only manual ones? And are 5/day/user, 2 concurrent and 40/day global the right starting numbers? They depend on the measured cost per briefing, which does not exist yet.
4. **Split requirements.** Create `requirements-runtime.txt` without `ragas`, `datasets`, `pandas`, `pyarrow`, `pyiceberg`, `cohere`, `pinecone-client` for the image? It shrinks the image and memory and makes `t3.micro` plausible, but needs a check that nothing in `agents/`, `services/`, `routers/` imports them (the evals harness would keep using the full file). Proposed yes, as its own slice.
5. **Supabase for production.** Separate production project (recommended: isolates dev data and keys) and which plan? Free pauses after inactivity (a paused DB is an outage) and has no PITR **(confirm)**; Pro is $25/mo. Also: should existing dev data be migrated? Proposed no.
6. **LangSmith in production.** Off at launch (proposed, because resume and JD text would leave the box), or on for debugging with a privacy note?
7. **Image build location.** On the instance (proposed, no CI/registry changes, slow on 2 vCPUs) or in GitHub Actions to GHCR (faster, needs a CI change and ARM image via buildx)?
8. **`TOKEN_ENCRYPTION_KEY` rotation.** Accept "rotation forces Calendar reconnect" (proposed), or add `MultiFernet` support now?
9. **Shell access.** SSM Session Manager only (proposed) or SSH from a fixed IP? And who gets the instance role?
10. **Deploy-time orphans.** Also sweep `pending` rows older than N minutes at startup (the known gap), as part of this spec?
11. **Rate limiting at the edge.** Is app-level limiting enough, or put Cloudflare (free) in front of the API for IP limits and DDoS absorption? It adds a DNS/proxy layer and changes how client IPs are read.
12. **Budget.** What monthly ceiling for LLM/search spend should the provider limits and the global cap be derived from?

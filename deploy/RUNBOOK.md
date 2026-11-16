# PrepAgent deployment runbook

Operator steps for specs/deployment.md (Part B). **Every step marked `$` creates or bills a
resource.** Nothing here is run by an agent. Design reasons and open items are in the spec;
this file is just the order of operations.

Assumes: backend on one EC2 instance at `https://api.<domain>`, frontend on Vercel at
`https://app.<domain>`, Google OAuth in Testing mode (invite list), separate production
Supabase project, LangSmith off.

## 1. Before spending anything

- [ ] Production API keys for Anthropic, OpenAI and Tavily, separate from the laptop `.env`. Set a **monthly spend limit or credit cap on each before the key is used** (budget ceiling is $20 in total; the in-app caps limit blast radius but do not guarantee it).
- [ ] Supabase: new production project (free plan). Confirm in the dashboard: pause-on-inactivity behaviour, backups/PITR, storage limit. Apply `supabase/migrations/002` to `007` in order (`006` is needed for the chunk writer, `007` is optional).
- [ ] Generate secrets (keep copies in a password manager; losing `TOKEN_ENCRYPTION_KEY` forces every Calendar reconnect):
  ```bash
  python3 -c "import secrets; print(secrets.token_urlsafe(48))"        # JWT_SECRET
  python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"  # TOKEN_ENCRYPTION_KEY
  ```

## 2. Domain and Google ($ domain, about $10-15/yr)

- [ ] Register a domain. Hostnames: `app.<domain>` (frontend), `api.<domain>` (backend).
- [ ] Google Cloud: a **new production OAuth client** (Web application). Authorized redirect URIs, exactly:
  - `https://app.<domain>/auth/callback`
  - `https://app.<domain>/calendar/callback`
- [ ] Consent screen in **Testing** mode; add yourself and any invitees as test users (max 100). Enable the Google Calendar API if Calendar is used. Keep localhost URIs on a separate dev client.
- [ ] Testing-mode refresh tokens expire after 7 days: Calendar users reconnect weekly. (Publishing and Calendar verification are a separate effort; see spec section 4.)

## 3. AWS ($ EC2 t4g.small about $12/mo, EBS about $1.6, public IPv4 about $3.7)

- [ ] IAM role for the instance: managed policy `AmazonSSMManagedInstanceCore` plus an inline policy allowing `ssm:GetParametersByPath` and `ssm:GetParameters` on `arn:aws:ssm:<region>:<account>:parameter/prepagent/prod/*` (and `kms:Decrypt` if you use a customer-managed key; the default key needs nothing).
- [ ] Security group: inbound **80 and 443** from anywhere; **no 22**. Shell access via SSM Session Manager.
- [ ] $ Launch `t4g.small`, Amazon Linux 2023 (arm64), 20 GB gp3, IMDSv2 required, the role above attached.
- [ ] $ Allocate an Elastic IP and attach it. DNS: `A` record `api.<domain>` to that IP.
- [ ] On the instance (Session Manager):
  ```bash
  sudo dnf install -y docker git jq
  sudo systemctl enable --now docker
  sudo mkdir -p /usr/local/lib/docker/cli-plugins   # install the compose plugin (see Docker docs for your arch)
  sudo mkdir -p /etc/prepagent && sudo chmod 700 /etc/prepagent
  echo "DOMAIN=<your-domain>" | sudo tee /etc/prepagent/deploy.conf   # not a secret
  git clone <repo-url> /opt/prepagent
  ```
  Enable automatic security updates (`dnf-automatic`).

## 4. Secrets into SSM Parameter Store (free, standard tier)

One **SecureString** per variable under `/prepagent/prod/`, named exactly like the env var. Put values in from a file or stdin so they never appear in shell history or the process list:
```bash
# write the value to a file with an editor, not echo; then
aws ssm put-parameter --name /prepagent/prod/ANTHROPIC_API_KEY --type SecureString \
  --value file://./anthropic.key --overwrite
shred -u ./anthropic.key        # or rm on macOS
```
Values must not contain `$`, quotes, `#`, backticks or backslashes (`render-env.sh` refuses them: a compose env file would silently change them). Required: `SUPABASE_URL`, `SUPABASE_SERVICE_KEY`, `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `TAVILY_API_KEY`, `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `JWT_SECRET` (32+ chars), `TOKEN_ENCRYPTION_KEY`, `FRONTEND_URL` (`https://app.<domain>`, no trailing slash).

First launch is invite-only; also set `SIGNUPS_ENABLED=false` and `ALLOWED_EMAILS=<your email>`. Defaults for the caps are 3 per user per day, 20 per day globally, 2 concurrent per user (override with `MAX_BRIEFINGS_PER_USER_PER_DAY`, `MAX_BRIEFINGS_GLOBAL_PER_DAY`, `MAX_ACTIVE_BRIEFINGS_PER_USER`). **Do not set `LANGSMITH_TRACING`** (it would send resume and job description text off the box).

The backend refuses to start (and names the variables) if any of these is missing or weak.

## 5. First backend deploy

```bash
cd /opt/prepagent && deploy/deploy.sh --yes
```
It pulls, builds the image tagged with the git SHA, renders `/etc/prepagent/backend.env` (0600) from SSM, starts the stack, waits for `healthy`, and checks `https://api.<domain>/health` and that `/docs` is 404. Caddy obtains the certificate on first start (DNS must already point at the instance). If the new container is unhealthy it restarts the previous tag.

- [ ] Uptime monitor (free tier) on `https://api.<domain>/health`, every 5 minutes. Free-plan Supabase may pause when idle; a paused database is an outage, so plan a weekly sign-in or confirm the behaviour in the dashboard.

Do **not** run `docker compose config` or `docker inspect` on the instance and paste the output anywhere: both print resolved environment values.

## 6. Vercel (Hobby is $0, for personal non-commercial use; Pro is $20/mo)

- [ ] Import the repo. **Root Directory `frontend`**, framework Next.js, Node 20, production branch `main`.
- [ ] Environment variable, **Production only**: `NEXT_PUBLIC_API_URL=https://api.<domain>` (no trailing slash). A production build fails without it. It is inlined at build time: changing it needs a redeploy. Never put a secret in a `NEXT_PUBLIC_*` variable.
- [ ] Domain `app.<domain>`; redirect other hostnames (including `*.vercel.app`) to it. Leave Deployment Protection on for previews (sign-in cannot work on preview URLs: they are not in CORS or Google's redirect URIs).

## 7. Smoke test (every release: 1-6; at launch and after config changes: all)

1. `https://api.<domain>/health` returns `{"status":"ok"...}` with a valid certificate; `http://` redirects to `https://`; `/docs` and `/openapi.json` return 404.
2. CORS: a preflight from `https://app.<domain>` is allowed; from another origin there is no `Access-Control-Allow-Origin`.
3. Sign in as yourself through the real frontend.
4. Create a briefing without a job description; the viewer polls to `complete`.
5. Create one with a job description (the chip shows); a 12,001-character one is a 422 that does not echo it; a body over 512 KB is a 413.
6. Logs: put unique marker strings in company, interviewer, resume and job description, then `sudo docker compose -f deploy/docker-compose.prod.yml logs api caddy | grep -c <marker>` must be 0 for each; the `/auth/callback` log line has no `code=` or `state=`.
7. Caps: temporarily set `MAX_BRIEFINGS_PER_USER_PER_DAY=1`, redeploy, confirm a `429` with `Retry-After` and the message on `/prep/new`; restore.
8. Kill switches: `BRIEFINGS_ENABLED=false` gives 503 on create and reads still work; `SIGNUPS_ENABLED=false` refuses a new email (403) and still lets you in.
9. Restart the container mid sign-in: it returns healthy and the startup sweep logs; the interrupted sign-in just needs a retry.
10. Calendar (if enabled; test users only): connect, sync, disconnect.
11. **Cost check:** after step 4, read the Anthropic, OpenAI and Tavily usage for that one briefing and write the measured cost into specs/deployment.md. Re-derive the caps and the provider spend limits from it.
12. Image has no env files: `docker run --rm --entrypoint sh prepagent-api:<tag> -c 'ls -a /app | grep "^\.env" || echo none'` prints `none`.

## 8. Kill switches and emergency order

Edit the SSM parameter, then `deploy/render-env.sh && IMAGE_TAG=$(cat /etc/prepagent/current_tag) docker compose -f deploy/docker-compose.prod.yml --env-file /etc/prepagent/deploy.conf up -d` (about 10 seconds).

| Switch | Effect |
|---|---|
| `BRIEFINGS_ENABLED=false` | create and calendar-confirm return 503; reads still work |
| `SIGNUPS_ENABLED=false` | new emails refused (403); existing users sign in |
| `ALLOWED_EMAILS=a@x.com,b@x.com` | only these can sign in or sign up (existing users not on it are refused too) |
| `CALENDAR_ENABLED=false` | calendar routes return 404, poller off |

`ALLOWED_EMAILS` and `SIGNUPS_ENABLED` are checked at sign-in only: someone already signed in keeps API access until their session expires (7 days, no revocation). To cut a user off now, rotate `JWT_SECRET` (signs everyone out) or use `BRIEFINGS_ENABLED=false`.

Emergency order, fastest first: (1) `BRIEFINGS_ENABLED=false`; (2) revoke the Anthropic / OpenAI key; (3) `docker compose ... stop api`; (4) rotate `JWT_SECRET` (signs everyone out); (5) remove test users in the Google console, or pause the Vercel project.

## 9. Rollback

- Backend: `deploy/rollback.sh <tag>` (tags: `docker images prepagent-api`; the last 3 are kept). Migrations are additive, so older code runs on the newer schema; there are no down-migrations.
- Config: SSM keeps parameter history; restore the old value, re-render, recreate.
- Frontend: Vercel **Instant Rollback** to the previous production deployment.
- Rehearse once with a throwaway tag before relying on it. The automatic rollback in `deploy.sh` (and the `up -d` behaviour it depends on) has never been run: treat it as untested until you have seen it work.

## 10. Secret rotation

Update the SSM parameter, `deploy/render-env.sh`, recreate the container, run the smoke checks for that feature, then revoke the old value at the provider.

| Secret | Notes |
|---|---|
| `JWT_SECRET` | everyone is signed out (sessions last 7 days, no revocation); this is also the emergency lever |
| `TOKEN_ENCRYPTION_KEY` | stored calendar tokens become undecryptable: users reconnect Calendar. No zero-downtime rotation |
| `SUPABASE_SERVICE_KEY` | full database access; rotate per the Supabase dashboard (depends on the project's key system) |
| `GOOGLE_CLIENT_SECRET` | Google lets a client hold two secrets: add the new, deploy, disable the old |
| Anthropic / OpenAI / Tavily | create new, update SSM, recreate, revoke old. Also the response to any suspected leak or cost spike |

Practise once on a low-risk key (Tavily) before an incident.

## 11. When it is live

- [ ] Replace the placeholders in the README Deployment section with the real URLs.
- [ ] Loosen `SIGNUPS_ENABLED` / `ALLOWED_EMAILS` only to the audience you intend, after the smoke checks pass.
- [ ] Watch provider usage for the first week; re-check the caps against real cost.

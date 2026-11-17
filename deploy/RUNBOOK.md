# PrepAgent deployment runbook (Part B, operator steps)

Operator steps for specs/deployment.md. **Nothing here is run by an agent.** Every step marked `$` creates or bills a resource. Design reasons and open items are in the spec; this file is the order of operations, with the expected cost and a check for each step.

## The setup this runbook is written for

| Choice | Value |
|---|---|
| Domain | `useprepagent.app` (`.app` is HSTS-preloaded: browsers refuse plain http, which is fine here, everything is https) |
| Frontend | Vercel, canonical origin **`https://useprepagent.app`** (the apex). `www.useprepagent.app` redirects to it |
| API | `https://api.useprepagent.app`, one EC2 instance |
| AWS | Free plan, $100 credits, plan ends **16 May 2027**. One region: **`us-west-2` (Oregon)**. Use it for every command below (`--region us-west-2`) |
| Instance | `t3.micro` (x86_64, 2 vCPU burstable, 1 GB RAM), Amazon Linux 2023 x86_64, **10 GB gp3**, **2 GB swap file**, Docker Compose + Caddy |
| Google OAuth | Testing mode, invite list |
| Supabase | new production project (free plan) |

Prices are US-region list prices from general knowledge, marked **(confirm)**: check them in the AWS console / pricing calculator before relying on them.

### Expected monthly cost (us-west-2, on-demand, taxes excluded) **(confirm)**

| Item | Per month | Notes |
|---|---|---|
| EC2 `t3.micro` | ~$7.6 | $0.0104/h x 730 h. Must run in **standard** CPU-credit mode (step 3.5), or sustained load can add surplus-credit charges |
| EBS gp3 10 GB | ~$0.8 | $0.08/GB-month |
| Public IPv4 (the Elastic IP) | ~$3.7 | $0.005/h, charged whether attached or not |
| Route 53 hosted zone | ~$0.5 | only if DNS is hosted in Route 53 (skip if the registrar's DNS is used) |
| SSM Parameter Store (standard), Session Manager, Let's Encrypt, Caddy, Vercel Hobby | $0 | |
| **Total** | **~$12-12.5** | |

One-off: the `.app` registration, about $14-20/yr depending on registrar (Route 53 lists about $20) **(confirm)**.

Credit arithmetic: today (16 Nov 2026) to 16 May 2027 is about 6 months, so about $72 of EC2 + EBS + IPv4, plus about $3 of hosted zone, plus the domain: **roughly $75-95 of the $100**. That fits, with little slack: do not add a second instance, a NAT gateway, a load balancer, an RDS or CloudWatch agent logging. The LLM/search spend is **not** AWS and is not covered by the credits (it is paid on the Anthropic, OpenAI and Tavily accounts: section 1).

**The Free plan ends on 16 May 2027 (or when the credits run out, whichever is first), and AWS closes the account.** Treat that date as a hard stop: do the teardown (section 12) or move to a paid plan before it **(confirm the exact end date on the Billing > Credits page; AWS documents 6 and 12 months in different places)**.

## 1. Prepare first (nothing here costs AWS money)

### 1.1 Code on `main`
- [ ] The deploy script checks out and fast-forwards `main`, and Vercel builds `main`. Merge the production-readiness work (PR #18, now on `dev`) to `main` first.
  - Verify: `git log origin/main --oneline | head -3` shows the deployment commit.

### 1.2 Production Supabase project (free plan)
- [ ] Create a new project (region near us-west-2, for example `West US (Oregon)`). Save the database password in a password manager.
- [ ] Enable the `vector` extension (Database > Extensions), or let migration 002 do it.
- [ ] **Blocker to resolve first: the repo has no migration that creates `users` or `briefings`.** `supabase/migrations` starts at `002`, and `002`, `004`, `005`, `006` all reference tables created earlier by hand in the dev project. Applying `002`-`007` to an empty project fails. Take a schema-only dump of the **dev** project (`supabase db dump --schema public -f base_schema.sql` or `pg_dump --schema-only --no-owner`), read it, remove anything not wanted, and apply it to the production project **before** `002`. Do not copy data. (Better: commit it as `001_base_schema.sql` in a separate change.) The dump includes the old `users.google_*_token` columns; that is fine on an empty table, `005` then drops them.
- [ ] Apply `002` to `007` in order in the SQL editor (`007` is optional, `006` is needed for the chunk writer).
  - Verify: Table editor shows `users`, `briefings`, `resume_embeddings` (with `briefing_id`, `company`, `role`), `calendar_connections`, `calendar_detections`; `users` has no `google_access_token` column; `briefings` has `failure_reason`.
- [ ] Copy **Project URL** and the **service_role** key (backend only, never in Vercel). Confirm in the dashboard, on the free plan: pause-on-inactivity (a paused project is an outage), no point-in-time recovery, storage limit **(confirm)**.

### 1.3 Provider keys and spend limits (set the limit before the key is ever used)
Budget ceiling is **$20/month of LLM and search spend**. Create **new** keys, separate from the laptop `.env`.
- [ ] **Anthropic** (console): a new workspace (for example `prepagent-prod`) with a **monthly spend limit**, then an API key in it. Set the limit to what remains of the budget, not the maximum.
- [ ] **OpenAI** (platform): a new project with a **monthly budget**; keep auto-recharge off if the account is prepaid. New API key in that project. Embeddings are cheap, so a small limit is enough.
- [ ] **Tavily**: a new key on a plan with a fixed monthly credit allowance; turn off pay-as-you-go/overage so it stops instead of billing.
- [ ] Each provider's limit feature differs and changes: **(confirm)** by finding the setting in each console and writing down the value you set.
- [ ] The app's caps (3/user/day, 20/day, 2 concurrent) limit blast radius only. 20/day x 30 = 600 briefings stays under $20 only if one costs under ~$0.033 (unmeasured; smoke step 11 measures it).

### 1.4 Google Cloud (production OAuth client)
- [ ] New OAuth client, type **Web application**, in a project used for production. Name it `prepagent-prod`.
- [ ] **Authorized redirect URIs, exactly these two** (the apex, no `www`, no trailing slash):
  - `https://useprepagent.app/auth/callback`
  - `https://useprepagent.app/calendar/callback`
- [ ] Do not add localhost to this client. Keep `http://localhost:3000/auth/callback` and `/calendar/callback` on a separate dev client.
- [ ] OAuth consent screen: user type External, **Publishing status = Testing**, app name, support email, developer contact email. Add `useprepagent.app` under Authorized domains (needed only if you later publish; harmless now).
- [ ] **Test users** (Audience > Test users, max 100): your own Google account and each invitee, exactly as they sign in. Anyone not listed cannot sign in.
- [ ] Enable the **Google Calendar API** (APIs & Services > Library) if Calendar is used.
- [ ] Copy the client ID and secret.
- [ ] Testing-mode refresh tokens expire after 7 days: Calendar users reconnect weekly (spec section 4).

### 1.5 Secrets and values to generate
```bash
python3 -c "import secrets; print(secrets.token_urlsafe(48))"        # JWT_SECRET (token_urlsafe has no $ " ' # ` \)
python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"  # TOKEN_ENCRYPTION_KEY
```
Keep both in a password manager. Losing `TOKEN_ENCRYPTION_KEY` forces every Calendar reconnect.

### 1.6 What goes into SSM Parameter Store (as SecureString, under `/prepagent/prod/`, in us-west-2)
| Parameter (exact env var name) | Value | Secret? |
|---|---|---|
| `SUPABASE_URL` | production project URL | no, but store anyway |
| `SUPABASE_SERVICE_KEY` | production service_role key | **yes, highest risk** |
| `ANTHROPIC_API_KEY` | prod key (workspace with limit) | yes |
| `OPENAI_API_KEY` | prod key (project with budget) | yes |
| `TAVILY_API_KEY` | prod key | yes |
| `GOOGLE_CLIENT_ID` | prod OAuth client | no |
| `GOOGLE_CLIENT_SECRET` | prod OAuth client | yes |
| `JWT_SECRET` | generated, 32+ chars | yes |
| `TOKEN_ENCRYPTION_KEY` | generated Fernet key | yes |
| `FRONTEND_URL` | `https://useprepagent.app` (no trailing slash) | no |
| `SIGNUPS_ENABLED` | `false` for the first launch | no |
| `ALLOWED_EMAILS` | your Google email (comma list later) | personal data: keep it in SSM, not in git |

Optional (defaults are fine): `MAX_BRIEFINGS_PER_USER_PER_DAY`=3, `MAX_BRIEFINGS_GLOBAL_PER_DAY`=20, `MAX_ACTIVE_BRIEFINGS_PER_USER`=2. **Do not create `LANGSMITH_*` parameters** (resume and job-description text would leave the box). `APP_ENV=production` is set by the compose file, not SSM. `DOMAIN` is not a secret and goes in `/etc/prepagent/deploy.conf` on the box (step 3.8).

Values must not contain `$`, quotes, `#`, backticks or backslashes (`render-env.sh` refuses them). The backend refuses to start, naming the variables, if any required one is missing or weak.

### 1.6b Accounts and tools on your laptop
- [ ] AWS account on the Free plan, MFA on the root user, and an admin IAM/Identity Center user for the console (do not work as root). AWS CLI configured for it (`aws sts get-caller-identity` works) if you use the CLI snippets.
- [ ] Vercel account (Hobby), GitHub connected. If the repo is **private**, decide how the instance clones it (a read-only deploy key is better than a personal token; neither goes in SSM `prepagent/prod/`, which is rendered into the API's env file).
- [ ] An uptime monitor account (free tier).

## 2. Domain and DNS ($ domain once, about $14-20/yr **(confirm)**)

Where the domain is registered decides where DNS lives. Pick one:
- **Registrar's own DNS (cheapest, no hosted zone):** add the records below in its dashboard.
- **Route 53:** register or transfer in Route 53 (Registered domains > Register), which creates a hosted zone (~$0.50/mo). AWS bills the registration against the account; whether credits cover it **(confirm on the Free plan)**. If the Free plan blocks domain registration, register elsewhere.

- [ ] Registered; verify: `whois useprepagent.app | head` or the registrar dashboard shows you as registrant; auto-renew on or a calendar reminder.
- Records to create (TTL 300 while setting up). Create the `api` record only after step 3.4 (it needs the Elastic IP); the Vercel ones after step 6:

| Type | Name | Value |
|---|---|---|
| A | `api` | the Elastic IP |
| A | `@` (apex) | the value Vercel shows on the domain card (`76.76.21.21` for most projects) |
| CNAME | `www` | the value Vercel shows (`cname.vercel-dns-0.com` is the general one) |

Remove any existing `AAAA` record on the apex and any leftover parking records. Do not add a CAA record unless it allows both Let's Encrypt and Vercel's CA.
- Verify later: `dig +short api.useprepagent.app` returns the Elastic IP; `dig +short useprepagent.app` returns the Vercel address.

## 3. AWS (us-west-2): about $12/month total once everything exists

All steps in `us-west-2`: set the region selector in the console first (top right). The default VPC is used.

### 3.1 IAM role for the instance (free)
- [ ] IAM > Roles > Create role > AWS service > EC2. Attach managed policy `AmazonSSMManagedInstanceCore`. Name it `prepagent-prod-ec2`.
- [ ] Add an inline policy `prepagent-ssm-read`:
  ```json
  {"Version":"2012-10-17","Statement":[{"Effect":"Allow",
    "Action":["ssm:GetParametersByPath","ssm:GetParameters"],
    "Resource":"arn:aws:ssm:us-west-2:<ACCOUNT_ID>:parameter/prepagent/prod/*"}]}
  ```
  (No `kms:Decrypt` needed for the default `aws/ssm` key.)
- Verify: the role page lists both policies; the resource ARN has your account id and `us-west-2`.

### 3.2 Security group (free)
- [ ] EC2 > Security Groups > Create, name `prepagent-prod`, default VPC. Inbound: **TCP 80** and **TCP 443** from `0.0.0.0/0`, and **UDP 443** (HTTP/3, optional). **No port 22.** Leave outbound as is.
- Verify: exactly those rules; nothing on 22.

### 3.3 Launch the instance ($ about $7.6/mo)
- [ ] EC2 > Launch instance. Name `prepagent-prod`.
  - AMI: **Amazon Linux 2023 AMI, 64-bit (x86)** (not Arm). Instance type **`t3.micro`**.
  - Key pair: **Proceed without a key pair** (Session Manager only).
  - Network: default VPC, **Auto-assign public IP: Disable** (the Elastic IP in 3.6 is the only public address; this avoids a second billed IPv4). Security group `prepagent-prod`.
  - Storage: **10 GiB gp3**, delete on termination **Yes**, encrypted (default key).
  - Advanced details: IAM instance profile `prepagent-prod-ec2`; **Metadata version: V2 only (required)**; **Credit specification: Standard** (see 3.5); leave detailed CloudWatch monitoring off.
- Verify: Instance state `running`, 2/2 checks pass; Instance details show Instance type `t3.micro`, Architecture `x86_64`, IMDSv2 `Required`, no public IPv4 yet.

### 3.4 Elastic IP ($ about $3.7/mo, billed from allocation)
- [ ] EC2 > Elastic IPs > Allocate, then Associate with the instance. Note the address.
- Verify: instance now shows that public IPv4; `dig +short api.useprepagent.app` (after step 2's record) returns it.

### 3.5 CPU credits: standard mode (free, prevents a surprise)
T3 launches in **unlimited** mode by default, which bills surplus CPU credits if average CPU stays above the baseline (about 10% per vCPU on a t3.micro) **(confirm)**. Docker builds and pipeline bursts can do that.
- [ ] If you did not set Standard at launch: EC2 > select instance > Actions > Instance settings > **Change T2/T3/T4g credit specification** > Standard.
- Verify: instance Details > Credit specification shows `standard`. Optional: CloudWatch `CPUCreditBalance` is non-zero.

### 3.6 Connect with Session Manager (free)
- [ ] EC2 > Connect > **Session Manager** tab > Connect (wait 2-5 minutes after launch if it is greyed out). Run everything below as `sudo`.
- Verify: you get a shell; `uname -m` prints `x86_64`; `free -m` shows about 900 MB total. If the instance is missing from Systems Manager > Fleet Manager, recheck the role (3.1) and that the security group still allows outbound 443.

### 3.7 Swap file (free, uses 2 GB of the 10 GB disk)
```bash
sudo dd if=/dev/zero of=/swapfile bs=1M count=2048 status=progress
sudo chmod 600 /swapfile && sudo mkswap /swapfile && sudo swapon /swapfile
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
echo 'vm.swappiness=10' | sudo tee /etc/sysctl.d/99-swap.conf && sudo sysctl --system
```
- Verify: `swapon --show` lists `/swapfile` 2G; `free -m` shows Swap 2047; `grep swap /etc/fstab` has the line; after a reboot (`sudo reboot`) swap is still on.
- Why: a 1 GB box running the image build or a pipeline run can be OOM-killed; swap keeps it alive but slow. Heavy swapping looks like the earlier "hung on running" incident, so keep an eye on step 7 timing.

### 3.8 Install Docker, Compose (x86_64), clone the repo (free)
```bash
sudo dnf install -y docker git jq
sudo systemctl enable --now docker
# Compose plugin: pick the current release on github.com/docker/compose/releases, pin it, and check it
COMPOSE_VERSION=<vX.Y.Z>
sudo mkdir -p /usr/local/lib/docker/cli-plugins
sudo curl -fSL "https://github.com/docker/compose/releases/download/${COMPOSE_VERSION}/docker-compose-linux-x86_64" \
  -o /usr/local/lib/docker/cli-plugins/docker-compose
sudo chmod +x /usr/local/lib/docker/cli-plugins/docker-compose
sudo mkdir -p /etc/prepagent && sudo chmod 700 /etc/prepagent
echo "DOMAIN=useprepagent.app" | sudo tee /etc/prepagent/deploy.conf     # not a secret
sudo git clone <repo-url> /opt/prepagent
sudo dnf install -y dnf-automatic && sudo systemctl enable --now dnf-automatic-install.timer
```
`docker-compose-linux-x86_64` is the right file for a t3 (an Arm `t4g` would need `aarch64`). The AWS CLI is preinstalled on Amazon Linux 2023.
- Verify: `docker --version`, `docker compose version`, `aws --version`, `ls /opt/prepagent/deploy` shows the scripts, `systemctl list-timers | grep dnf-automatic`, `df -h /` shows roughly 3 GB used.

## 4. Secrets into SSM Parameter Store (free, standard tier, SecureString)

One parameter per row of the table in 1.6, under `/prepagent/prod/`, named exactly like the env var. Run from your laptop with the admin profile (the instance role is read-only). Put each value in a file with an editor, never `echo` and never as a command argument:
```bash
aws ssm put-parameter --region us-west-2 --name /prepagent/prod/ANTHROPIC_API_KEY \
  --type SecureString --value file://./anthropic.key --overwrite
rm -P ./anthropic.key      # macOS secure delete (shred -u on Linux)
```
Non-secret values (`FRONTEND_URL`, `SIGNUPS_ENABLED`, `ALLOWED_EMAILS`) go in the same way for consistency.
- Verify (names only): `aws ssm get-parameters-by-path --region us-west-2 --path /prepagent/prod/ --query 'Parameters[].Name' --output text` lists all 12 names. Do **not** use `--with-decryption` on your laptop screen-share. On the instance: `sudo deploy/render-env.sh` (step 5 runs it) prints `wrote 12 variable(s)`.

## 5. First backend deploy (free; the image build uses CPU credits and about 1 GB of disk)

Order matters: the `api` DNS record must already point at the Elastic IP (Caddy asks Let's Encrypt for the certificate on first start), and the instance must have the Supabase migrations in place (1.2).
```bash
sudo bash -c 'cd /opt/prepagent && deploy/deploy.sh --yes'
```
(`sudo` is needed: the script writes `/etc/prepagent`, runs docker and ends by pruning old tags.) It pulls `main`, builds `prepagent-api:<sha>`, renders `/etc/prepagent/backend.env` (0600), starts the stack, waits for `healthy`, and checks `https://api.useprepagent.app/health` and that `/docs` is 404. If the new container is unhealthy it restarts the previous tag.
- Expect the first build to take several minutes on a t3.micro (2 vCPU burstable, swap in use).
- Verify: `curl -s https://api.useprepagent.app/health` returns `{"status":"ok"...}` with a valid certificate (`curl -vI` shows a Let's Encrypt issuer); `curl -I http://api.useprepagent.app` redirects to https; `curl -s -o /dev/null -w '%{http_code}' https://api.useprepagent.app/docs` is `404`; `sudo docker ps` shows `api` as `healthy`.
- Memory check: `free -m` and `vmstat 1 5` while idle: used should be well under 1 GB, swap in/out (`si`/`so`) close to 0. If swap is busy at idle, stop and reconsider the instance size (`t3.small` is also Free-plan eligible **(confirm)**, about +$7.6/mo, which would not fit the credits for six months).
- Disk check: `df -h /` should stay under about 80%. After each deploy run `sudo docker builder prune -f` and, if tight, `sudo docker image prune -f`. `deploy.sh` keeps the newest 3 image tags; on a 10 GB disk consider 2 (edit `KEEP_IMAGES` on the box only if the disk is filling).
- [ ] Uptime monitor (free tier) on `https://api.useprepagent.app/health` every 5 minutes. The free Supabase project may pause when idle: sign in once a week, or confirm the behaviour in the dashboard.

Do **not** run `docker compose config` or `docker inspect` and paste the output anywhere: both print resolved environment values.

## 6. Vercel (Hobby $0; Pro $20/mo only if the project stops being personal/non-commercial **(confirm)**)

- [ ] Import the GitHub repo. **Root Directory `frontend`**, framework Next.js, Node 20, production branch **`main`**.
- [ ] Environment variable, **Production only**: `NEXT_PUBLIC_API_URL=https://api.useprepagent.app` (no trailing slash). Inlined at build time: changing it needs a redeploy. Never put a secret in a `NEXT_PUBLIC_*` variable. The build fails without it (intended).
- [ ] Settings > Domains: add `useprepagent.app` (this is the canonical/primary domain) and `www.useprepagent.app` with **Redirect to `useprepagent.app`**. Add the DNS records Vercel shows (section 2). Leave Deployment Protection on for previews (sign-in cannot work on preview URLs: they are not in CORS or Google's redirect URIs). Redirect `*.vercel.app` to the apex if the option is offered.
- Verify: the deployment shows Ready; the domain cards show "Valid Configuration"; `curl -sI https://useprepagent.app` is 200 with a valid certificate; `curl -sI https://www.useprepagent.app` is a 307/308 to `https://useprepagent.app/`; in the browser, the Network tab shows API calls going to `https://api.useprepagent.app`, never localhost; response headers include `X-Content-Type-Options` and a `Content-Security-Policy-Report-Only` whose `connect-src` has the API origin.

## 7. Smoke test (every release: 1-6; at launch and after config changes: all)

1. `https://api.useprepagent.app/health` returns `{"status":"ok"...}` with a valid certificate; `http://` redirects to `https://`; `/docs` and `/openapi.json` return 404.
2. CORS: `curl -si -X OPTIONS https://api.useprepagent.app/briefings -H 'Origin: https://useprepagent.app' -H 'Access-Control-Request-Method: POST' -H 'Access-Control-Request-Headers: authorization,content-type'` allows that origin and sends no `Access-Control-Allow-Credentials`; the same with `Origin: https://example.com` returns no `Access-Control-Allow-Origin`.
3. Sign in as yourself through the real frontend at `https://useprepagent.app` (an unlisted Google account must be refused by Google).
4. Create a briefing without a job description; the viewer polls to `complete`.
5. Create one with a job description (the chip shows); a 12,001-character one is a 422 that does not echo it; a body over 512 KB is a 413.
6. Logs: put unique marker strings in company, interviewer, resume and job description, then `sudo docker compose -f /opt/prepagent/deploy/docker-compose.prod.yml logs api caddy | grep -c <marker>` must be 0 for each; the `/auth/callback` log line has no `code=` or `state=`.
7. Caps: temporarily set `MAX_BRIEFINGS_PER_USER_PER_DAY=1` in SSM, re-render and recreate (section 8), confirm a `429` with `Retry-After` and the message on `/prep/new`; restore.
8. Kill switches: `BRIEFINGS_ENABLED=false` gives 503 on create and reads still work; `SIGNUPS_ENABLED=false` refuses a new email (403) and still lets you in.
9. Restart the container mid sign-in: it returns healthy and the startup sweep logs; the interrupted sign-in just needs a retry.
10. Calendar (if enabled; test users only): connect, sync, disconnect.
11. **Cost check:** after step 4, read the Anthropic, OpenAI and Tavily usage for that one briefing and write the measured cost into specs/deployment.md. Re-derive the caps and the provider spend limits from it.
12. Image has no env files: `sudo docker run --rm --entrypoint sh prepagent-api:<tag> -c 'ls -a /app | grep "^\.env" || echo none'` prints `none`.
13. **Small-box check (t3.micro):** time one briefing end to end (it must finish inside `PIPELINE_DEADLINE_SECONDS`, 120 s); during it run `free -m` and `vmstat 1` in a second session: swap `so` should not stay high, and `sudo dmesg | grep -i 'out of memory'` must print nothing.

## 8. Kill switches and emergency order

Edit the SSM parameter, then on the instance:
`sudo /opt/prepagent/deploy/render-env.sh && sudo bash -c 'IMAGE_TAG=$(cat /etc/prepagent/current_tag) docker compose -f /opt/prepagent/deploy/docker-compose.prod.yml --env-file /etc/prepagent/deploy.conf up -d'` (about 10 seconds).

| Switch | Effect |
|---|---|
| `BRIEFINGS_ENABLED=false` | create and calendar-confirm return 503; reads still work |
| `SIGNUPS_ENABLED=false` | new emails refused (403); existing users sign in |
| `ALLOWED_EMAILS=a@x.com,b@x.com` | only these can sign in or sign up (existing users not on it are refused too) |
| `CALENDAR_ENABLED=false` | calendar routes return 404, poller off |

`ALLOWED_EMAILS` and `SIGNUPS_ENABLED` are checked at sign-in only: someone already signed in keeps API access until their session expires (7 days, no revocation). To cut a user off now, rotate `JWT_SECRET` (signs everyone out) or use `BRIEFINGS_ENABLED=false`.

Emergency order, fastest first: (1) `BRIEFINGS_ENABLED=false`; (2) revoke the Anthropic / OpenAI key; (3) `sudo docker compose ... stop api`; (4) rotate `JWT_SECRET`; (5) remove test users in the Google console, or pause the Vercel project.

## 9. Rollback

- Backend: `sudo deploy/rollback.sh <tag>` (tags: `sudo docker images prepagent-api`; the last 3 are kept). Migrations are additive, so older code runs on the newer schema; there are no down-migrations.
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

- [ ] Replace the placeholders in the README Deployment section: `https://useprepagent.app` and `https://api.useprepagent.app/health`.
- [ ] Loosen `SIGNUPS_ENABLED` / `ALLOWED_EMAILS` only to the audience you intend, after the smoke checks pass.
- [ ] AWS: Billing > Budgets > create a monthly **cost budget** (for example $15) with an email alert at 80%, and check Billing > Credits weekly for the remaining balance and the end date **(confirm the budget types the Free plan allows)**.
- [ ] Watch provider usage for the first week; re-check the caps against real cost.
- [ ] Put 15 May 2027 (the day before the plan ends) in your calendar: run section 12 or upgrade.

## 12. Teardown: delete every billable resource

Do this when you stop, and no later than **15 May 2027**. Order matters (an Elastic IP or volume left behind keeps billing). Closing the account is not a substitute: do the steps and verify.

1. [ ] **Vercel**: Project > Settings > Domains > remove `useprepagent.app` and `www`; Settings > Advanced > Delete Project. (Hobby costs $0, but this stops serving a dead site.) Verify: the project is gone from the dashboard.
2. [ ] **DNS records**: delete the `api`, apex and `www` records so nothing points at a released IP (dangling-record takeover). If Route 53 hosts the zone, delete the records first, then the hosted zone (~$0.50/mo): Route 53 > Hosted zones > delete. Verify: `dig +short api.useprepagent.app` is empty.
3. [ ] **Domain**: turn **auto-renew off** (Route 53 > Registered domains, or the registrar). Registration is paid up front and is not refunded; it is a separate renewal charge each year. Verify: auto-renew shows Off.
4. [ ] **EC2 instance**: stop the API first if you want a clean shutdown (`sudo docker compose -f /opt/prepagent/deploy/docker-compose.prod.yml down`), then EC2 > Instances > **Terminate**. Verify: state `terminated`. The root volume goes with it only because "delete on termination" was Yes.
5. [ ] **EBS volumes**: EC2 > Volumes: none left in us-west-2 (`available` volumes bill). Delete any. Also EC2 > Snapshots and AMIs: none.
6. [ ] **Elastic IP**: EC2 > Elastic IPs > Disassociate, then **Release** (an unassociated EIP bills ~$3.7/mo). Verify: the Elastic IPs list is empty.
7. [ ] **Security group** `prepagent-prod`: delete after the instance is gone.
8. [ ] **SSM parameters**: delete all under `/prepagent/prod/` (`aws ssm delete-parameters --region us-west-2 --names ...`, or console). Verify: `aws ssm get-parameters-by-path --region us-west-2 --path /prepagent/prod/` returns an empty list. They are free, but they hold live secrets: delete them.
9. [ ] **IAM**: delete role `prepagent-prod-ec2` (and its instance profile) and any IAM user/access key created for this project.
10. [ ] **Budgets / alarms**: delete the AWS Budget and any CloudWatch alarms or dashboards you created; a Cost Explorer check next day should show $0.
11. [ ] **Check the whole region and others**: Billing > Cost Explorer grouped by Service and Region (next day), plus EC2 > Global view. Anything unexpected in another region means a resource was created there by mistake.
12. [ ] **Supabase**: Project settings > General > Delete project (or Pause). Free, but it holds user data (resume text). Verify: gone from the dashboard.
13. [ ] **Secrets at third parties**: revoke/delete the production keys at Anthropic, OpenAI and Tavily and delete the workspace/project; delete the Google OAuth client `prepagent-prod` and revoke test users' access.
14. [ ] **AWS account**: if you will not use it again, Account > Close account (AWS closes Free-plan accounts at the end anyway; unused credits are forfeited **(confirm)**). Do this last, after step 11 shows nothing.

After teardown: set the README Deployment section back to "not live".

## 13. Free-plan facts to confirm in your own console

- The plan end date (Billing > Credits) is 16 May 2027, and what happens to the account then (closure after the Free plan, a 90-day window to upgrade and recover **(confirm)**).
- The Free plan allows `t3.micro` in `us-west-2`, Route 53 domain registration, and Budgets.
- Public IPv4 and Elastic IP charges are drawn from credits.

# PrepAgent status

## Last updated
- Date: 2026-11-16
- Main commit: `83c1228`

## Live
- URLs: https://useprepagent.app (frontend), https://api.useprepagent.app (backend)
- Region: us-east-2 (Ohio)
- Current release tag: none (no git tags exist; the deployed image tag is in `/etc/prepagent/current_tag` on the instance)

## Done
- LangGraph pipeline (fixed DAG: company + interviewer, RAG, synthesis)
- Resilience: timeouts, retries, pipeline deadline, stale-row sweeps
- RAGAS eval harness with committed baselines
- Job description input (backend, viewer, evals)
- Production readiness: config checks, rate limits, cost caps, kill switches, log hygiene
- AWS deploy (EC2, Docker Compose, Caddy) via `deploy/RUNBOOK.md`
- Vercel frontend
- Domain (useprepagent.app)

## Measured numbers
- Eval (Sonnet baseline): company faithfulness 0.99, factual synthesis 0.72, prescriptive synthesis 0.79
- JD spike: factual synthesis faithfulness 0.56 to 0.99 (3 synthetic cases, self-graded)
- Cost per briefing: not yet measured

## TODO (priority order)
1. Production smoke test: real briefings with and without a JD, `free -m` and `dmesg` OOM check, log-hygiene marker test
2. Measure real cost per briefing, re-derive caps (20/day fits $20/month only if under about $0.033)
3. Uptime monitor on `/health`, confirm AWS Budget alert and provider spend limits
4. Delete stale GitHub branches
5. README live URL placeholders and unverified-app note
6. Resume wording: Gmail and Drive are not built, reword or build
7. Later: Gmail/Drive, LangSmith, `--repeat` judge noise, base-schema migration, orphaned pending sweep

## Deadlines
- AWS teardown by 2027-05-15 (RUNBOOK section 12)

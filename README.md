# PrepAgent

AI-powered interview research. Enter a company and interviewer, and get a personalized, cited briefing from a multi-agent pipeline.

**Live:** https://useprepagent.app · API health: https://api.useprepagent.app/health

## What it does

PrepAgent runs a 4-node LangGraph research pipeline when you have an interview:

1. **Company Intelligence Agent** — searches the web (Tavily) for recent news, funding and engineering context, and summarizes it with sources
2. **Interviewer Research Agent** — builds a profile of who you're meeting, drops results that don't mention them, and warns when the match looks like the wrong person
3. **RAG Retrieval Agent** — retrieves your resume chunks and prior briefings for the same company from pgvector
4. **Synthesis Agent** — generates role insights and talking points specific to your background; every item must cite a source URL or a resume section, and code drops anything uncited

The output is a 4-section briefing: company overview, interviewer profile, role insights, and talking points. A Google Calendar connection can detect interview events and propose a briefing for you to confirm.

**Optional job description (built).** Paste a job posting on the new-briefing form and the role requirements come from that text instead of being inferred from company research. Each requirement is tagged `[JD]` and the viewer marks it with a "Job description" chip and a "From job description" label on the Key requirements list. The pasted text is treated as untrusted data, is limited to 12,000 characters, is used for that one briefing only (it is not stored, logged or embedded), and is never taken from calendar events. Spec: [specs/job-description-input.md](specs/job-description-input.md).


## Tech Stack

**Frontend:** Next.js (app router), TypeScript, Tailwind CSS

**Backend:** FastAPI, Python 3.12, LangGraph, LangChain, Claude Sonnet

**Database:** Supabase PostgreSQL

**Vector Store:** pgvector (Supabase)

**Observability:** LangSmith

**Evals:** RAGAS harness with committed baselines (see [Evaluation](#evaluation))

**Auth and integrations:** Google OAuth with JWT sessions; Google Calendar interview detection through the Calendar API directly (see ADR 7)

**Infrastructure:** GitHub Actions CI; AWS EC2 (Docker Compose + Caddy) for the backend and Vercel for the frontend (see [Deployment](#deployment))

## Architecture

```
Next.js Frontend (Vercel)
    ↓
FastAPI Backend (AWS EC2)
    ↓
LangGraph DAG
    ├── Company Intelligence Agent (Tavily) ──┐ parallel
    ├── Interviewer Research Agent (Tavily) ──┘
    ↓
    ├── RAG Retrieval Agent (pgvector)
    ↓
    └── Synthesis Agent (Claude Sonnet)
    ↓
Google Calendar (direct API) · Supabase PostgreSQL · LangSmith Tracing
```

## Getting Started

### Prerequisites

- Python 3.12+
- Node.js 18+
- Accounts: Anthropic, OpenAI, Supabase, LangSmith, Tavily, Google Cloud (OAuth client)

### Backend Setup

```bash
cd backend
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# fill in your API keys
uvicorn main:app --reload
```

### Frontend Setup

```bash
cd frontend
npm install
cp .env.local.example .env.local
# point NEXT_PUBLIC_API_URL at the backend
npm run dev
```

### Environment Variables

**backend/.env**

```bash
SUPABASE_URL=
SUPABASE_SERVICE_KEY=
ANTHROPIC_API_KEY=
OPENAI_API_KEY=
LANGSMITH_API_KEY=
LANGSMITH_PROJECT=prepagent
TAVILY_API_KEY=
GOOGLE_CLIENT_ID=
GOOGLE_CLIENT_SECRET=
JWT_SECRET=
TOKEN_ENCRYPTION_KEY=
FRONTEND_URL=http://localhost:3000
```

**frontend/.env.local**

```bash
NEXT_PUBLIC_API_URL=http://localhost:8000
```

## Deployment

Live: https://useprepagent.app (frontend on Vercel) · API: https://api.useprepagent.app/health

- **Backend:** one EC2 instance running Docker Compose (FastAPI under uvicorn with a **single worker**, Caddy for HTTPS). One worker is required: the OAuth PKCE verifier store and the rate limiter are in process memory, so with more workers about half of sign-ins would fail.
- **Frontend:** Vercel, root directory `frontend`, `NEXT_PUBLIC_API_URL` set for Production (a Vercel production build fails without it).
- **Secrets:** AWS SSM Parameter Store, rendered to a root-only env file on the server; never committed, never in the image or the browser bundle.
- **Access and cost controls:** Google OAuth runs in Testing mode (invite list). The API enforces per-user and global daily briefing caps (defaults 3 and 20), per-IP rate limits on the sign-in endpoints, and kill switches (`SIGNUPS_ENABLED`, `ALLOWED_EMAILS`, `BRIEFINGS_ENABLED`, `CALENDAR_ENABLED`). With `APP_ENV=production` the API refuses to start on missing or weak secrets.
- Design, smoke checklist and rollback: [specs/deployment.md](specs/deployment.md). Operator steps: [deploy/RUNBOOK.md](deploy/RUNBOOK.md).

## Agent Architecture

PrepAgent uses a LangGraph DAG with fixed edges. Company research and interviewer research run in parallel (they're independent), then RAG retrieval pulls relevant resume and briefing context, then synthesis generates the final briefing. Retry logic for insufficient web results lives inside each agent's tool-calling loop rather than in a separate routing layer.


## Key Design Decisions

Full reasoning is in [ARCHITECTURE_DECISIONS.md](ARCHITECTURE_DECISIONS.md) and [docs/decisions.md](docs/decisions.md).

- **Fixed DAG, not a supervisor.** The workflow is deterministic, so a routing LLM call adds latency and cost for no benefit. Retries live inside each agent.
- **pgvector over Pinecone/Qdrant.** The corpus is about 15 resume chunks plus a small set of briefing chunks per user, and Supabase is already in the stack.
- **No reranker.** Retrieval is a SQL filter scoped by `user_id` and company, because the candidate set is already most of the corpus.
- **Cross-contamination prevention.** Briefing chunks are filtered to the target company so other companies' details don't leak into talking points.
- **Guardrails for hallucination.** Source attribution in synthesis, citation validation in code (uncited items are dropped with a warning), and low-result warnings.
- **Identity from the JWT only**, never the request body.
- **Untrusted text is fenced.** Calendar event text, search results and pasted job descriptions are treated as untrusted data; the calendar classifier has no tools and code, not the model, chooses the action.
- **Reliability.** Per-provider timeouts and bounded retries, a 120-second pipeline deadline, and stale-run sweeps so a briefing never hangs on `running`.

## Engineering Workflow

Spec-first (Given/When/Then acceptance criteria in `specs/`), tests written before implementation, an independent review before each commit, and conventional commits. About 690 backend tests plus frontend tests run in GitHub Actions CI (ruff, mypy, pytest, lint, tsc, vitest, build).

## Evaluation

Briefing quality is measured offline with [RAGAS](https://docs.ragas.io), through a harness in `backend/evals/` (spec: [specs/ragas-eval-harness.md](specs/ragas-eval-harness.md)). It is not part of CI or the normal test suite: it makes real API calls.

### What is measured

The harness runs the real LangGraph pipeline over a small golden set of synthetic resumes and public companies (9 cases in `backend/evals/golden_v1.json`, no real personal data) and scores each generated briefing:

- **Faithfulness** — are the claims supported by the web results and resume chunks the pipeline actually had. Reported per group: company overview, interviewer profile, and synthesis. Synthesis is split in two (see below).
- **Answer relevancy** — does the briefing address this specific role and company.
- **Context precision** — are the retrieved resume chunks useful for the briefing. (Context recall is available but opt-in: retrieval returns every chunk, so it is about 1.0 by construction.)

Prior-briefing chunks are never counted as context, because the synthesis prompt cannot cite them.

### How to run it

```bash
source backend/venv/bin/activate && cd backend
python -m evals.run --dry-run --limit 4                     # print the per-model call estimate; no calls
python -m evals.run --limit 4 --web-cache record --label x  # real run: costs money, caches the briefings
python -m evals.run --rescore --metrics faithfulness --limit 4   # judge only, reuses cached briefings
python -m evals.compare evals/results/A.json evals/results/B.json

# Job description comparison: same 3 cases, same recorded web results, JD removed vs present (about $1.2 per arm)
python -m evals.run --dataset evals/golden_v2.json --cases stripe-backend-01,datadog-sre-01,mercury-ambiguous-01 --metrics faithfulness_synthesis,faithfulness_prescriptive --jd off --web-cache record --label jd-off
python -m evals.run --dataset evals/golden_v2.json --cases stripe-backend-01,datadog-sre-01,mercury-ambiguous-01 --metrics faithfulness_synthesis,faithfulness_prescriptive --jd on  --web-cache replay --label jd-on
```

Useful controls: `--limit N` / `--cases id1,id2` / `--all`, `--metrics` to choose what is scored, a preflight that refuses to start above `--max-llm-calls`, and `JUDGE_MODEL` to choose the judge (default `claude-sonnet-5-5`). Needs `ANTHROPIC_API_KEY`, `TAVILY_API_KEY` (not for web-cache replay) and `OPENAI_API_KEY` (answer-relevancy embeddings). Rough cost for 4 cases with the default judge is about $1.50 for a full run.

### Results

Committed scores-only snapshots are in `backend/evals/baselines/`. Both runs below use the same 4 cases (the first four golden cases), the Sonnet judge, and metric definitions v2. The hedged run scored only the two synthesis metrics, so the other metrics are marked "not run" rather than assumed.

| Metric (mean over 4 cases) | Baseline (synthesis prompt `228b958d479e`) | After hedging prompt (`f7be121b67df`) |
|---|---|---|
| Faithfulness, company overview | 0.99 | not run |
| Faithfulness, synthesis, factual fields (main) | 0.72 | 0.71 |
| Faithfulness, synthesis, prescriptive fields | 0.79 | 0.77 |
| Faithfulness, synthesis, all fields as written | 0.56 | not run |
| Answer relevancy | 0.81 | not run |
| Context precision | 0.72 | not run |
| Faithfulness, interviewer profile | n/a (no case has an interviewer) | n/a |

Per case, factual synthesis faithfulness was 0.67 / 0.87 / 0.76 / 0.57 for the baseline and 0.57 / 0.74 / 0.71 / 0.82 after the prompt change (Stripe / Shopify / Datadog / Mercury). The starting threshold for faithfulness is 0.85, so the baseline is below it.

For reference only, `golden_v1.json` is an earlier baseline over all 9 cases scored by an Opus judge under the older v1 metric definitions (company 0.97, interviewer 0.91 on 2 cases, synthesis 0.64, answer relevancy 0.79, context precision 0.72, context recall 1.00). It is **not comparable** to the table above (different judge, different synthesis definition, different cases).

#### Job description input (3 cases)

A separate comparison on `golden_v2.json` (the 9 golden cases, with a synthetic job description added to 3 of them: Stripe, Datadog, Mercury). Same 3 cases, same recorded web results, same Sonnet judge, metric definitions v2; only the job description differs (`--jd off` vs `--jd on`). Only the two synthesis metrics were scored, so the rest are "not run". Snapshots: `backend/evals/baselines/golden_v2_sonnet_metric_v2_jd_off.json` and `..._jd_on.json` (label `sonnet-judge-metric-v2-jd-spike`).

| Metric (mean over 3 cases) | Without a JD | With a JD |
|---|---|---|
| Faithfulness, synthesis, factual fields | 0.56 | 0.99 |
| Faithfulness, synthesis, prescriptive fields | 0.74 | 0.91 |
| `key_requirements` items tagged `[JD]` | n/a | 29 of 29 |
| Items removed by the citation check | n/a | 0 |

Per case (Stripe / Datadog / Mercury), factual: 0.58 / 0.47 / 0.62 without, 1.00 / 1.00 / 0.97 with. Prescriptive: 0.74 / 0.78 / 0.69 without, 1.00 / 0.73 / 1.00 with, so one case got slightly worse. Answer relevancy and context precision were not measured. These runs used the same synthesis code as the shipped feature; the form, API and viewer were not part of the eval.

### Key findings

- **The first synthesis faithfulness score was mostly measuring wording.** It scored every synthesis field as written, including talking points, stories and conversation starters. A claim-level audit of that run found that most claims the judge marked unsupported were advice phrasing ("one talking point is to..."), which no source can contain. The synthesis metric is now split: factual fields (role insights, shared interests) are scored as written, and prescriptive fields are scored on the facts they rely on. The old all-fields score is kept as a separate metric. On the Sonnet-judged baseline the three read 0.72 (factual), 0.79 (prescriptive) and 0.56 (all fields as written).
- **A synthesis-prompt change that hedges inferred claims showed no measurable change.** The prompt now asks for inferred requirements and connections to be phrased as hedged inferences tied to a specific fact. On 4 cases, factual synthesis faithfulness went from 0.72 to 0.71 and prescriptive from 0.79 to 0.77, with per-case swings of -0.13 to +0.25 in both directions. That is within what a single judge pass on 4 cases cannot distinguish from noise, so the change is neither confirmed nor ruled out. Answer relevancy and context precision were not re-measured under the new prompt.
- **With a job description, requirements stopped being unsupported inferences, on 3 synthetic cases.** Factual synthesis faithfulness went from about 0.56 to about 0.99, all 29 `key_requirements` items carried `[JD]`, and none was removed by the citation check. Read this narrowly: the job description is now one of the contexts the judge checks against, so requirements that restate it are easy to support. It shows the requirements are grounded in the pasted text, not that the briefings are better or more useful.
- Faithfulness of the company overview is high (0.99 on 4 cases); the weakest area is synthesis.

### Limitations

- **Only 4 cases** (the first four of 9), none with an interviewer, so interviewer faithfulness is unscored and nothing here exercises the no-resume or fictional-interviewer cases.
- **Single judge pass, no repeats.** Judge variance has not been measured, and each run regenerated the briefings, so differences between runs mix prompt effects with generation and judge randomness.
- **The judge is the same model as the generator** (`claude-sonnet-5-5`), so scores are likely optimistic (self-preference). The harness flags such runs as self-grading.
- **Results are not comparable to the Opus-judged `golden_v1.json` baseline**: a different judge and different metric definitions change every score.
- The hedging run covered two metrics only, so its effect on relevancy and precision is unknown.
- Context precision mostly reflects how relevant the resume is to the target, and context recall is about 1.0 by construction, because retrieval returns every chunk (ADR section 3).
- **The job-description result is a best case.** The 3 job descriptions are clean, generic, synthetic postings written for the test, not real, long or messy ones, so it says little about how a real posting behaves. It covers only 3 cases, a single judge pass, and the judge is the generating model (self-graded, likely optimistic). Answer relevancy was not measured, and one case's prescriptive score fell.
- Resumes and companies are synthetic or public; thresholds are starting baselines, not gates.

### Planned

- A full 9-case Sonnet-judged baseline, including interviewer cases.
- Repeat runs to measure judge and generation noise.
- A non-generator judge, validated against the Opus-scored baseline.

## License

MIT

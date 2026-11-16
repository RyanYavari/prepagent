# Spec: RAGAS Evaluation Harness

## Problem
ARCHITECTURE_DECISIONS.md §5 promises RAGAS scoring (relevancy, faithfulness, context precision) with a golden set, but nothing exists: `services/eval.py` is empty, there is no dataset, and no baseline numbers. Prompt and retrieval changes (synthesis guardrails, the chunk writer) are currently judged by eye.

## Goal
`python -m evals.run` (from `backend/`) runs the real graph over a small synthetic golden set, scores each briefing with RAGAS under a hard LLM-call cap, writes a timestamped results JSON and prints a summary table, and `python -m evals.compare` shows a before/after diff between two result files.

## Non-goals
- No CI, no pytest-suite eval runs; no pass/fail gate (thresholds are reported, exit code stays 0)
- No real resumes, real candidate data, or Supabase writes
- No changes to agent prompts, retrieval, or pipeline behavior (the harness observes; it does not alter production code paths)
- No LLM-as-judge rubric beyond the four RAGAS metrics (the `/eval` skill's 1-5 rubric is out of scope)
- No dashboard/UI, no scheduled runs

## Design

### Layout
Everything lives under `backend/evals/` so `python -m evals.run` works from `backend/` like `python -m scripts.…` does.

```
backend/evals/
  __init__.py
  dataset.py        # load + validate golden JSON (pydantic)
  golden_v1.json    # versioned dataset (synthetic)
  collect.py        # run one case through the graph, capture contexts + answer
  samples.py        # map a CollectedCase -> RAGAS samples (the definitions below)
  score.py          # RAGAS adapter, counting judge wrapper, aggregation, thresholds
  report.py         # results JSON + terminal table
  run.py            # CLI
  compare.py        # before/after diff of two results files
  results/          # gitignored output
```
Unit tests: `backend/tests/evals/` (mirrors source; mocked scorers).

### Pipeline execution (what "real pipeline" means here)
`collect.py` calls `build_graph().invoke(state)` directly, with real Tavily and real Claude, so the real nodes, prompts, guardrails and citation validation all run. It does **not** call `run_pipeline` (that persists to the `briefings` table and writes chunks). Two seams are substituted, in the harness only, never in production code:

1. **Retrieval.** `retrieve_user_context` is replaced by an in-memory version that runs `chunk_resume()` on the case's synthetic resume and returns the same `RetrievalResult` shape, plus any `prior_briefings` the case defines as `doc_type='briefing'` chunks. Retrieval is a SQL filter (ADR §3), so no embeddings and no Supabase are needed. Consequence: the eval never touches a user's data. It does *not* exercise the SQL filter itself (already covered by `test_retrieval`).
2. **Web results capture.** The graph state keeps only the LLM summary and source URLs, not the raw Tavily results the summary was written from. Faithfulness needs those results as context, so `collect.py` wraps `search_web` (in `agents.company` and `agents.interviewer`) to record every `SearchResult` returned, tagged by which node asked. Same results the node saw, so scores reflect what the model actually had. Record/replay cache: see Decisions #4.

### Definitions: question, answer, contexts
Notation: `web_c` = company search results (title + url + content), `web_i` = interviewer search results that survived the node's name filter, `resume` = retrieved resume chunks (`[Section] content`), `prior` = same-company prior-briefing chunks.

**Question** (same string for all metrics, deterministic template, no resume text in it):
`Prepare an interview briefing for the {role|"unspecified"} role at {company}{, interviewing with {interviewer}}.`

**Rendered text.** Sections are flattened with the same field-by-field rendering idea as `briefing_chunks.render_sections`. Before scoring, citation tags `[Source: …]` and `[Resume: …]` are stripped (they are provenance markers, not claims, and URLs add noise to claim extraction). `warnings` are never scored.

| Metric | Answer | Contexts |
|---|---|---|
| **Faithfulness: company** | `company_overview` (summary, news, tech stack, culture) | `web_c` |
| **Faithfulness: interviewer** | `interviewer_profile.summary` + `background` (skipped if no interviewer or no results) | `web_i` |
| **Faithfulness: synthesis** | `role_insights` (requirements, alignment, gaps) + `talking_points.talking_points` + `stories_to_prepare` + `shared_interests` + `conversation_starters` | `web_c` + `web_i` + `resume` |
| **Answer relevancy** | The whole rendered briefing (all four sections including `suggested_questions`; no warnings) | n/a (question + answer only) |
| **Context precision** | n/a (scores the retrieval step; see below) | `resume` (ordered as retrieved) |
| **Context recall** | n/a | `resume` |

Faithfulness is reported per section group *and* as a case-level mean, because the ADR's predicted weak spot (invented resume↔company links) lives in the synthesis group and would be diluted by two passthrough groups that are near-extractive and score high. `suggested_questions` are excluded from faithfulness: they are questions to ask, not claims.

**Context precision / recall (retrieval step).** The question for these is the same template; contexts are the resume chunks the retrieval step returned; the reference is the case's hand-written `reference` (see dataset). Honest caveat recorded in the report: retrieval currently returns *every* resume chunk (ADR §3), so
- *recall* will be ~1.0 by construction and works as a regression guard (e.g. a chunking bug that drops the Experience section), not as a quality signal;
- *precision* measures how much of the resume is relevant to this company/role, which is a property of the resume and the target more than of the retrieval code. It becomes a real signal only if retrieval ever becomes selective (e.g. top-k).

**Prior-briefing chunks.** They are retrieved and shown to the synthesis LLM but are explicitly not citable. Decision (Decisions #3): **excluded from every scored context list**, because (a) a claim that is only supported by an earlier generated briefing would pass faithfulness while being unsupported by any primary source, which launders earlier hallucinations; (b) the validator drops items that cite them anyway. They are tracked as diagnostics instead: per case `prior_briefing_chunk_count` and `unsupported_by_primary_but_in_prior`, computed by re-scoring synthesis faithfulness *with* `prior` added and reporting the difference. Only cases that seed prior briefings pay for that second faithfulness call.

### Golden dataset (`golden_v1.json`)
9 cases. Versioned by filename and a `version` field; changing a case means a new file (`golden_v2.json`), so old results stay interpretable.

```json
{
  "version": "v1",
  "cases": [{
    "id": "stripe-backend-01",
    "company": "Stripe",
    "role": "Backend Engineer",
    "interviewer": null,
    "resume_text": "<synthetic resume, section headers Experience/Education/Skills/...>",
    "prior_briefings": [{"company": "Stripe", "role": "...", "section": "...", "content": "..."}],
    "reference": ["fact or expectation 1", "..."],
    "interviewer_kind": null,
    "tags": ["no-interviewer"]
  }]
}
```
- `reference` is a short list (3-6 lines) of the **resume-side facts a good briefing should draw on** for this role/company (e.g. "Led a Go and PostgreSQL ledger service at Halcyon Systems"). Because context recall/precision score the retrieved resume chunks, company-side facts do not belong here (they live in web results, not the resume). For the no-resume case it states the expected behavior. Not a full golden briefing.
- Mix (proposal): well-known companies across sectors; 1 ambiguous name (Mercury); 1 case with no resume (exercises the no-resume warning; resume-dependent metrics reported as `null`); 2 cases with a public-figure interviewer; 2 with a fictional interviewer name (exercises the low-result/wrong-person guardrails); the rest no interviewer; 2 cases seed prior briefings for the same company.
- Synthetic means invented people, invented employers (clearly fictional, e.g. "Northwind Labs"), no real names, emails, phone numbers, schools-with-real-people. A loader validation rejects emails, phone-number patterns and URLs inside `resume_text`.

### Scoring
- RAGAS 0.4.3 (already pinned in `requirements.txt`). **The exact metric class names and the LLM/embeddings wrapper API differ between RAGAS versions; slice 3 starts with a short spike against the installed version before code is written.**
- Judge LLM: `JUDGE_MODEL` env (default `claude-opus-5-5`, see Decisions #6). Judge embeddings for answer relevancy: `EVAL_EMBEDDING_MODEL` (default `text-embedding-3-small`, needs `OPENAI_API_KEY`).
- Judge calls go through a counting wrapper (below). A metric that errors yields `null` with the error class recorded, not a crash and not a silent 0.

### Cost and safety controls
| Control | Behavior |
|---|---|
| `--cases N` | Run the first N cases (default 3). `--ids a,b` selects specific cases. `--all` runs everything. |
| `--max-llm-calls K` | Hard cap (default 150) over pipeline **and** judge calls. A counting wrapper around the judge LLM, plus counted pipeline nodes, raises `BudgetExceeded` *before* the call that would exceed K. The run stops, results gathered so far are written with `"truncated": true`. |
| Preflight | Before any call, print the estimate (pipeline ≈ 3 Claude calls + ≤ 6 Tavily calls per case; scoring ≈ 25-40 judge calls per case, to be calibrated from the first real run) and abort if the estimate for the selected cases exceeds K, unless `--force`. |
| `--dry-run` | Validate dataset, print the plan and estimate, make no calls. |
| Secrets | Keys are read from env only and never printed or put in results. Logs and results contain case ids, scores, counts, and timings. Resume text is never logged (it does appear in results JSON as a retrieved context, which is acceptable only because every case is synthetic; the results dir is gitignored). Exceptions are logged by class only (same rule as `net_config.retry_call`). |
| Isolation | Runs refuse to start if `PYTEST_CURRENT_TEST` or `CI` is set. Nothing under `tests/` imports a real scorer; `pytest` collects `tests/evals/` only (testpaths unchanged), `evals/run.py` is never imported by `main.py`. |

### Thresholds (starting baseline, reported not enforced)
From ADR §5 and the `/eval` skill: faithfulness ≥ 0.85, answer relevancy ≥ 0.80, context precision ≥ 0.70, context recall ≥ 0.75. Terminal table marks each score `ok` / `LOW` and the summary row shows the mean per metric. First real run's numbers are saved as the baseline file and the thresholds are revisited against it.

### Results JSON (`evals/results/<UTC timestamp>[-label].json`)
```
meta:   run_id, started_at, label, dataset_version, dataset_sha256, cases_run, truncated,
        llm_calls {pipeline, judge, cap}, tavily_calls,
        git {sha, dirty},
        config {agent_model, judge_model, embedding_model, ragas_version,
                prompt_hashes {company, interviewer, synthesis}, retrieval_mode}
cases:  [{id, tags, question, scores {metric: float|null}, score_errors, thresholds_met,
          contexts {web_company, web_interviewer, resume, prior_count},
          answer {rendered sections}, pipeline_warnings, elapsed_seconds}]
summary: {metric: {mean, min, n, below_threshold_count}}
```

### Before/after comparison
1. Run `python -m evals.run --label baseline-<change>` before the change and `--label <change>` after, with the same `--ids`/dataset.
2. `python -m evals.compare results/A.json results/B.json` prints per-metric mean delta and per-case deltas, and refuses a silent apples-to-oranges comparison: it prints a loud notice listing every `meta` field that differs (dataset version/sha, judge model, agent model, prompt hashes, ragas version) so a prompt change is distinguishable from a judge change, and only compares cases present in both.
3. Noise handling: the judge is stochastic and Tavily results drift, so each comparison states that deltas under ±0.05 are within noise until measured. Slice 5 includes a `--repeat 2` option to estimate that noise on a single case set (costs 2×). With the web cache (Decisions #4) the web-side drift is removed.
4. The record of a comparison is the pair of result files (kept locally, gitignored) plus a one-line entry in `docs/decisions.md` via `/why` when the change is architectural. A committed `evals/baselines/golden_v1.json` holds a *scores-only* snapshot (no contexts or answers) so the repo records the accepted baseline.

### LangSmith (optional)
If `LANGSMITH_TRACING=true` and `LANGSMITH_API_KEY` are set, each case's graph run gets `run_name="eval_case"`, `tags=["eval", run_id]`, and its metric scores are attached as feedback via the LangSmith client; failures to post feedback are logged by class and never fail the run. Env unset: no import of the client, no network. Note that LangSmith tracing already sends prompts and outputs; this is acceptable only because the dataset is synthetic.

## Acceptance Criteria

### Given a valid `golden_v1.json`
### When `load_dataset()` is called
### Then it returns validated cases with unique ids, and `dataset_sha256` is stable across loads

### Given a dataset case with an email, phone number, or URL in `resume_text`, a duplicate id, or a missing `company`
### When the dataset is loaded
### Then loading fails with an error naming the case id (not echoing the resume text)

### Given `--cases 2`
### When the harness runs
### Then exactly the first 2 cases are collected and scored and `meta.cases_run == 2`

### Given a case with a resume and no interviewer
### When samples are built
### Then the interviewer-faithfulness sample is omitted (score `null`), the question has no interviewer clause, and the other samples use the contexts defined in the table above

### Given a case with prior briefings seeded
### When samples are built
### Then no scored context list contains a prior-briefing chunk, `prior_count` is recorded, and the with-prior faithfulness diagnostic is computed separately

### Given a briefing whose items contain `[Source: …]` and `[Resume: …]` tags and a `warnings` list
### When the answer text is rendered
### Then tags are stripped, warnings are absent, and `suggested_questions` are excluded from the faithfulness answer but present in the answer-relevancy answer

### Given a case with no resume on file
### When it is scored
### Then resume-dependent metrics are `null` (not 0), the case still reports company faithfulness and relevancy, and the pipeline's no-resume warning is recorded

### Given `--max-llm-calls K` and a judge that would exceed it mid-case
### When scoring runs
### Then `BudgetExceeded` is raised before the K+1th call, completed cases are written, and the results file has `truncated: true` and accurate call counts

### Given a preflight estimate above the cap
### When run without `--force`
### Then the harness aborts before any network call and prints the estimate

### Given `--dry-run`
### When run
### Then no LLM, Tavily or Supabase client is constructed

### Given a scorer that raises for one metric on one case
### When scoring runs
### Then that score is `null` with the error class in `score_errors`, other metrics and cases still score, and the exception message is not logged

### Given scores for several cases
### When aggregated
### Then the summary has mean/min/n per metric ignoring `null`s, flags scores below threshold, and returns exit code 0 regardless

### Given `CI=true` or a pytest process
### When `evals.run` is invoked
### Then it refuses to run

### Given API keys in the environment
### When a run completes
### Then no log line, terminal output, or results file contains a key value or an `Authorization` header

### Given two results files with different `prompt_hashes` and the same dataset
### When `evals.compare` runs
### Then it prints per-metric and per-case deltas for shared cases and lists the differing meta fields

### Given two results files with different dataset versions
### When `evals.compare` runs
### Then it warns that the comparison is not like-for-like and compares only shared case ids

### Given `LANGSMITH_*` env vars unset
### When a run completes
### Then no LangSmith client is imported; given them set and a feedback call that fails, the run still completes

### Given the existing suite
### When `pytest -x -q` runs
### Then `tests/evals/` passes with mocked scorers and no network, and no test requires real keys

## Affected Files
- `backend/evals/{__init__,dataset,collect,samples,score,report,run,compare}.py` (new)
- `backend/evals/golden_v1.json` (new), `backend/evals/baselines/` (new, scores-only), `backend/evals/results/` (gitignored)
- `backend/tests/evals/test_*.py` (new)
- `.gitignore` (add `backend/evals/results/`, optional `backend/evals/cache/`)
- `backend/requirements.txt` only if the RAGAS spike shows a missing dependency (ragas, datasets, langchain-openai already pinned)
- `CLAUDE.md` (Current State, Commands), `docs/decisions.md` (if the prior-briefing decision stands)
- No production modules changed

## Dependencies
- Real run needs `ANTHROPIC_API_KEY`, `TAVILY_API_KEY`, `OPENAI_API_KEY` (judge embeddings); `SUPABASE_*` not needed
- RAGAS 0.4.3 API spike (slice 3)
- Hand-written `reference` lists for the 9 cases (about 15 min per case; the main human effort)

## Decisions (approved 2026-11-15)
1. **Location:** `backend/evals/` (run from `backend/`).
2. **Ground truth:** a short hand-written `reference` fact list per case, not full golden sections.
3. **Prior briefings:** excluded from every scored context; tracked as a diagnostic (`prior_count` and a with-prior faithfulness delta).
4. **Web determinism:** record/replay cache added. `--web-cache record|replay|off` (default `off`; `replay` reads `backend/evals/cache/` keyed by query hash and falls back to a live search + record on a miss only in `record` mode; in `replay` a miss is an error). Cache is gitignored. Cache records are public web content only.
5. **Interviewers:** a mix, labelled in the dataset with `interviewer_kind: "public_figure" | "fictional" | null`. Public-figure cases use well-known executives; fictional cases exercise the low-result/wrong-person guardrails and are expected to score `null`/low on the interviewer metric.
6. **Judge model:** separate env var `JUDGE_MODEL`, default `claude-opus-5-5` (differs from the `AGENT_MODEL` default `claude-sonnet-5-5`). If the resolved judge equals the resolved agent model the run still proceeds, logs a warning, prints a "self-grading" line above the table and records `meta.self_grading: true`. Limitation documented: a model grading its own output tends to rate it higher (self-preference), so absolute scores are optimistic; before/after deltas under one judge are still meaningful, and `compare` flags a judge change.
7. **(not asked, recommended default used) Cap defaults:** `--cases 3`, `--max-llm-calls 150`. Per-case budget estimate calibrated against the ragas 0.4.3 implementation: pipeline 3 Claude calls (+ up to 6 Tavily), judge about 15 (faithfulness 2 x 3 groups, answer relevancy 3, context precision one per resume chunk, context recall 1), plus 2 for the optional prior-briefing diagnostic. Preflight uses 22 calls/case and is recalibrated after the real run.
8. **(not asked, recommended default used) LangSmith:** kept as the last, optional slice.

### RAGAS 0.4.3 spike (done before slice 3)
Metrics live in `ragas.metrics.collections` (`Faithfulness`, `AnswerRelevancy`, `ContextPrecisionWithReference`, `ContextRecall`); each exposes `async ascore(...)` returning `MetricResult(.value)`. They require an `InstructorBaseRagasLLM` (`generate`/`agenerate(prompt, response_model)`) and `AnswerRelevancy` a `BaseRagasEmbedding`. The harness supplies its own judge implementing that interface on top of the project's LangChain `ChatAnthropic` with `method="json_schema"` (the same path that works on the model; no `temperature`, which the model rejects), and a thin OpenAI embeddings class. Every judge call goes through the counter, which is how the hard cap is enforced. Legacy `ragas.evaluate()` / `Dataset` are not used.

### Calibration from the first real run (2 cases)
Judge calls were 14-15 per case plus 2 for the prior diagnostic; pipeline 3 per case with an interviewer, 2 without. The 22/case preflight estimate stays as headroom. Judge `max_tokens` is 12000 because faithfulness verdicts list every claim. Not done: a committed scores-only baseline (needs a full `--all` run).

## Metric v2 (2026-11-15): factual vs prescriptive synthesis faithfulness
**Why.** The first full baseline scored synthesis faithfulness 0.64. A claim-level audit of the judge's verdicts (374 claims, 8 cases) found about 100 of 122 unsupported claims were advice-shaped ("One talking point is to...", "A suggested conversation starter is...", story templates). RAGAS splits answers into statements; for prescriptive items the statement is about the briefing itself, which no context can contain. So the score mostly measured wording, not hallucination.

**Change.**
- `faithfulness_synthesis` (main synthesis metric) now scores the *factual* fields as written: `role_insights` (requirements, alignment, gaps) and `shared_interests`, against web results + resume chunks.
- `faithfulness_prescriptive` covers `talking_points`, `stories_to_prepare` and `conversation_starters`. A judge call first rewrites the items into standalone factual statements they rely on (advice, questions, framing and story templates dropped, no new facts added), then those facts are scored against the same contexts. Zero facts gives `null`, not 0.
- `faithfulness_synthesis_all` is the v1 definition (all synthesis fields as written), kept for continuity and reported beside the others in the table, summary and `compare`.
- Case-level `faithfulness` (f.mean) averages company, interviewer and synthesis (factual); prescriptive is reported separately. Thresholds apply to every faithfulness metric (0.85).
- `suggested_questions` stay excluded; the prior-briefing diagnostic now compares against the factual synthesis score.
- `meta.config.metric_version` is 2 (v1 baseline files have none/1), so `compare` lists it as a difference.
- Cost: about 5 more judge calls per case (all: 2, prescriptive: 3); preflight estimate is now 27 calls per case.

**Caveats.** The extraction step is itself LLM work and can drop or soften a claim, so `faithfulness_prescriptive` is a less strict measure than the factual score and should be read as "are the facts behind the advice supported". The metric is not a gate and v1 vs v2 numbers are not directly comparable except `faithfulness_synthesis_all`.

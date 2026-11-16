# Decision Journal

Architectural decisions for PrepAgent. Each entry answers the interview question: "Why did you choose X over Y?"

---

## 2024-11-11 Fixed DAG over supervisor pattern for agent orchestration

**Status:** Accepted

**Context:**
PrepAgent uses multiple LLM-powered agents (company researcher, role analyzer, question generator, etc.) that need to be orchestrated. The two main patterns are a supervisor agent that dynamically routes, or a fixed DAG with predetermined flow.

**Decision:**
Use LangGraph's fixed DAG pattern with explicit node transitions.

**Alternatives considered:**
- Supervisor/router pattern: Rejected because it adds latency (extra LLM call to decide routing), costs more tokens, and introduces nondeterminism that makes debugging harder.
- Simple sequential chain: Rejected because some nodes can run in parallel (company research + role analysis).

**Tradeoffs:**
- Pro: Deterministic, debuggable, cheaper (no routing LLM call), parallelizable branches
- Con: Less flexible if workflow needs to change dynamically based on input

**Revisit when:**
If user research shows that different input types need fundamentally different processing paths.

---

## 2026-11-15 Calendar detection is a classifier gate, not a supervisor

**Status:** Accepted

**Context:**
Calendar events should turn into briefings automatically. Deciding "interview or not" is the first branching decision in the system that needs LLM judgment, and event text is attacker-controllable (anyone can send an invite).

**Decision:**
One no-tools structured LLM extraction per event, then deterministic code (`decide()`) picks ignore / confirm / auto-create. The research pipeline stays a fixed DAG. Auto-run is opt-in via `CALENDAR_AUTO_CONFIDENCE_THRESHOLD`; the default confirms everything.

**Alternatives considered:**
- Supervisor agent with calendar tools: puts tools next to untrusted text and is nondeterministic for a one-shot classification.
- LLM chooses the action: an injected event could select its own outcome; code-owned routing bounds the blast radius to a pending briefing.
- Always auto-run or never auto-run: the first hides wrong extractions behind a pipeline run, the second skips reliable structured data; opt-in threshold sits between.

**Tradeoffs:**
- Pro: small injection blast radius, deterministic and testable routing, no change to the research DAG.
- Con: one LLM call per candidate event; confidence is self-reported by the model, so it is only one of several gates.

**Revisit when:**
Auto-run is enabled for real use and misfires are observed, or a second source (Gmail) needs the same gate.

---

## 2026-11-15 Calendar trigger: on-demand polling now, watch channels later

**Status:** Accepted

**Context:**
ADR section 4 used push notifications for Gmail. The calendar MVP runs on localhost with no public HTTPS endpoint.

**Decision:**
Poll on demand (dashboard load, "Sync now", optional interval loop). The sync function is idempotent and dedupes in the database (UNIQUE user + event id), so a webhook-triggered sync can call it unchanged later.

**Alternatives considered:**
- `events.watch` channels now: needs a public webhook, channel renewal and webhook auth; too heavy for local-first.
- syncToken incremental sync: unnecessary while dedupe makes re-reading a 14-day window harmless.

**Tradeoffs:**
- Pro: works locally, simple, no channel lifecycle to manage.
- Con: detection latency equals the poll interval; more Google API reads than push.

**Revisit when:**
Deploying publicly or when polling volume matters.

---

## 2026-11-15 Direct Google Calendar API over an MCP server

**Status:** Accepted

**Context:**
The resume claims an MCP-native system, so MCP for Calendar access was evaluated (langchain-mcp-adapters).

**Decision:**
Use the Google Calendar API directly via httpx. No part of this phase is MCP-based.

**Alternatives considered:**
- Calendar MCP server: the ones I know of are designed for a single local user (per-user token handling in a multi-tenant app would need a custom server), add a process boundary around one deterministic call, and tempt handing tools to a model that reads untrusted text. No specific server or langchain-mcp-adapters version was evaluated.

**Tradeoffs:**
- Pro: our own encryption/refresh/revoke path, no new dependency, no tool access for the classifier.
- Con: forgoes an "MCP-native" claim for this feature.

**Revisit when:**
Exposing PrepAgent itself as an MCP server (real MCP, small), or a multi-tenant calendar MCP server exists.

---

---

## 2026-11-15 Stop storing sign-in Google tokens (instead of encrypting them)

**Status:** Accepted

**Context:**
`/auth/callback` stored Google access and refresh tokens in plaintext in `users`. Nothing read them, and calendar access now has its own encrypted store (`calendar_connections`).

**Decision:**
Sign-in uses Google only for identity: tokens stay in memory for the userinfo call, are never persisted or logged, and the flow no longer requests offline access. Existing tokens are revoked at Google by a one-off script, then migration 005 drops the columns.

**Alternatives considered:**
- Encrypt the sign-in tokens: Rejected because nothing consumes them; it would keep a secret with no purpose.
- Null the columns but keep them: Rejected because new code could start writing plaintext again; dropping removes the temptation.
- Run the migration only (no revoke): Rejected because nulling leaves old Gmail/Drive grants live at Google.

**Tradeoffs:**
- Pro: smaller breach blast radius, less code, old broad grants closed
- Con: if sign-in ever needs Google APIs, it must re-request consent; revoking may also invalidate a user's calendar connection (they reconnect)

**Revisit when:**
Sign-in itself needs offline access to a Google API.

---

## 2026-11-15 RAGAS eval harness: observe the real graph, exclude prior briefings from scored contexts

**Status:** Accepted

**Context:**
ADR section 5 promised RAGAS scoring but nothing existed. The graph keeps only summaries and source URLs (not the raw web results), and retrieval returns every resume chunk plus same-company prior briefings, which synthesis may not cite.

**Decision:**
`backend/evals/` runs `build_graph()` directly over a synthetic golden set with harness-only seams (in-memory retrieval, recorded web results with optional record/replay cache, counted LLM calls). Scoring uses ragas 0.4.3 collections metrics through a custom judge on ChatAnthropic, with a hard LLM-call cap. Prior-briefing chunks are never a scored context; they feed a with-prior faithfulness diagnostic. Judge model is `JUDGE_MODEL` (default differs from the agent model; equal models are flagged as self-grading). Thresholds are reported, not enforced; evals never run in CI or pytest.

**Alternatives considered:**
- Count prior briefings as context: Rejected because an earlier hallucination would then validate a later claim.
- Call `run_pipeline`: Rejected because it persists to Supabase and writes chunks.
- Legacy `ragas.evaluate()`/`Dataset`: Rejected because 0.4.3 collections metrics are the maintained path and let every judge call be counted against the cap.
- Same model as judge: Rejected as the default because of self-preference bias.

**Tradeoffs:**
- Pro: no production code changed, no user data touched, before/after runs comparable with cached web results
- Con: context recall is about 1.0 by construction (retrieval returns all chunks) and precision mostly reflects the resume; the judge costs about 15 calls per case

**Revisit when:**
Retrieval becomes selective (top-k or reranked), or a prior-briefing citation format is introduced.

---

## 2026-11-15 Split synthesis faithfulness into factual and prescriptive (metric v2)

**Status:** Accepted

**Context:**
Synthesis faithfulness scored 0.64, but about 100 of 122 flagged claims were advice wording ("a talking point is to...", story templates) that no context can contain, plus a handful of genuine stretched inferences and about two overgeneralised facts. The number could not tell a hallucination from a prescriptive sentence.

**Decision:**
The main synthesis score covers factual fields only (role insights, shared interests). Talking points, stories and conversation starters are scored by first extracting the facts they rely on with a judge call, then checking those facts. The old all-fields score stays as `faithfulness_synthesis_all`, and results record `metric_version: 2`.

**Alternatives considered:**
- Change the synthesis prompt first: Rejected because the change would be measured against a score that is mostly artifact.
- Drop prescriptive fields from scoring entirely: Rejected because their cited facts are where ADR section 6's stretched-connection failure shows up.
- Rewrite items with regexes instead of a judge call: Rejected because advice and fact are interleaved in free text.

**Tradeoffs:**
- Pro: the headline metric now moves when facts get less supported, not when phrasing changes
- Con: about 5 extra judge calls per case; the extraction step can itself drop claims, so the prescriptive score is more lenient; v1 and v2 baselines are comparable only through `faithfulness_synthesis_all`

**Revisit when:**
Synthesis output gains structured citations per item (then check the citation directly instead of extracting facts).

---

## 2026-11-15 Eval cost controls: opt-in recall, briefing cache, Sonnet judge

**Status:** Accepted

**Context:**
A full eval run cost about 200 LLM calls with an Opus judge, repeated in full on every scoring change because each run re-ran the pipeline, and it paid for context recall (about 1.0 by construction).

**Decision:**
Metrics are selectable and context recall is opt-in. Generated briefings are cached so `--rescore` calls only the judge. A preflight prints per-model call estimates and refuses to start above `--max-llm-calls` (no override flag). The judge default moves to `claude-sonnet-5-5`; the Opus-scored `golden_v1.json` baseline stays but is labelled, and `compare` warns that scores from different judges are not comparable.

**Alternatives considered:**
- Keep Opus as the judge and cut cases: Rejected because the case count was already small and judge cost scales with every re-score.
- Haiku as the default judge: Rejected as a default because NLI verdict quality on long contexts is unproven; it remains one env var away.
- Re-run the pipeline for every re-score: Rejected because it pays for generation to change only the grader.
- Keep a `--force` to bypass the cap: Rejected because the point of the cap is a refusal.

**Tradeoffs:**
- Pro: a rescore of 4 cases is about 40-65 calls instead of about 100; metric choice controls cost directly
- Con: the default judge equals the default agent model (self-grading, optimistic scores); older baselines are not comparable to new runs; cached briefings can lag the prompts unless the pipeline is re-run

**Revisit when:**
A cheaper non-self-grading judge (or batch pricing for the judge) is validated against the Opus-scored baseline.

---

## 2026-11-15 Synthesis prompt: hedge inferences, frame requirements as inferred, no trend generalisation

**Status:** Accepted (not yet measured: no live eval was run for this change)

**Context:**
The claim-level audit of the eval baseline found the real faithfulness problems were few but specific: role requirements stated as fact with no job description to support them, resume-to-company connections presented as established, gaps inferred from what a resume omits, and one cited event stretched into a trend (a single acquisition described as acquisitions in a whole area).

**Decision:**
One addition to `SYSTEM_PROMPT` in `agents/synthesis.py` (nothing else changed): (1) anything inferred rather than stated in the context (a requirement, a candidate-to-company connection, a gap) is phrased as a hedged inference ("likely", "based on the company's focus on X") and tied to the specific company or resume fact it rests on, cited as before; (2) because no job description is provided, role requirements are framed as inferred from the company research, never as stated requirements; (3) never generalise a single cited event into a trend or pattern. Prior briefings stay background only and not citable, and the citation tags and the drop-if-uncitable rule are unchanged.

**Prompt hash (eval `prompt_hashes.synthesis`, sha256 prefix of `SYSTEM_PROMPT`):** `228b958d479e` before, `f7be121b67df` after. The company and interviewer hashes are unchanged (`1b541070a6cf`, `250c3b7e53c8`). Every existing eval result and baseline, including `golden_v1.json`, was generated under the old synthesis hash.

**Alternatives considered:**
- Drop unsupported requirements entirely: Rejected because inferred requirements are useful to a candidate; hedging keeps them honest.
- Enforce hedging in code (post-validation): Rejected for now because there is no reliable way to detect an unhedged inference without another LLM call.
- Change scoring instead of the prompt: Already done (metric v2); this targets the residual real claims.

**Tradeoffs:**
- Pro: inferred items become visibly inferred, so a wrong inference reads as a guess, not a fact
- Con: more hedged wording may read as less confident; items without a citable fact may now be dropped more often; the effect is unmeasured until a live eval (`--rescore` cannot test it because it reuses briefings made with the old prompt, so a normal run is needed)

**Revisit when:**
A Sonnet-judged metric-v2 run on the new prompt shows whether synthesis faithfulness, answer relevancy and the dropped-citation counts moved; revert if relevancy or usefulness drops without a faithfulness gain.

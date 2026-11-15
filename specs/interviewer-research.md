# Spec: Interviewer Research Agent

Source of truth: `ARCHITECTURE_DECISIONS.md` §1 (fixed DAG, retry inside the agent, skip is a plain `if`), §6 failure mode 3 (wrong person) and guardrails 1, 2, 3.

## Problem
`backend/agents/interviewer.py` is empty. The pipeline cannot produce the `interviewer_profile` briefing section, and nothing guards against profiling the wrong person when a name like "John Smith" matches many people.

## Goal
An `interviewer_research_node(state)` (LangGraph node contract: state dict in, partial state dict out) that searches Tavily for the interviewer at the target company, retries with a reformulated query when fewer than 2 relevant results are found, summarizes into an `InterviewerProfile` grounded only in those results, warns when fewer than 3 results back it, and warns when the results cannot be tied to the named person at that company.

## Non-goals
- No StateGraph wiring or parallel execution with the company node (later slice).
- No LinkedIn scraping or Gmail/Calendar-sourced interviewer data; Tavily only.
- No extra LLM disambiguation call (ADR §6 guardrail 4 covers company; for people we use a deterministic check in code).
- No supervisor, no LLM tool-calling loop: retry is a deterministic loop (ADR §1).
- No `shared_interests` / `conversation_starters` personalization against the resume: that needs RAG output and belongs to synthesis. The node fills `summary` and `background` only.
- No HTTP endpoint, persistence or caching.

## Design
- Reuses `services/web_search.search_web` and `SearchResult`. Reuses `low_result_warning`'s pattern but with interviewer wording.
- `agents/interviewer.py`:
  - **Skip**: if `interviewer` is absent/blank, return an empty `InterviewerProfile` with no network or LLM call and no warning (ADR §1: "a simple `if`"). `company` is still required.
  - **Query ladder** (max 3 attempts): (1) `"{interviewer}" {company}`, (2) `"{interviewer}" {company} {role} linkedin` (role omitted if absent), (3) `"{interviewer}" {company} blog talk interview podcast`.
  - **Relevance filter** (wrong-person guard, deterministic): a result is *relevant* if its title+content contains the interviewer's full name (case-insensitive). Results that do not are dropped before counting. A relevant result is *company-confirmed* if it also mentions the company name.
  - Relevant results accumulate across attempts, de-duplicated by URL. Loop stops once relevant results >= 2 (ADR §1 threshold).
  - **Low-result warning** when relevant results < 3: `"Limited public information available for {interviewer}. The following profile is based on {N} sources and may be incomplete."` (ADR §6 guardrail 2).
  - **Wrong-person warning** when there is at least one relevant result but none is company-confirmed: `"Could not confirm that these sources refer to {interviewer} at {company}. Verify this is the right person before relying on the profile."` (ADR §6 failure mode 3.)
  - **Zero relevant results**: skip the LLM, return empty `InterviewerProfile`, add the low-result warning (N = 0).
  - **Summary**: one Claude call (`with_structured_output(InterviewerProfile)`), prompt requires: use only the numbered results; only include facts about a person who is clearly the named interviewer at the named company; if results look like different people, leave fields empty; no claims without support. `sources` is overwritten in code with the URLs passed to the model (ADR §6 guardrail 1).
- State in: `interviewer`, `company`, optional `role`, optional `warnings`. State out: `interviewer_research` (`InterviewerProfile` as dict), `warnings`.
- Env: `TAVILY_API_KEY`, `ANTHROPIC_API_KEY`; model overridable via `INTERVIEWER_AGENT_MODEL` (default `claude-sonnet-5-5`).

## Acceptance Criteria

### Scenario 1: Enough relevant results first try
- **Given** the first query returns 4 results that mention the interviewer and company
- **When** the node runs
- **Then** Tavily is called once, the LLM once, `sources` equals those URLs, no warnings.

### Scenario 2: Retry when fewer than 2 relevant results
- **Given** the first query yields 1 relevant result and the second yields 2 more
- **When** the node runs
- **Then** the reformulated query is issued, results merge, the LLM sees all 3, no warnings.

### Scenario 3: Retry capped at 3 attempts
- **Given** every query yields 0 or 1 relevant result
- **When** the node runs
- **Then** Tavily is called exactly 3 times.

### Scenario 4: Low-result warning
- **Given** 2 relevant results total
- **When** the node runs
- **Then** the profile is still produced and the interviewer low-result warning (N = 2) is appended. With exactly 3, no such warning.

### Scenario 5: Zero relevant results
- **Given** all attempts return nothing, or only results that never mention the name
- **When** the node runs
- **Then** the LLM is not called, `interviewer_research` is an empty `InterviewerProfile`, the low-result warning (N = 0) is added, and the node does not raise.

### Scenario 6: Irrelevant results are filtered
- **Given** a query returns 5 results, 2 of which do not mention the interviewer's name
- **When** the node runs
- **Then** only the 3 relevant results are passed to the LLM, counted toward thresholds, and listed in `sources`.

### Scenario 7: Wrong-person warning
- **Given** relevant results exist but none mentions the company
- **When** the node runs
- **Then** the wrong-person warning is appended (the profile is still produced). If at least one result mentions the company, it is not.

### Scenario 8: No interviewer provided
- **Given** state has no `interviewer` (missing, `None` or blank)
- **When** the node runs
- **Then** no Tavily or LLM call is made, `interviewer_research` is an empty `InterviewerProfile`, and no warning is added.

### Scenario 9: Missing company
- **Given** an interviewer is given but `company` is missing or blank
- **When** the node runs
- **Then** it raises `ValueError` before any network call.

### Scenario 10: Duplicate URLs across attempts
- **Given** a retry query returns a URL already seen
- **When** results merge
- **Then** each URL appears once and counts once.

### Scenario 11: Sources cannot be fabricated
- **Given** the LLM returns a `sources` list with a URL not among the results
- **When** the node finishes
- **Then** `sources` contains only the URLs passed to the model.

### Scenario 12: Role optional
- **Given** state has no `role`
- **When** query 2 is built
- **Then** it has no stray "None" or double spaces.

### Scenario 13: Upstream failure
- **Given** Tavily or the LLM raises
- **When** the node runs
- **Then** the exception propagates (consistent with the other nodes).

### Scenario 14: Existing warnings preserved
- **Given** state already holds warnings
- **When** the node runs
- **Then** they are kept and new ones appended.

## Affected Files
- `backend/agents/interviewer.py` (implement)
- `backend/tests/test_interviewer_node.py` (new)
- `specs/tasks-interviewer-research.md` (new)
- `CLAUDE.md` (Current State / Next Task)

## Dependencies
- `search_web`, `SearchResult`, `InterviewerProfile` already exist. `TAVILY_API_KEY` and `ANTHROPIC_API_KEY` for real runs (tests mock both).

## Open Questions
- Name matching is a plain case-insensitive full-name substring, so "Jon Smith" vs "Jonathan Smith" or "Smith, John" would be missed. Acceptable for v1 (errs toward a warning, not a wrong profile); revisit with real data.
- Should a missing interviewer add a warning so the briefing UI can say "no interviewer provided"? Spec says no (the user chose not to provide one).
- Company-mention check uses the company string as typed; aliases ("Stripe, Inc.") may under-confirm and trigger the warning spuriously.

# Spec: Company Intelligence Agent

Source of truth: `ARCHITECTURE_DECISIONS.md` §1 (fixed DAG, retry inside the agent), §6 (guardrails 1, 2, 3).

## Problem
`backend/agents/company.py` is empty. The pipeline has no way to turn a company name into the `company_overview` briefing section; web research (Tavily) is not wired up anywhere.

## Goal
A `company_research_node(state)` (LangGraph node contract: state dict in, partial state dict out) that searches Tavily for the target company, retries with a reformulated query when fewer than 2 results come back, summarizes the results into a `CompanyOverview` whose sources are the result URLs, and warns when fewer than 3 results back it.

## Non-goals
- No StateGraph wiring or parallel execution with the interviewer node (later slice).
- No interviewer research, synthesis, or briefing-chunk writer.
- No company disambiguation LLM call (ADR §6 guardrail 4: only if ambiguity proves real).
- No supervisor, no LLM-driven tool-calling loop: retry is a deterministic loop in the node (ADR §1: "a local decision, not a routing decision"). Only the final summarization uses an LLM.
- No HTTP endpoint, no persistence, no caching of search results.

## Design
- `services/web_search.py`: `search_web(query, max_results=5) -> list[SearchResult]` wrapping `tavily-python` (`TavilyClient(api_key=TAVILY_API_KEY)`). `SearchResult` (`title`, `url`, `content`) lives in `models/research.py`. Raises `RuntimeError` if `TAVILY_API_KEY` unset.
- `agents/company.py`:
  - Query ladder (max 3 attempts): (1) `"{company} company overview"`, (2) `"{company} {role} engineering tech stack recent news"` (role omitted if absent), (3) `"{company} about funding products"`.
  - Attempts accumulate results, de-duplicated by URL. Loop stops as soon as accumulated results >= 2 (ADR §1 threshold: retry when <2).
  - If results == 0 after all attempts: skip the LLM, return an empty `CompanyOverview`.
  - Otherwise one Claude call (`langchain-anthropic`, `with_structured_output(CompanyOverview)`) with a system prompt requiring every claim be drawn from the provided results (ADR §6 guardrail 1). `sources` is then overwritten in code with the URLs of the results actually passed in, so the model cannot invent a source.
  - If final result count < 3: append warning `"Limited public information available for {company}. The following profile is based on {N} sources and may be incomplete."` (ADR §6 guardrail 2).
- State in: `company`, optional `role`, optional `warnings`. State out: `company_research` (`CompanyOverview` as dict), `warnings`.
- Env: `TAVILY_API_KEY`, `ANTHROPIC_API_KEY`.

## Acceptance Criteria

### Scenario 1: Enough results on first try
- **Given** Tavily returns 5 results for the first query
- **When** the node runs for "Stripe"
- **Then** Tavily is called once, the LLM is called once, `company_research.sources` equals the 5 URLs, and no warning is added.

### Scenario 2: Retry when fewer than 2 results
- **Given** the first query returns 1 result and the second returns 3 more
- **When** the node runs
- **Then** the second (reformulated) query is issued, results are merged, the LLM sees all 4, and no warning is added.

### Scenario 3: Retry stops at 3 attempts
- **Given** every query returns 0 or 1 result
- **When** the node runs
- **Then** Tavily is called exactly 3 times, never more.

### Scenario 4: Low-result warning
- **Given** the accumulated results total 2 (fewer than 3)
- **When** the node runs
- **Then** the overview is still produced and the warning "Limited public information available for Stripe. The following profile is based on 2 sources and may be incomplete." is appended. With exactly 3 results there is no warning.

### Scenario 5: Zero results
- **Given** all attempts return no results
- **When** the node runs
- **Then** the LLM is not called, `company_research` is an empty `CompanyOverview`, and the low-result warning (N = 0) is added. The node does not raise.

### Scenario 6: Duplicate URLs across attempts
- **Given** the retry query returns a URL already seen
- **When** results are merged
- **Then** each URL appears once and counts once toward the thresholds.

### Scenario 7: Sources cannot be fabricated
- **Given** the LLM returns a `sources` list containing a URL not in the search results
- **When** the node finishes
- **Then** `sources` contains only URLs from the search results.

### Scenario 8: Role is optional
- **Given** state has no `role`
- **When** the retry query is built
- **Then** it contains the company only, with no stray "None" or double spaces.

### Scenario 9: Missing input
- **Given** state with a missing or blank `company`
- **When** the node runs
- **Then** it raises `ValueError` before any network call.

### Scenario 10: Upstream failure
- **Given** Tavily or the LLM raises
- **When** the node runs
- **Then** the exception propagates (consistent with `rag_retrieval_node`; no silent empty result). Missing `TAVILY_API_KEY` raises `RuntimeError`.

### Scenario 11: Existing warnings preserved
- **Given** state already holds warnings
- **When** the node runs
- **Then** they are kept and new ones appended.

## Affected Files
- `backend/models/research.py` (new: `SearchResult`)
- `backend/services/web_search.py` (new)
- `backend/agents/company.py` (implement)
- `backend/tests/test_web_search.py` (new)
- `backend/tests/test_company_node.py` (new)
- `CLAUDE.md` (Current State / Next Task)

## Dependencies
- `tavily-python` and `langchain-anthropic` already in `requirements.txt`.
- `TAVILY_API_KEY` and `ANTHROPIC_API_KEY` must be set for real runs (tests mock both).

## Open Questions
- Should a Tavily outage fail the whole briefing, or degrade to an empty section plus warning? Spec follows the rag node (propagate); revisit when the graph is wired.
- Stale results (ADR §6 failure mode 2): Tavily `published_date` is not used yet; consider a recency hint in the prompt later.
- Model ID is hardcoded as `claude-sonnet-5-5` with an env override (`COMPANY_AGENT_MODEL`); confirm this is acceptable.

# Spec: Synthesis Agent

Source of truth: `ARCHITECTURE_DECISIONS.md` §1 (fixed DAG, synthesis is the last node), §5 (faithfulness is the expected weak spot), §6 failure mode 1 (hallucinated talking points), guardrail 1 (source attribution in the prompt) and guardrail 3 (structured output validation).

## Problem
`backend/agents/synthesis.py` is empty. Company, interviewer and RAG nodes each produce partial state, but nothing assembles them into the 4-section `BriefingSections`, and nothing stops the LLM from inventing connections between the resume and the company that the research does not support.

## Goal
A `synthesis_node(state)` (LangGraph node contract: state dict in, partial state dict out) that builds the final `BriefingSections` from company research, interviewer research and retrieved resume/briefing context, where every generated claim carries a citation that is checked in code against the sources actually available, and unsupported claims are dropped.

## Non-goals
- No StateGraph wiring, background execution, or persisting to the `briefings` table (later slices).
- No briefing chunk writer / embedding of the output (separate task).
- No RAGAS evaluation (separate task).
- No second LLM call for fact-checking, no retries on validation failure, no confidence scores (ADR §6 "What NOT to build").
- No changes to the company or interviewer nodes; their output passes through unchanged.
- No new Pydantic fields on `BriefingSections`; citations are inline in the strings.

## Design
- **Inputs (state in):** `company` (required), optional `role`, `company_research` (`CompanyOverview` dict), `interviewer_research` (`InterviewerProfile` dict), `retrieved_context` (`RetrievalResult` dict), optional `warnings`.
- **Output (state out):** `briefing_content` (`BriefingSections` as dict), `warnings`.
- **What is passthrough vs generated:**
  - `company_overview`: passthrough of `company_research`.
  - `interviewer_profile`: `summary`, `background`, `sources` passthrough; `shared_interests` and `conversation_starters` generated (these were deliberately left empty by the interviewer node).
  - `role_insights`: generated (`key_requirements`, `resume_alignment`, `potential_gaps`); `sources` set in code.
  - `talking_points`: generated (`talking_points`, `suggested_questions`, `stories_to_prepare`).
- **One Claude call** with `with_structured_output(SynthesisOutput)`, where `SynthesisOutput` is a private model holding only the generated fields above. Model overridable via `SYNTHESIS_AGENT_MODEL` (default `claude-sonnet-5-5`), `temperature=0`.
- **Context given to the model:** numbered company facts (summary, news, stack, culture) each tied to the company source URLs; interviewer summary/background with its URLs; resume chunks labeled by section; same-company prior briefing chunks labeled as prior briefings. Only data from state, nothing else.
- **Citation format (ADR §6 guardrail 1):** every generated item ends with one or more tags: `[Source: <url>]` for web facts, `[Resume: <Section>]` for resume references (section = a `section` value of a retrieved resume chunk, e.g. `Experience`). Prompt: every factual claim must cite its source; for resume references cite the specific section; if you cannot cite, do not include the claim; do not connect resume experience to company needs unless both are in the provided context.
- **Validation in code (ADR §6 guardrail 3):** after the call, each generated list item is kept only if it contains at least one citation tag AND every tag it contains is valid: a `[Source: url]` whose url is in the allowed set (company `sources` ∪ interviewer `sources`), or a `[Resume: X]` whose X matches (case-insensitive) a retrieved resume chunk section. Items failing this are dropped. `suggested_questions` are the user's questions to ask, not factual claims, so they are exempt from the citation requirement (but still need to be non-blank strings).
- **Gating the LLM call:**
  - Interviewer enrichment fields are generated only when the interviewer profile has a non-empty `summary` or `background` (no inventing starters about an unknown person); otherwise they are left empty.
  - Resume-based items can only validly cite resume sections that exist; with no resume chunks, items can only cite web sources.
  - If there is no usable context at all (no company facts, no interviewer facts, no resume chunks), skip the LLM, return passthrough sections with empty generated fields, and add a warning.
- **Warnings (appended, existing preserved):**
  - Dropped items: `"Removed N generated items that lacked a valid source citation."` (only when N > 0).
  - Empty talking points after validation: `"No sourced talking points could be generated for this briefing."`
  - No usable context (LLM skipped): `"Not enough research context to generate role insights or talking points."`
- Sources/URLs are never taken from the model: `role_insights.sources` is set in code from the allowed URL set.
- Failures (LLM raises) propagate, consistent with the other nodes.

## Acceptance Criteria

### Scenario 1: Happy path assembly
- **Given** company research, interviewer research, resume chunks, and an LLM output whose items all carry valid citations
- **When** the node runs
- **Then** `briefing_content` is a valid `BriefingSections` with company overview and interviewer summary/background passed through unchanged, generated fields populated, and no new warnings.

### Scenario 2: Source attribution in the prompt
- **Given** the node builds the LLM call
- **When** the call is made
- **Then** the system prompt requires a citation for every factual claim (URL for web facts, resume section for resume references) and forbids uncited claims; the human message contains the company facts with their URLs, interviewer facts, and resume chunks labeled by section.

### Scenario 3: Item with no citation is dropped
- **Given** the LLM returns a talking point with no citation tag
- **When** validation runs
- **Then** that item is absent from the output and the dropped-items warning counts it.

### Scenario 4: Fabricated URL is dropped
- **Given** the LLM cites `[Source: https://evil.example]` which is not in the company/interviewer sources
- **When** validation runs
- **Then** the item is dropped and counted.

### Scenario 5: Invalid resume section is dropped
- **Given** the LLM cites `[Resume: Awards]` but no retrieved resume chunk has section `Awards`
- **When** validation runs
- **Then** the item is dropped and counted. A valid `[Resume: experience]` matches case-insensitively and is kept.

### Scenario 6: Mixed valid and invalid tags
- **Given** one item cites a valid URL and an invalid resume section
- **When** validation runs
- **Then** the item is dropped (every tag must be valid).

### Scenario 7: Suggested questions exempt from citations
- **Given** the LLM returns suggested questions without tags
- **When** validation runs
- **Then** they are kept (blank strings removed).

### Scenario 8: Empty talking points after validation
- **Given** every generated talking point fails validation
- **When** the node finishes
- **Then** `talking_points.talking_points` is empty, the node does not raise, and the "No sourced talking points" warning is added.

### Scenario 9: No interviewer research
- **Given** the interviewer profile is empty (no interviewer given, or no results)
- **When** the node runs
- **Then** `interviewer_profile` stays empty (including `shared_interests` and `conversation_starters`, even if the LLM returned some), with no warning added for that.

### Scenario 10: No resume on file
- **Given** `retrieved_context` has no resume chunks
- **When** the node runs
- **Then** the call still happens using web context, resume-section citations are all invalid (dropped if present), and no extra warning is added (the RAG node already warned).

### Scenario 11: No usable context
- **Given** empty company research, empty interviewer research, and no resume chunks
- **When** the node runs
- **Then** the LLM is not called, generated fields are empty, and the "Not enough research context" warning is added.

### Scenario 12: Sources set in code
- **Given** the LLM returns its own source list for role insights
- **When** the node finishes
- **Then** `role_insights.sources` equals the company and interviewer URLs from state (de-duplicated, order preserved), nothing the model supplied.

### Scenario 13: Missing company
- **Given** `company` is missing or blank
- **When** the node runs
- **Then** it raises `ValueError` before any LLM call.

### Scenario 14: Upstream failure
- **Given** the LLM raises
- **When** the node runs
- **Then** the exception propagates.

### Scenario 15: Existing warnings preserved
- **Given** state already holds warnings (e.g. low-result warnings from research nodes)
- **When** the node runs
- **Then** they are kept, in order, and new ones appended.

### Scenario 16: Missing upstream keys tolerated
- **Given** state lacks `company_research`, `interviewer_research`, or `retrieved_context` keys
- **When** the node runs
- **Then** missing keys are treated as empty models and the node does not crash on them.

## Affected Files
- `backend/agents/synthesis.py` (implement)
- `backend/tests/test_synthesis_node.py` (new)
- `specs/tasks-synthesis-agent.md` (new)
- `CLAUDE.md` (Current State / Next Task)

## Dependencies
- `CompanyOverview`, `InterviewerProfile`, `RoleInsights`, `TalkingPoints`, `BriefingSections` (`models/briefing.py`) and `RetrievalResult` (`models/retrieval.py`) already exist.
- `ANTHROPIC_API_KEY` for real runs (tests mock `ChatAnthropic`).
- No migrations.

## Open Questions
- Dropping uncited items silently shrinks the briefing; the warning only gives a count. Acceptable for v1, revisit if drops are frequent in practice (RAGAS faithfulness will tell).
- Prior-briefing chunks are shown to the model as context but have no citation tag, so items cannot cite them. Intentional (ADR §3 same-company only, and avoids laundering stale claims); confirm.
- Citation tags are inline text, so the frontend will need to parse/render them later.
- Company facts (`recent_news`, `tech_stack`) in `CompanyOverview` carry no per-fact URL, only the shared `sources` list, so "cite the URL" means any URL from that list. Per-fact attribution would need a schema change.

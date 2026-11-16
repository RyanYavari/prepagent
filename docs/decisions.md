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

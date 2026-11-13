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

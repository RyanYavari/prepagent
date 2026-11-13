---
name: why
description: Log an architectural decision with context, tradeoffs, and rejected alternatives
---

# /why

Record an architectural decision in the decision journal.

## Steps

1. Ask for (or read from the prompt):
   - What decision was made
   - What alternatives were considered

2. Explore the relevant code to understand the implementation.

3. Append an entry to `docs/decisions.md`:

```markdown
## [YYYY-MM-DD] [Decision Title]

**Status:** Accepted

**Context:**
[1-3 sentences: what problem prompted this decision]

**Decision:**
[1-2 sentences: what we chose to do]

**Alternatives considered:**
- [Alternative A]: [why rejected — 1 sentence]
- [Alternative B]: [why rejected — 1 sentence]

**Tradeoffs:**
- Pro: [benefit]
- Con: [cost or risk]

**Revisit when:**
[Under what conditions this decision should be reconsidered]
```

4. Keep entries concise. This is interview prep that writes itself.
   An interviewer asking "why did you choose X?" gets answered by this log.

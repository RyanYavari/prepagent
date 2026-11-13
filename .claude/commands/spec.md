---
name: spec
description: Generate a spec from a problem description with Given/When/Then acceptance criteria
---

# /spec

Generate a specification document for a feature or change.

## Steps

1. Ask for (or read from the prompt) the problem description: what exists, what's wrong, what "done" looks like.
2. Explore the relevant codebase files to understand current state.
3. Output a spec using this template:

```markdown
# Spec: [Feature Name]

## Problem
[1-2 sentences: what exists now and what needs to change]

## Goal
[1 sentence: what "done" looks like]

## Non-goals
- [What we are NOT building in this slice]

## Acceptance Criteria

### Given [precondition]
### When [action]
### Then [expected result]

(Repeat for each scenario. Include happy path, error cases, and edge cases.)

## Affected Files
- [List each file that will be created or modified]

## Dependencies
- [Any prerequisite work, API keys, migrations, etc.]

## Open Questions
- [Anything unresolved that needs a decision before building]
```

4. Save to `specs/[feature-name].md`
5. Do NOT start implementing. The spec must be reviewed and approved first.

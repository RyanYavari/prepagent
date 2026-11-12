---
name: review
description: Code review against spec acceptance criteria before merging
---

# /review

Review implementation against its spec's acceptance criteria.

## Steps

1. Read the spec from `specs/[feature-name].md`.
2. Read all files listed in the spec's "Affected Files" section.
3. Check each acceptance criterion (Given/When/Then) against the implementation:
   - Does the code handle the happy path?
   - Does the code handle every error case in the spec?
   - Does the code handle every edge case in the spec?
4. Run `pytest -x -q` in the backend directory to confirm tests pass.
5. Run `ruff check` to confirm no lint violations.
6. Output a review in this format:

```markdown
# Review: [Feature Name]

## Spec compliance
| Criterion | Status | Notes |
|-----------|--------|-------|
| [Given/When/Then summary] | PASS / FAIL / PARTIAL | [details] |

## Issues found
- [ ] [Severity: HIGH/MED/LOW] [description]

## Tests
- Total: X | Passing: X | Failing: X
- Missing coverage: [list any acceptance criteria without a test]

## Verdict
APPROVE / REQUEST CHANGES
```

7. If verdict is REQUEST CHANGES, list the specific changes needed.

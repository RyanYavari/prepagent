---
name: wrap
description: End-of-session wrap summarizing what changed, what's next, and what to tell the harness
---

# /wrap

Generate an end-of-session summary.

## Steps

1. Run `git diff --stat HEAD` to see what changed this session.
2. Run `git log --oneline -10` to see recent commits.
3. Run `pytest -x -q` to confirm current test state.
4. Output a wrap summary:

```markdown
# Session Wrap — [Date]

## What changed
- [List each meaningful change with file paths]

## Commits
- [List commits made this session]

## Test status
- Passing: X | Failing: X | Skipped: X

## What's next
- [ ] [Next task to pick up]
- [ ] [Any blockers or open questions]

## Harness updates needed
- [ ] [Any patterns Claude kept getting wrong — add to CLAUDE.md "What Claude gets wrong"]
- [ ] [Any new protected files — add to hooks/block-protected-files.sh]
- [ ] [Any new lint rules — update hooks/post-edit-lint.sh]
- [ ] [Any new conventions discovered — add to CLAUDE.md]
```

5. If there are harness updates needed, offer to apply them now.

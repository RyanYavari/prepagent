---
name: commit
description: Stage and commit with conventional commit message format
---

# /commit

Create a well-formatted conventional commit.

## Steps

1. Run `git status` and `git diff --staged` to see what's ready.
2. If nothing is staged, identify the logical change set and stage relevant files.
   - Group related changes into a single commit.
   - Never mix unrelated changes in one commit.

3. Determine the commit type from the changes:
   - `feat:` — new feature or capability
   - `fix:` — bug fix
   - `refactor:` — code restructuring, no behavior change
   - `test:` — adding or updating tests
   - `docs:` — documentation changes
   - `chore:` — build, CI, dependency updates

4. Write the commit message:

```
type: short description (imperative mood, <72 chars)

[Optional body: what and why, not how. Wrap at 72 chars.]
```

5. Commit with the message.

6. Run `pytest -x -q` after committing to confirm nothing broke.

## Rules
- Imperative mood: "add feature" not "added feature" or "adds feature"
- No period at the end of the subject line
- Body explains WHY the change was made, not WHAT changed (the diff shows what)
- If the change relates to a spec, reference it: `Spec: specs/[name].md`

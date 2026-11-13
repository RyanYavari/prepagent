---
name: debug
description: Structured debugging with hypothesis-test loops instead of shotgun fixes
---

# /debug

Debug an issue using structured hypothesis testing.

## Steps

1. **Reproduce:** Get the exact error message, stack trace, or incorrect behavior.
   - Run the failing test or request.
   - Copy the full error output.

2. **Hypothesize:** List 2-3 most likely causes, ranked by probability.

```markdown
# Debug: [Brief description]

## Error
[Exact error message or incorrect behavior]

## Hypotheses (ranked)
1. [Most likely cause] — [why I think this]
2. [Second most likely] — [why I think this]
3. [Third most likely] — [why I think this]
```

3. **Test hypothesis 1 first.** Add a diagnostic (print, log, assert, or test) that would confirm or rule out hypothesis 1.

4. **Run the diagnostic.** Read the output.

5. **If confirmed:** Fix the root cause, not the symptom. Run the full test suite after fixing.

6. **If ruled out:** Move to hypothesis 2. Repeat.

7. **After fixing:** Document the root cause:

```markdown
## Root cause
[What was actually wrong — 1-2 sentences]

## Fix
[What changed — file and line]

## Prevention
- [ ] Add regression test? [yes/no — if yes, write it]
- [ ] Update CLAUDE.md "What Claude gets wrong"? [yes/no]
- [ ] Add to spec edge cases? [yes/no]
```

## Rules
- Never apply more than one fix at a time.
- Never guess-and-check without a hypothesis.
- If 3 hypotheses are all ruled out, step back and re-read the error with fresh eyes.
- If stuck after 2 full cycles, flag it and ask for human input.

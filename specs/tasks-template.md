# Tasks: [Feature Name]

Spec: `specs/[feature-name].md`

## Slice plan

Break the spec into the smallest shippable slices. Each slice should be independently testable.

### Slice 1: [Name]
- [ ] [Concrete implementation step]
- [ ] [Write test for acceptance criterion X]
- [ ] [Run /review]

### Slice 2: [Name]
- [ ] [Concrete implementation step]
- [ ] [Write test for acceptance criterion Y]
- [ ] [Run /review]

### Slice 3: [Name]
- [ ] [Concrete implementation step]
- [ ] [Write test for acceptance criterion Z]
- [ ] [Run /review]

## Done checklist
- [ ] All acceptance criteria have passing tests
- [ ] `pytest -x -q` passes
- [ ] `ruff check` clean
- [ ] /review returns APPROVE
- [ ] Reviewer agent returns APPROVE
- [ ] /commit with conventional commit message
- [ ] /why entry if any architectural decisions were made

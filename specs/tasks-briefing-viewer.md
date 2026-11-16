# Tasks: Briefing Viewer Page

Spec: `specs/briefing-viewer.md`

## Slice plan

Break the spec into the smallest shippable slices. Each slice should be independently testable.

### Slice 1: Test runner + citation parser
- [x] Add `vitest` devDependency, `test` script (`vitest run`), and CI step `npm test`
- [x] Write failing tests in `frontend/lib/citations.test.ts` (single/multiple tags, whitespace, mixed order, non-http URL stays text, no tags, empty, unclosed tag)
- [x] Implement `frontend/lib/citations.ts` (`parseCitations`, `hostnameOf`)
- [x] Run `npm test`, `npm run lint`, `npx tsc --noEmit`
- [x] Run /review

### Slice 2: Briefing types and section components
- [x] Add `frontend/lib/briefing.ts` types mirroring `backend/models/briefing.py`
- [x] Add `CitedText` (source link w/ hostname + noopener, resume chip, "no source" marker option)
- [x] Add `BriefingSections` (4 sections, sources list, empty handling, prominent warnings box)
- [x] Run `npm test`, `npm run lint`, `npx tsc --noEmit`
- [x] Run /review

### Slice 3: Viewer page with polling
- [x] Read Next docs for dynamic routes / `useParams` (frontend/AGENTS.md)
- [x] Create `frontend/app/prep/[id]/page.tsx`: auth guard (effect-only localStorage), 401 -> `/`, 404 state
- [x] Poll every 3s while pending/running; stop on complete/failed/unmount; 5-min cap with "Check again"; stop after 3 consecutive errors
- [x] Render pending/running, failed, complete (null content) and complete states
- [x] Run `npm test`, `npm run lint`, `npx tsc --noEmit`, `npm run build`
- [x] Run /review

### Slice 4: Navigation wiring
- [x] Dashboard cards link to `/prep/{id}`
- [x] `/prep/new` redirects to `/prep/{id}` after successful POST
- [ ] Manual test: create briefing, watch status poll to complete, sections + citation chips + warnings render
- [ ] Manual test: failed briefing, 404 id, signed-out access
- [x] Run `npm test`, `npm run lint`, `npx tsc --noEmit`, `npm run build`
- [x] Run /review

## Done checklist
- [ ] All acceptance criteria have passing tests or documented manual checks (parser + rendering tested; polling/auth/404/navigation NOT yet run in a browser)
- [x] `npm test` passes (and backend `pytest -x -q` still passes)
- [x] `npm run lint` clean, `npx tsc --noEmit` clean, `npm run build` succeeds
- [x] /review returns APPROVE
- [ ] Reviewer agent returns APPROVE
- [ ] /commit with conventional commit message (one commit for the whole spec)
- [ ] /why entry if any architectural decisions were made

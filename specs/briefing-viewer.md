# Spec: Briefing Viewer Page

## Problem
POST /briefings runs the LangGraph pipeline in the background and GET /briefings/{id} returns status plus the 4-section `content` (with `content.warnings`), but no page displays it: the dashboard lists briefings without linking anywhere, and /prep/new redirects back to /dashboard. Synthesis output carries inline `[Source: <url>]` and `[Resume: <Section>]` citation tags (ADR §6 guardrails 1 and 3) that would render as raw text.

## Goal
A user opens `/prep/{id}`, sees live status while the pipeline runs, then reads the 4 sections with citation tags rendered as clickable source links and resume chips and pipeline warnings shown prominently above the content.

## Non-goals
- No backend changes (GET /briefings/{id} already returns everything needed).
- No persisting a failure reason (the page shows a generic failed message; CLAUDE.md lists this as a known gap).
- No retry / regenerate button, no editing, no export or sharing.
- No server push (SSE/websockets): plain polling.
- No briefing chunk writer, no RAGAS, no confidence scores (ADR §6: "source attribution is more actionable").
- No streaming of partial sections: content appears when status is `complete`.

## Design notes (from ARCHITECTURE_DECISIONS.md)
- §6 guardrail 1: citations exist so hallucinations are *detectable*; the viewer must make citations visible and make uncited generated claims a visible red flag.
- §6 guardrail 2: low-result warnings must set user expectations, so warnings render prominently (above all sections), not in a footer.
- §1 / §3: the 4 sections are company overview, interviewer profile, role insights, talking points. Section order in the UI follows `BriefingSections`.
- Tag grammar is defined by `_SOURCE_TAG` / `_RESUME_TAG` in `backend/agents/synthesis.py`: `[Source: <url>]`, `[Resume: <Section>]`, whitespace after the colon allowed.

## Acceptance Criteria

### Tag parsing (pure function `parseCitations(text)`)
#### Given a string containing text and one `[Source: https://example.com/a]` tag
#### When it is parsed
#### Then it returns ordered segments: text segments and a `source` segment with `url`, and the tag text is removed from the visible text.

#### Given a string with `[Resume: Experience]` (and `[Resume:  Skills ]` with extra spaces)
#### When it is parsed
#### Then each yields a `resume` segment with the trimmed section name.

#### Given several tags (mixed Source and Resume) in one string
#### When it is parsed
#### Then all are returned in original order with surrounding text preserved.

#### Given a `[Source: ...]` whose value is not an http(s) URL (e.g. `javascript:alert(1)` or plain words)
#### When it is parsed
#### Then it is NOT turned into a link; it is kept as plain text.

#### Given text with no tags, an empty string, or an unclosed `[Source: https://x`
#### When it is parsed
#### Then it returns a single text segment (or none for empty) and never throws.

### Rendering citations
#### Given an item containing `[Source: url]`
#### When rendered
#### Then a link opens the URL in a new tab with `rel="noopener noreferrer"`, labelled with the hostname (e.g. `example.com`), with the full URL as title.

#### Given an item containing `[Resume: Section]`
#### When rendered
#### Then a non-link chip with the section name is shown.

#### Given a synthesis-generated list item (role insights lists, talking points lists, interviewer shared interests / conversation starters) with no tag
#### When rendered
#### Then it shows a subtle "no source" marker (ADR §6 red flag).
(Pass-through summaries and `sources` arrays are not marked; `sources` URLs render as a "Sources" link list per section.)

### Polling
#### Given a briefing with status `pending` or `running`
#### When the page is open
#### Then it shows the company/role/interviewer header, a progress/status indicator, and re-fetches GET /briefings/{id} every 3 seconds with the JWT.

#### Given polling and the status becomes `complete`
#### When the response arrives
#### Then polling stops and the 4 sections render.

#### Given status becomes `failed`
#### When the response arrives
#### Then polling stops and a failure message is shown (no reason available), with a link back to the dashboard.

#### Given the user navigates away
#### When the component unmounts
#### Then the interval/timeout is cleared and no further requests are made.

#### Given status stays `pending`/`running` for more than 5 minutes (e.g. a crash left the row `running`)
#### When the limit is reached
#### Then polling stops and the page says the briefing is taking longer than expected, with a manual "Check again" button.

#### Given a transient network error or 5xx during polling
#### When the poll fails
#### Then the last known state stays visible, a small error notice shows, and polling continues (stops only after 3 consecutive failures, offering "Check again").

### Warnings
#### Given `content.warnings` is non-empty
#### When status is `complete`
#### Then a prominent amber alert box appears above all sections listing every warning, with a count.

#### Given `content.warnings` is empty or content has none
#### When rendered
#### Then no warning box is shown.

### Sections
#### Given a complete briefing
#### When rendered
#### Then sections appear in order: Company Overview (summary, recent news, tech stack, culture notes, sources), Interviewer Profile (summary, background, shared interests, conversation starters, sources), Role Insights (key requirements, resume alignment, potential gaps, sources), Talking Points (talking points, suggested questions, stories to prepare).

#### Given a section or list is empty
#### When rendered
#### Then empty lists are omitted; a fully empty section shows a muted "No information available." line (the interviewer section shows "No interviewer provided." when the briefing has no interviewer).

#### Given `status` is `complete` but `content` is null
#### When rendered
#### Then a "No content was generated" message is shown (no crash).

### Auth and errors
#### Given no token in localStorage
#### When the page loads
#### Then it redirects to `/`.

#### Given the API returns 401
#### When fetching
#### Then token and email are cleared and the user is redirected to `/`.

#### Given the API returns 404
#### When fetching
#### Then a "Briefing not found" message with a link to the dashboard is shown and polling stops.

#### Given first render (hydration)
#### When the page renders on server and client
#### Then localStorage is read only inside effects (same loading shell on both; no hydration mismatch, per the dashboard fix).

### Navigation
#### Given the dashboard briefing list
#### When a briefing card is clicked
#### Then the user goes to `/prep/{id}`.

#### Given a successful POST /briefings from /prep/new
#### When the form submits
#### Then the user is redirected to `/prep/{id}` (instead of /dashboard) so they watch progress.

## Affected Files
- `frontend/lib/citations.ts` (new): `parseCitations`, `hostnameOf`
- `frontend/lib/citations.test.ts` (new)
- `frontend/lib/briefing.ts` (new): types mirroring `models/briefing.py`, polling constants
- `frontend/components/CitedText.tsx` (new): renders segments as text, source links, resume chips
- `frontend/components/BriefingSections.tsx` (new): the 4 sections, warnings box
- `frontend/app/prep/[id]/page.tsx` (new): auth guard, fetch + polling, states
- `frontend/app/dashboard/page.tsx`: cards link to `/prep/{id}`
- `frontend/app/prep/new/page.tsx`: redirect to `/prep/{id}` on success
- `frontend/package.json`, `package-lock.json`: add `vitest` (devDependency) and a `test` script
- `.github/workflows/ci.yml`: add `npm test` step to the frontend job
- `CLAUDE.md`: update current state / next task (in wrap step)

## Dependencies
- Backend GET /briefings/{id} (done) and a running pipeline for manual checks.
- `vitest` as a new devDependency: the frontend has no test runner, and the parser is the logic worth testing. Component and polling behaviour is verified by manual testing plus `npm run lint`, `npx tsc --noEmit` and `npm run build`.
- Per frontend/AGENTS.md, read the Next.js docs in `node_modules/next/dist/docs/` before writing route code (`useParams` for the `[id]` segment in a client component).

## Open Questions
- Adding vitest is assumed acceptable (alternative: leave the parser untested). Assumed yes.
- Should an untagged generated item be flagged "no source"? Assumed yes per ADR §6 guardrail 1; synthesis already drops untagged items in code, so this should rarely show.
- Poll interval 3s, give-up at 5 min (pipeline target is under 90s): assumed fine.

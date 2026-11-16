# Tasks: Optional Job Description Input

Spec: `specs/job-description-input.md` (Revision 2)

Status: spec approved (defaults for the open questions). Slices 1-4, 6 and 7 built with tests; slice 5 built and covered by vitest, lint and build, but NOT exercised in a browser. The spike (synthesis JD block, `[JD]` validation, `--jd`, `golden_v2.json`) was the base. ONE commit for the whole spec (spec and tasks docs included) after `pytest -x -q` passes and /review is APPROVE, made with the commit skill, no Co-Authored-By. Do not merge to dev.

## Slice plan

### Slice 1: Request model and validation
- [x] Write failing tests: valid JD accepted; absent/null/whitespace -> None; 12,001 chars -> 422 without echoing the JD; URLs/`<>{}`/non-ASCII accepted; control, zero-width and bidi chars stripped, newlines/tabs kept
- [x] `clean_long_text` in `models/text_safety.py`
- [x] `BriefingCreate.job_description` (`max_length=12_000`) with validator
- [x] `RequestValidationError` handler in `main.py` dropping `input` for `job_description` errors only; other 422s unchanged
- [x] Run /review (one independent reviewer-agent pass over the whole diff: CHANGES REQUESTED on the 422 body echo, fixed and re-verified, then APPROVE)

### Slice 2: Plumbing (no persistence) and log hygiene
- [x] Write failing tests: POST passes `job_description` to the patched `routers.research.run_pipeline`; insert row has no JD; absent -> `None`; calendar path passes `None` and cannot set it
- [x] `create_pending_briefing` -> `start_pipeline(job_description=...)`; update existing tests that assert exact kwargs
- [x] `run_pipeline(job_description=...)` into graph state (`PipelineState.job_description` exists from the spike)
- [x] Log-hygiene test: unique marker in JD never appears in logs, `failure_reason` or graph metadata across success, node error and timeout
- [x] Run /review (one independent reviewer-agent pass over the whole diff: CHANGES REQUESTED on the 422 body echo, fixed and re-verified, then APPROVE)

### Slice 3: Synthesis prompt and code-side validation (base: spike)
- [x] Spike tests already cover: JD untrusted block with `<` escaped, JD sentence swap, no-JD prompt unchanged, `[JD]` validity, `key_requirements` must carry `[JD]`, JD alone is context, blank JD ignored
- [x] Add tests: injection text ("ignore previous instructions", `</untrusted_data>`) stays inside one block and an item repeating it without a tag is dropped; `UNTRUSTED_RULE` and the no-JD prompt hash are unchanged; kept items with `[JD]`/`[Resume:]`/`[Source:]` together
- [x] Remove "experimental, eval-only" wording from comments and docstrings in `synthesis.py`, `state.py`
- [x] Run /review (one independent reviewer-agent pass over the whole diff: CHANGES REQUESTED on the 422 body echo, fixed and re-verified, then APPROVE)

### Slice 4: Chunk writer guard
- [x] Test: no stored chunk contains the raw JD marker; `write_briefing_chunks` signature unchanged
- [x] Run /review (one independent reviewer-agent pass over the whole diff: CHANGES REQUESTED on the 422 body echo, fixed and re-verified, then APPROVE)

### Slice 5: Frontend
- [x] Failing vitest for `parseCitations`: `[JD]` -> job-description segment; existing cases unchanged; a Key requirements list with a `[JD]` item shows the indicator, without one it does not
- [x] `[JD]` chip and "From job description" heading indicator in `BriefingSections.tsx`
- [x] Textarea + counter + optional label on `/prep/new`; payload omits the key when empty; over 12,000 blocks submit
- [x] `npm run lint`, `npm test`, `npm run build`
- [ ] Manual browser check (backend + frontend running): submit with and without a JD, view the briefing, over-limit message. Tick only if actually done; otherwise state it is unverified
- [x] Run /review (one independent reviewer-agent pass over the whole diff: CHANGES REQUESTED on the 422 body echo, fixed and re-verified, then APPROVE)

### Slice 6: Evals (mocked tests only, no live runs)
- [x] Spike tests already cover: `golden_v2.json` has JDs on exactly 3 cases and v1 has none, contact-detail rejection, `--jd off` strips the JD and records `jd_mode`, JD context in synthesis samples, `[JD]` stripping
- [x] Add tests: briefing cache file name differs with and without a JD and the two modes do not overwrite each other; `golden_v1.json` hash unchanged; company/interviewer samples never include the JD
- [x] Cache file name suffix `-jd` in `briefing_cache.py`
- [x] Write the reproduce procedure (spec, Evals) into the eval docs
- [x] Run /review (one independent reviewer-agent pass over the whole diff: CHANGES REQUESTED on the 422 body echo, fixed and re-verified, then APPROVE)

### Slice 7: Docs
- [x] Update `CLAUDE.md` current state and gotchas (JD request-scoped, never logged, never embedded, `--jd`, golden_v2, spike numbers with their caveats)
- [x] /why entry (no JD storage; bare `[JD]` tag; `UNTRUSTED_RULE` left unchanged; calendar out of scope)

## Done checklist
- [x] All acceptance criteria have passing tests
- [x] `pytest -x -q` passes
- [x] `ruff check` clean (changed files only)
- [x] mypy clean (`--cache-dir=/dev/null --no-sqlite-cache`)
- [x] /review returns APPROVE
- [x] Reviewer agent returns APPROVE
- [ ] Frontend verified in a real browser, or explicitly marked unverified
- [ ] Live smoke call for synthesis with a JD (`RUN_LIVE_LLM_TESTS=1`), run by the user
- [x] /commit with conventional commit message (one commit, no Co-Authored-By)
- [x] /why entry if any architectural decisions were made

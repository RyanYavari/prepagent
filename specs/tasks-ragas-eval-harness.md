# Tasks: RAGAS Evaluation Harness

Spec: `specs/ragas-eval-harness.md` (approved with decisions recorded there).

## Slice plan

### Slice 1: Dataset + loader
- [x] Write failing tests: valid load, stable sha, rejects email/phone/URL in resume, duplicate id, missing company (error names id, never echoes resume)
- [x] Implement `evals/dataset.py` (pydantic models, `load_dataset`)
- [x] Author `evals/golden_v1.json`: 9 synthetic cases + hand-written `reference` lists (needs user review of references)
- [x] Run /review

### Slice 2: Case collection
- [x] Write failing tests (mocked graph nodes): in-memory retrieval returns chunked resume + seeded prior chunks; web results captured per node; LLM-call counter increments; no Supabase client constructed
- [x] Implement `evals/collect.py` (`build_graph().invoke`, retrieval + `search_web` seams, capture, optional web cache if approved)
- [x] Run /review

### Slice 3: Samples + scoring
- [x] Spike: confirm RAGAS 0.4.3 metric classes and LLM/embeddings wrapper API in the venv; note findings in the spec
- [x] Write failing tests (mocked scorer): question template, tag stripping, per-metric answer/context mapping, prior chunks excluded + diagnostic, null for skipped metrics, scorer error -> null with class only
- [x] Implement `evals/samples.py` and `evals/score.py` (counting judge wrapper, `BudgetExceeded`, aggregation, thresholds)
- [x] Run /review

### Slice 4: Report + CLI
- [x] Write failing tests: results JSON shape/meta (git sha, prompt hashes, call counts), terminal table, `--cases`/`--ids`/`--dry-run`, preflight abort, truncated results on cap, refuses under `CI`/pytest, no secrets in output
- [x] Implement `evals/report.py` and `evals/run.py`; add `.gitignore` entries
- [x] Run /review

### Slice 5: Compare
- [x] Write failing tests: deltas for shared cases, differing-meta notice, dataset-version mismatch warning, noise note
- [x] Implement `evals/compare.py` (+ `--repeat` if approved)
- [x] Run /review

### Slice 6 (optional): LangSmith feedback
- [x] Write failing tests: no client import when env unset; feedback failure does not fail the run
- [x] Implement feedback posting
- [x] Run /review

### Slice 7: Real smoke run + docs
- [x] Real run with `--cases 1`, then `--cases 3`, with real keys; calibrate the judge-call estimate and the default cap
- [ ] Save first baseline to `evals/baselines/golden_v1.json` (scores only): NOT done; a 2-case smoke run is not a baseline, run `--all` first
- [x] Update CLAUDE.md (Current State, Commands) and `docs/decisions.md` via /why

## Done checklist
- [x] All acceptance criteria have passing tests
- [x] `pytest -x -q` passes (no eval ever runs in it)
- [x] `ruff check` / `ruff format` on changed files only; mypy clean
- [x] One real harness run completed (mocked tests alone don't count)
- [x] /review returns APPROVE (inline per slice; final check below)
- [ ] /commit with conventional commit message (no Co-Authored-By)
- [x] /why entry for the prior-briefing and judge-model decisions

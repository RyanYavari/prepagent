#!/bin/bash
# Stop hook: runs the fast backend test suite before the agent finishes its turn.
# If tests fail, output goes back to the agent so it can self-correct.
#
# Uses the project venv's interpreter directly (pytest is not on PATH outside
# the venv, which made this hook exit 127). Exits 0 quietly if the venv is
# missing. Only the quick unit suite runs: no live LLM tests, no mypy/build.

ROOT="${CLAUDE_PROJECT_DIR:-$(git rev-parse --show-toplevel 2>/dev/null)}"
[ -n "$ROOT" ] || exit 0

PYTHON="$ROOT/backend/venv/bin/python"
[ -x "$PYTHON" ] || exit 0

cd "$ROOT/backend" || exit 0

# Live LLM smoke tests are slow and cost money; never run them from a hook.
unset RUN_LIVE_LLM_TESTS

# Exit code passes through: non-zero means tests failed, agent sees the output.
"$PYTHON" -m pytest -x -q 2>&1

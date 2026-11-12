#!/bin/bash
# Stop hook: runs test suite before the agent finishes its turn.
# If tests fail, output goes back to the agent so it can self-correct.

cd "$(git rev-parse --show-toplevel)/backend" 2>/dev/null || exit 0

# Run pytest quietly. If it fails, the output feeds back to Claude.
pytest -x -q 2>&1

# Exit code passes through: non-zero means tests failed, agent sees the output.

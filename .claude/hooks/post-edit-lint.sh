#!/bin/bash
# PostToolUse hook: runs after Write/Edit on Python files
# Fires ruff to auto-format and lint. Agent writes good code; this handles the last 10%.

FILE="$CLAUDE_FILE_PATH"

# Only run on Python files
if [[ "$FILE" == *.py ]]; then
    cd "$(git rev-parse --show-toplevel)/backend" 2>/dev/null || exit 0
    ruff check "$FILE" --fix --quiet 2>/dev/null
    ruff format "$FILE" --quiet 2>/dev/null
fi

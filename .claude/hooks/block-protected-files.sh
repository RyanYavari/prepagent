#!/bin/bash
# PreToolUse hook: blocks edits to protected files.
# Exit code 2 = block the action (the ONLY hard guarantee in Claude Code).

FILE="$CLAUDE_FILE_PATH"

PROTECTED_FILES=(
    ".env"
    ".env.local"
    "backend/.env"
    "frontend/.env.local"
    "docker-compose.yml"
    ".github/workflows/ci.yml"
)

for protected in "${PROTECTED_FILES[@]}"; do
    if [[ "$FILE" == *"$protected" ]]; then
        echo "BLOCKED: $FILE is a protected file. Edit manually or unlock explicitly."
        exit 2
    fi
done

exit 0

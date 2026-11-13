#!/bin/bash
# PreToolUse hook: blocks edits to protected files.
# Claude Code passes the tool input as JSON on stdin; the target path is
# .tool_input.file_path. Exit code 2 = block the action.

if ! command -v jq >/dev/null 2>&1; then
    echo "BLOCKED: jq is required by block-protected-files.sh but was not found."
    exit 2
fi

FILE=$(jq -r '.tool_input.file_path // empty')

# Not a file edit (or no path given): nothing to protect.
[[ -z "$FILE" ]] && exit 0

BASE=$(basename "$FILE")

block() {
    echo "BLOCKED: $FILE is a protected file ($1). Edit manually or unlock explicitly." >&2
    exit 2
}

# Environment files: .env, .env.local, .env.test, backend/.env, ... (templates are fine)
case "$BASE" in
    .env.example|.env.sample|.env.template) ;;
    .env|.env.*) block "environment file" ;;
esac

# Infrastructure and CI config
[[ "$BASE" == "docker-compose.yml" || "$BASE" == "docker-compose.yaml" ]] && block "docker compose"
case "$FILE" in
    */.github/workflows/*|.github/workflows/*) block "CI config" ;;
esac

exit 0

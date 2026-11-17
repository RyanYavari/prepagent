#!/usr/bin/env bash
# Render the API's environment file from AWS SSM Parameter Store.
#
#   deploy/render-env.sh [ssm-path-prefix] [output-file]
#
# Defaults: /prepagent/prod/  ->  /etc/prepagent/backend.env (mode 0600, owner root),
# region us-east-2 (Ohio).
# Each parameter /prepagent/prod/NAME becomes a NAME=value line. Needs the AWS CLI and
# jq, and an instance role allowed to read that prefix. Values are never printed: only
# the count and the names of any problem parameters.
set -euo pipefail

PREFIX="${1:-/prepagent/prod/}"
OUT="${2:-/etc/prepagent/backend.env}"
# The SSM parameters live in one region. Set explicitly: the CLI on EC2 does not
# necessarily infer it. Override with AWS_REGION for another region.
REGION="${AWS_REGION:-us-east-2}"

umask 077
TMP="$(mktemp "${OUT}.XXXXXX")"
trap 'rm -f "$TMP"' EXIT

# Fetch and render in one pipeline so values live only in the pipe and the 0600 file.
aws ssm get-parameters-by-path --region "$REGION" \
  --path "$PREFIX" --recursive --with-decryption \
  --query 'Parameters[].{n:Name,v:Value}' --output json |
  jq -r '.[] | (.n | split("/") | last) as $k | "\($k)=\(.v)"' >"$TMP"

# Values with a newline would corrupt an env file (and could smuggle extra variables).
# Check the number of lines against the number of parameters; print names only.
# The CLI paginates (10 parameters per page) and applies --query to every page, so this
# prints one number per page ("10" then "2" for 12 parameters): add them up.
EXPECTED="$(aws ssm get-parameters-by-path --region "$REGION" --path "$PREFIX" --recursive \
  --query 'length(Parameters)' --output text | awk '{ n += $1 } END { print n + 0 }')"
ACTUAL="$(wc -l <"$TMP" | tr -d ' ')"
if [ "$EXPECTED" != "$ACTUAL" ] || [ "$ACTUAL" -eq 0 ]; then
  echo "render-env: expected $EXPECTED parameter(s) under $PREFIX but rendered $ACTUAL line(s)." >&2
  echo "A value probably contains a newline, or the prefix is empty. Nothing was installed." >&2
  exit 1
fi

# docker compose's env_file interpolates `$`, treats ` #` as a comment and strips quotes,
# so such a value would be silently altered. Print the names only.
BAD="$(grep -nE '^[^=]*=.*[$"'"'"'#`\\]' "$TMP" | cut -d: -f2 | cut -d= -f1 || true)"
if [ -n "$BAD" ]; then
  echo "render-env: these parameters contain one of \$ \" ' # backtick or backslash, which an env file would corrupt:" >&2
  echo "$BAD" >&2
  echo "Regenerate those values without such characters. Nothing was installed." >&2
  exit 1
fi

chmod 0600 "$TMP"
mv "$TMP" "$OUT"
trap - EXIT
echo "render-env: wrote $ACTUAL variable(s) to $OUT"

#!/usr/bin/env bash
# Deploy the API on the EC2 instance. Run from anywhere inside the cloned repo:
#
#   deploy/deploy.sh            # pull main, build, refresh secrets, restart, smoke check
#   deploy/deploy.sh --yes      # skip the "no briefings running?" confirmation
#
# Needs: docker + compose plugin, git, curl, the AWS CLI + jq (render-env.sh), and
# /etc/prepagent/deploy.conf containing DOMAIN=<your-domain>.
# If the new container does not become healthy it restarts the previous image tag.
set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
# Config directory; only the tests override it.
ETC_DIR="${PREPAGENT_ETC:-/etc/prepagent}"
COMPOSE=(docker compose -f "$REPO/deploy/docker-compose.prod.yml" --env-file "$ETC_DIR/deploy.conf")
STATE="$ETC_DIR/current_tag"
KEEP_IMAGES=3

ASSUME_YES=0
[ "${1:-}" = "--yes" ] && ASSUME_YES=1

[ -f "$ETC_DIR/deploy.conf" ] || { echo "missing $ETC_DIR/deploy.conf (DOMAIN=...)" >&2; exit 1; }
# shellcheck disable=SC1091
DOMAIN="$(. "$ETC_DIR/deploy.conf" && echo "$DOMAIN")"
[ -n "$DOMAIN" ] || { echo "DOMAIN is empty in $ETC_DIR/deploy.conf" >&2; exit 1; }

cd "$REPO"
git fetch origin main
git checkout main
git merge --ff-only origin/main
TAG="$(git rev-parse --short=12 HEAD)"
PREV="$(cat "$STATE" 2>/dev/null || true)"
# The compose file requires IMAGE_TAG and compose interpolates it for every subcommand
# (`ps` included), so export it once for all calls below. The rollback `up` overrides it
# with the previous tag.
export IMAGE_TAG="$TAG"
echo "deploy: new tag $TAG (previous: ${PREV:-none})"

if [ "$ASSUME_YES" -ne 1 ]; then
  echo "A restart kills running background pipelines. In Supabase run:"
  echo "  select count(*) from briefings where status in ('pending','running');"
  read -r -p "Zero (or acceptable)? Continue [y/N] " reply
  [ "$reply" = "y" ] || { echo "aborted"; exit 1; }
fi

docker build -t "prepagent-api:$TAG" "$REPO/backend"
"$REPO/deploy/render-env.sh"

healthy() {
  local cid status i
  for i in $(seq 1 40); do
    cid="$("${COMPOSE[@]}" ps -q api 2>/dev/null || true)"
    if [ -n "$cid" ]; then
      status="$(docker inspect --format '{{.State.Health.Status}}' "$cid" 2>/dev/null || true)"
      [ "$status" = "healthy" ] && return 0
    fi
    sleep 3
  done
  return 1
}

smoke() {
  curl -fsS --max-time 15 "https://api.$DOMAIN/health" >/dev/null &&
    [ "$(curl -s -o /dev/null -w '%{http_code}' --max-time 15 "https://api.$DOMAIN/docs")" = "404" ]
}

# `up -d` itself exits non-zero when the api never becomes healthy (caddy waits on it),
# so it must be inside the condition or `set -e` would skip the rollback below.
if IMAGE_TAG="$TAG" "${COMPOSE[@]}" up -d && healthy && smoke; then
  echo "$TAG" >"$STATE"
  echo "deploy: $TAG is healthy"
else
  echo "deploy: $TAG failed its health/smoke check" >&2
  if [ -n "$PREV" ]; then
    echo "deploy: restarting previous tag $PREV" >&2
    IMAGE_TAG="$PREV" "${COMPOSE[@]}" up -d || true
  fi
  exit 1
fi

# Keep the newest few images for rollback; remove older prepagent-api tags.
docker images prepagent-api --format '{{.Tag}}' | tail -n +$((KEEP_IMAGES + 1)) |
  while read -r old; do docker rmi "prepagent-api:$old" >/dev/null 2>&1 || true; done

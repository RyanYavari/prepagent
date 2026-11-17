#!/usr/bin/env bash
# Roll the API back to an image tag that is still on this machine.
#
#   deploy/rollback.sh <tag>      # list tags with: docker images prepagent-api
#
# Migrations in this project are additive, so older code runs against the newer schema;
# there are no down-migrations. Frontend rollback is Vercel's "Instant Rollback".
set -euo pipefail

TAG="${1:?usage: rollback.sh <image-tag>  (see: docker images prepagent-api)}"
REPO="$(cd "$(dirname "$0")/.." && pwd)"
docker image inspect "prepagent-api:$TAG" >/dev/null 2>&1 ||
  { echo "no local image prepagent-api:$TAG" >&2; exit 1; }

IMAGE_TAG="$TAG" docker compose -f "$REPO/deploy/docker-compose.prod.yml" \
  --env-file /etc/prepagent/deploy.conf up -d
echo "$TAG" >/etc/prepagent/current_tag
echo "rollback: now running $TAG; check https://api.<domain>/health"

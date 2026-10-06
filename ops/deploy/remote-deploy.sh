#!/usr/bin/env bash
# Runs ON the production host, piped in over ssh by
# .github/workflows/deploy-production.yml. It is deliberately a file rather than
# a heredoc inside the workflow: it is the part that can break production, so it
# should be readable, reviewable and runnable by hand.
#
# The caller prepends the variables below and pipes this script into
# `bash -euo pipefail -s`, so nothing sensitive ever appears in the remote
# process list:
#
#   TAG         git tag to check out; also the image tag to pull
#   PROD_SIZE   small | medium | large (replica counts, see the Makefile)
#   GHCR_USER   GitHub actor for `docker login ghcr.io`
#   GHCR_TOKEN  the workflow's own GITHUB_TOKEN -- valid for that run only
#   PULL_ONLY   true -> pull the tag's images and exit, touching nothing else
#
# Manual run (rollback without GitHub):
#   TAG=v1.2.3 PROD_SIZE=medium bash ops/deploy/remote-deploy.sh
# GHCR_TOKEN may be omitted once the packages are public.

set -euo pipefail

: "${TAG:?TAG is required}"
PROD_SIZE="${PROD_SIZE:-medium}"
REPO_DIR="${REPO_DIR:-/root/overwatch-tournaments}"
COMPOSE_FILE="docker-compose.production.yml"

cd "$REPO_DIR"

# The tag decides the code AND the images. Checking it out keeps the compose
# file, the Makefile and the migrations in step with what CI built; a dirty tree
# fails here on purpose instead of being forced over -- host-specific knobs
# (ANALYTICS_WORKER_CPUS, ports, secrets) belong in .env, which is untracked.
git fetch --tags --prune --force origin

if [ -n "${GHCR_TOKEN:-}" ]; then
    echo "${GHCR_TOKEN}" | docker login ghcr.io -u "${GHCR_USER:-x}" --password-stdin
    trap 'docker logout ghcr.io >/dev/null 2>&1 || true' EXIT
fi

export IMAGE_TAG="${TAG}"

# PULL_ONLY=true (DEPLOY_FREEZE in the workflow): download this release's images
# and stop. The running stack, the checkout and nginx.conf stay as they are; the
# compose file is read from the tag itself, so a service the release adds gets
# fetched too. The later real deploy of the same tag finds every image on disk
# and is down to migrations plus `prod-up`.
if [ "${PULL_ONLY:-false}" = "true" ]; then
    PREFETCH_FILE="$(mktemp -p "$REPO_DIR" .prefetch.XXXXXX.yml)"
    trap 'rm -f "$PREFETCH_FILE"; docker logout ghcr.io >/dev/null 2>&1 || true' EXIT
    git show "refs/tags/${TAG}:${COMPOSE_FILE}" > "$PREFETCH_FILE"
    docker compose -f "$PREFETCH_FILE" pull --quiet --policy missing
    echo "pulled ${TAG}; running stack left untouched"
    exit 0
fi

git checkout --detach "refs/tags/${TAG}"

# `--policy missing`, not a plain pull: the stack also names redis, rabbitmq,
# nginx and xray, and Docker Hub is not reachable from this host (which is why
# the xray proxy exists at all) -- a plain pull fails the whole deploy on
# `teddysun/xray:latest` even though the image has been on disk for months.
# Release tags are immutable, so "already present" can only mean "already the
# right image"; the ones this release actually changed are absent and do get
# pulled, and a GHCR failure still stops the deploy at `up`.
docker compose -f "${COMPOSE_FILE}" pull --quiet --policy missing

# `make prod-up` recreates nginx whenever nginx.conf changed (the Makefile stamps
# its hash on the service), and a broken file would then take the whole site
# down. Test the checked-out file in a throwaway container of the same image
# first; `set -e` stops the deploy here, before migrations, with the old stack
# still serving.
NGINX_IMAGE="$(docker compose -f "${COMPOSE_FILE}" config --format json \
    | python3 -c 'import json, sys; print(json.load(sys.stdin)["services"]["nginx"]["image"])')"
docker run --rm -v "${REPO_DIR}/nginx/nginx.conf:/etc/nginx/nginx.conf:ro" "${NGINX_IMAGE}" nginx -t </dev/null

# Migrations run from the NEW image while the OLD containers still serve. That
# order is what keeps a deploy from 500ing in between: every migration this
# project ships is additive, so old code tolerates the new schema, while new
# code cannot tolerate the old one.
#
# `-T` and `</dev/null`: `run` attaches the container to this script's stdin
# otherwise, and when the script itself arrives on stdin the container swallows
# the rest of it.
docker compose -f "${COMPOSE_FILE}" run --rm --no-deps -T app-svc alembic upgrade head </dev/null

# The bot's Discord emoji, from the NEW image: uploads whatever names this
# release added, skips the rest. Not fatal -- a missing emoji only falls back to
# Unicode, and Discord being unreachable must not stop a deploy. The running bot
# re-reads its emoji every 10 minutes, so nothing restarts for it.
docker compose -f "${COMPOSE_FILE}" --profile tools run --rm --no-deps -T discord-emoji </dev/null \
    || echo "warning: discord-emoji did not finish cleanly; the bot keeps its Unicode fallbacks"

make prod-up PROD_SIZE="${PROD_SIZE}"

docker compose -f "${COMPOSE_FILE}" ps --format '{{.Service}}|{{.State}}|{{.Health}}' | sort

# Dangling layers only. Previous releases' images stay on disk, which is what
# makes a rollback (re-run the workflow with the old tag) a local restart rather
# than a re-download.
docker image prune -f >/dev/null

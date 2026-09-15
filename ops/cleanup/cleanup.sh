#!/bin/bash
# Weekly disk cleanup for the production host (Moscow, msk-1-vm-15za).
#
# What actually fills the disk there and isn't bounded by anything else:
#   - Docker's default json-file log driver has no size cap anywhere in
#     docker-compose.production.yml, and every Python service also mirrors its
#     structured logs to stderr (backend/shared/observability/logging.py) on
#     top of its own rotated file under ./logs/<service> — so container
#     stdout/stderr logs under /var/lib/docker/containers/*/*-json.log grow
#     unbounded even though the app's own log files rotate fine.
#   - Every release tags a NEW image (ops/deploy/remote-deploy.sh only prunes
#     DANGLING layers on purpose, to keep past releases available for a fast
#     rollback) — old release images past the rollback window are dead weight.
#   - Build cache from an occasional `make prod-build` (hotfix path).
# This script reclaims all three. It does not touch volumes or bind-mounted
# app data: nothing here is a data-loss risk.
#
# Prod (Moscow) crontab:
#   0 5 * * 0 /root/disk-cleanup/cleanup.sh >> /var/log/disk-cleanup.log 2>&1
set -euo pipefail

# Unused (not attached to any container, running or stopped) images older than
# this keep no rollback value. 14 days covers "roll back to last week's release".
IMAGE_RETENTION="${IMAGE_RETENTION:-336h}"
BUILD_CACHE_RETENTION="${BUILD_CACHE_RETENTION:-168h}"
# Container json-file logs above this size get truncated in place. Docker
# keeps writing to the same (now-empty) inode -- this is the documented
# workaround for a driver with no rotation, and needs no container restart.
MAX_LOG_BYTES="${MAX_LOG_BYTES:-209715200}" # 200 MiB
DOCKER_CONTAINERS_DIR="${DOCKER_CONTAINERS_DIR:-/var/lib/docker/containers}"

echo "=== $(date -u +%FT%TZ) disk cleanup start"
echo "-- disk usage before:"
df -h / 2>/dev/null || true
docker system df

echo "-- truncating oversized container logs (> $((MAX_LOG_BYTES / 1024 / 1024)) MiB)"
if [ -d "$DOCKER_CONTAINERS_DIR" ]; then
	find "$DOCKER_CONTAINERS_DIR" -maxdepth 2 -name '*-json.log' -size +"${MAX_LOG_BYTES}"c -print 2>/dev/null |
		while IFS= read -r log; do
			echo "truncating $log ($(du -h "$log" | cut -f1))"
			: >"$log"
		done
else
	echo "skip: $DOCKER_CONTAINERS_DIR not present (not running on the Docker host)"
fi

echo "-- pruning unused images older than $IMAGE_RETENTION"
docker image prune -af --filter "until=${IMAGE_RETENTION}"

echo "-- pruning stopped containers"
docker container prune -f

echo "-- pruning unused networks"
docker network prune -f

echo "-- pruning build cache older than $BUILD_CACHE_RETENTION"
docker builder prune -af --filter "until=${BUILD_CACHE_RETENTION}"

echo "-- disk usage after:"
df -h / 2>/dev/null || true
docker system df
echo "=== $(date -u +%FT%TZ) disk cleanup ok"

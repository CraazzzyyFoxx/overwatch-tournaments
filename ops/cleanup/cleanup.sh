#!/bin/bash
# Daily disk cleanup for the production host (Moscow, msk-1-vm-15za).
#
# What fills the disk there and isn't bounded by anything else:
#   - Every release tags a NEW image (ops/deploy/remote-deploy.sh only prunes
#     DANGLING layers on purpose, to keep past releases available for a fast
#     rollback) — old release images past the rollback window are dead weight.
#   - Build cache from an occasional `make prod-build` (hotfix path).
#   - Container json-file logs. Since the `x-logging` anchor in
#     docker-compose.{production,monitoring}.yml every service caps its own at
#     50 MiB x 3, rotated by the daemon — the truncation step below is now only
#     a backstop for containers created before that (they keep the old,
#     uncapped driver until they are recreated) and for anything started
#     outside those two compose files.
# It does not touch volumes or bind-mounted app data: nothing here is a
# data-loss risk.
#
# Prod (Moscow) crontab — the REPO copy, so every deploy updates it and there
# is no hand-copied snapshot to go stale. DAILY, not weekly: at three releases
# in a day (2026-09-21) a week's worth of dead images is ~30 GB on a 77 GB disk.
#   15 5 * * * /root/overwatch-tournaments/ops/cleanup/cleanup.sh >> /var/log/disk-cleanup.log 2>&1
set -euo pipefail

# Unused (not attached to any container, running or stopped) images older than
# this keep no rollback value. 72h, not the 14 days this started with: that box
# ran out of disk at 147 images / 56 GB in /var/lib/containerd (2026-09-21),
# because a full release set is ~9 GB unpacked and releases land several times
# a day. Rolling back further than 72h still works — `docker compose pull
# --policy missing` in ops/deploy/remote-deploy.sh re-pulls what is gone — it
# just costs the download instead of a local restart.
IMAGE_RETENTION="${IMAGE_RETENTION:-72h}"
BUILD_CACHE_RETENTION="${BUILD_CACHE_RETENTION:-168h}"
# Container json-file logs above this size get truncated in place. Docker
# keeps writing to the same (now-empty) inode -- this is the documented
# workaround for a driver with no rotation, and needs no container restart.
MAX_LOG_BYTES="${MAX_LOG_BYTES:-209715200}" # 200 MiB
DOCKER_CONTAINERS_DIR="${DOCKER_CONTAINERS_DIR:-/var/lib/docker/containers}"

echo "=== $(date -u +%FT%TZ) disk cleanup start"
echo "-- disk usage before:"
df -h / 2>/dev/null || true
# Reporting only: `set -e` must not abort the reclaim because `df`/`system df`
# hiccuped. A real docker failure still stops the script at the prunes below.
docker system df || true

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
docker system df || true
echo "=== $(date -u +%FT%TZ) disk cleanup ok"

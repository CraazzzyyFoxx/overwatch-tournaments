# Disk cleanup: production host (Moscow)

Two layers, and only the second one is a cron job:

1. **Container logs are capped by Docker itself** — the `x-logging: &log-rotate`
   anchor in `docker-compose.production.yml` and `docker-compose.monitoring.yml`
   gives every service `json-file` with `max-size: 50m`, `max-file: 3`. 150 MiB per
   container, rotated by the daemon, no script involved. Takes effect for a
   container when it is **recreated** (any deploy, or `make prod-up`); containers
   created before it keep the old uncapped driver until then.
2. **Images and build cache** are reclaimed daily by `ops/cleanup/cleanup.sh`:

```
15 5 * * * /root/overwatch-tournaments/ops/cleanup/cleanup.sh >> /var/log/disk-cleanup.log 2>&1
```

That path is the **deployed repo checkout** (`ops/deploy/remote-deploy.sh` keeps
`/root/overwatch-tournaments` at the released tag), so the host always runs the
current script. Do not copy it somewhere else — a hand-made copy silently freezes
at whatever was copied, and a missing one fails in a log nobody reads. 05:15 UTC,
after the nightly backup (`docs/backup-rustfs.md`, 04:30 UTC).

Daily, not weekly: releases land several times a day and a full image set is ~9 GB
unpacked, so a week between runs is ~30 GB of dead images on a 77 GB disk.

---

## Why this exists

| Source | Why it isn't already capped |
| --- | --- |
| `/var/lib/docker/containers/*/*-json.log` | Docker's default `json-file` driver has no size limit **unless it is given one** — which is what the compose anchor above now does. Each Python service's own file (`./logs/<service>/*.log`) rotates fine (loguru, `rotation=1 day retention=30 days` — `backend/shared/observability/logging.py`), and the gateway's does too (lumberjack, `MaxSize=100M MaxBackups=5`), but both also mirror to stderr, which Docker captures. |
| Old release images | `ops/deploy/remote-deploy.sh` runs `docker image prune -f` after every deploy, but that only removes **dangling** (untagged) layers — every release tags a new image on purpose, so past releases stay available for a fast rollback. They still take disk. |
| Build cache | Only grows when `make prod-build` runs (the hotfix path in `ops/deploy/remote-deploy.sh`'s comment) — CI-built images normally skip it entirely. |

## What it does

```bash
ops/cleanup/cleanup.sh
```

1. Truncates any container's `-json.log` in place if it exceeds `MAX_LOG_BYTES` (200 MiB
   default). Docker keeps writing to the same inode — no container restart needed. A
   backstop only, now that the compose anchor caps every service at 50 MiB x 3: it still
   catches containers created before that anchor existed and anything started outside the
   two compose files.
2. `docker image prune -af --filter until=$IMAGE_RETENTION` (default 72h) — removes
   images no container references, older than the retention window. Anything newer, or
   still referenced by a running/stopped container, is untouched.
3. `docker container prune -f` / `docker network prune -f` — stopped containers and unused
   networks, normally near-empty.
4. `docker builder prune -af --filter until=$BUILD_CACHE_RETENTION` (default 7 days).

**Never touches volumes.** `redis-data`, `rabbitmq-data`, `analytics-models` and every
bind-mounted app path are excluded on purpose — this script only reclaims things that are
safe to lose (logs already shipped to Loki, layers GHCR can re-pull, cache that rebuilds
itself).

---

## Config

Every knob is an env var with a safe default, no secrets file needed:

| Var | Default | Meaning |
| --- | --- | --- |
| `IMAGE_RETENTION` | `72h` (3d) | Min age of an unused image before it's pruned. Rolling back past it still works: `docker compose pull --policy missing` re-pulls from GHCR, it just costs the download |
| `BUILD_CACHE_RETENTION` | `168h` (7d) | Min age of build-cache entries before they're pruned |
| `MAX_LOG_BYTES` | `209715200` (200 MiB) | Container log size that triggers truncation |
| `DOCKER_CONTAINERS_DIR` | `/var/lib/docker/containers` | Where to look for `*-json.log` |

## Run

```bash
make cleanup-run          # now
tail -n 50 /var/log/disk-cleanup.log
```

## "It didn't run" — triage, in this order

Nothing alerts on the cron job itself; `HostDiskSpaceLow` / `HostDiskSpaceCritical`
(`monitoring/prometheus/rules/infrastructure.yml`) only see the disk filling. On the host:

```bash
crontab -l | grep cleanup            # 1. is the entry there at all?
ls -l /root/overwatch-tournaments/ops/cleanup/cleanup.sh   # 2. right path, mode 755?
tail -n 40 /var/log/disk-cleanup.log # 3. did it run, and did it end with "disk cleanup ok"?
systemctl status cron                # 4. is cron even running on this box?
journalctl -u cron --since '2 weeks ago' | grep -i cleanup  # 5. what cron itself saw
```

- No `disk cleanup start` line for yesterday → cron never fired it (1, 2, 4, 5). This is
  what was actually wrong on 2026-09-21: there was no crontab entry at all, the
  `/root/disk-cleanup/` path the first version of this doc named never existed, and the
  disk had reached 94% with 147 images / 56 GB under `/var/lib/containerd`.
- `start` but no `ok` → it aborted mid-run (`set -euo pipefail`); the last line printed
  names the step. The two `docker system df` calls are `|| true`, so a failure there is
  not it — a prune failing is. Before that `|| true` existed, one broken container record
  (`docker system df` → `rw layer snapshot not found for container <id>`) was enough to
  kill the whole run on its first command; `docker rm -f <id>` clears it.
- `ok`, disk still climbing → it is not images/cache/logs. `docker system df -v`, then
  `du -xh --max-depth=2 / | sort -rh | head -20` before widening any retention window.

**This host keeps images in `/var/lib/containerd`, not `/var/lib/docker`** (Docker runs
with the containerd snapshotter: `docker info` shows `io.containerd.snapshotter.v1`).
`du /var/lib/docker` reports ~2 GB while the images sit in
`/var/lib/containerd/io.containerd.snapshotter.v1.overlayfs` — don't conclude from it
that Docker is innocent.

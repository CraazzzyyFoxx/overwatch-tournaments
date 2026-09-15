# Disk cleanup: production host (Moscow)

What actually runs on production (Moscow, `msk-1-vm-15za`):

```
0 5 * * 0 /root/disk-cleanup/cleanup.sh >> /var/log/disk-cleanup.log 2>&1
```

The same script lives in the repo as `ops/cleanup/cleanup.sh`. Weekly (Sunday 05:00 UTC),
after the nightly backup (`docs/backup-rustfs.md`, 04:30 UTC) has had time to finish.

---

## Why this exists

Nothing else on the box bounds these three:

| Source | Why it isn't already capped |
| --- | --- |
| `/var/lib/docker/containers/*/*-json.log` | Docker's default `json-file` log driver has no size limit, and no service sets `logging:` options in `docker-compose.production.yml`. Each Python service's own file (`./logs/<service>/*.log`) rotates fine (loguru, `rotation=1 day retention=30 days` — `backend/shared/observability/logging.py`), and the gateway's does too (lumberjack, `MaxSize=100M MaxBackups=5`), but both also mirror to stderr, which Docker captures unbounded. |
| Old release images | `ops/deploy/remote-deploy.sh` runs `docker image prune -f` after every deploy, but that only removes **dangling** (untagged) layers — every release tags a new image on purpose, so past releases stay available for a fast rollback. They still take disk. |
| Build cache | Only grows when `make prod-build` runs (the hotfix path in `ops/deploy/remote-deploy.sh`'s comment) — CI-built images normally skip it entirely. |

## What it does

```bash
ops/cleanup/cleanup.sh
```

1. Truncates any container's `-json.log` in place if it exceeds `MAX_LOG_BYTES` (200 MiB
   default). Docker keeps writing to the same inode — no container restart needed.
2. `docker image prune -af --filter until=$IMAGE_RETENTION` (default 14 days) — removes
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
| `IMAGE_RETENTION` | `336h` (14d) | Min age of an unused image before it's pruned |
| `BUILD_CACHE_RETENTION` | `168h` (7d) | Min age of build-cache entries before they're pruned |
| `MAX_LOG_BYTES` | `209715200` (200 MiB) | Container log size that triggers truncation |
| `DOCKER_CONTAINERS_DIR` | `/var/lib/docker/containers` | Where to look for `*-json.log` |

## Run

```bash
make cleanup-run          # now
tail -n 50 /var/log/disk-cleanup.log
```

## Failures

`HostDiskSpaceLow` / `HostDiskSpaceCritical` (`monitoring/prometheus/rules/infrastructure.yml`)
already watch actual disk usage regardless of cause — this script has no dedicated alert.
If disk keeps climbing after a run, check what's actually growing with `docker system df -v`
before widening the retention windows further.

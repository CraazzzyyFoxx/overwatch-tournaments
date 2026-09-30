# Production host: sizing and bundled Postgres

What machine the production stack needs, and how to run it on a host with no database of
its own: `docker-compose.production.yml` ships PostgreSQL 18 + pgBouncer behind the `db`
profile. A host with an external Postgres leaves the profile off and points `POSTGRES_*` at it.

## Host requirements

|      | Minimum (`PROD_SIZE=small`)    | Recommended (`medium` / `large`) |
| ---- | ------------------------------ | -------------------------------- |
| CPU  | 4 vCPU, x86_64                 | 8 vCPU                           |
| RAM  | 8 GB                           | 16 GB                            |
| Disk | 80 GB SSD                      | 160 GB SSD                       |
| OS   | 64-bit Linux, Docker Engine with Compose v2 | same                |

Where the numbers come from:

- **CPU.** `PROD_SIZE=small` is calibrated on a 4 CPU / 8 GB box, and `large` needs 8
  cores ([`Makefile`](../Makefile)). One FastStream process is one event loop, so extra
  cores only pay off through replicas (`PROD_SIZE`), not through bigger limits.
- **RAM.** With `db` + `telemetry` the container memory reservations add up to ~4.6 GB at
  `small` (~5.9 GB at `large`). The limits add up to ~18 GB — ceilings, not usage. The two
  big swings are `analytics-worker` training (up to `ANALYTICS_WORKER_MEMORY`, default
  `4G`) and Postgres (`POSTGRES_MEMORY`, default `2G`).
- **Disk.** One release's image set is ~9 GB unpacked, and earlier releases stay on disk for
  rollback until the daily [`disk-cleanup.md`](./disk-cleanup.md) job removes them.
  Container logs are capped at 150 MB each. On top of that: the Postgres data, up to 2 GB
  of WAL (`max_wal_size`), and the nightly dump staged in `ops/backup/tmp` before upload.
- **SSD.** The bundled Postgres is tuned for it (`random_page_cost=1.1`,
  `effective_io_concurrency=200`).
- **x86_64 only.** CI builds `linux/amd64` images
  ([`deploy-production.yml`](../.github/workflows/deploy-production.yml)). No GPU:
  `docker-compose.gpu.yml` is a local-dev overlay.
- **Pull, don't build.** `make prod-build` on a 4-core host takes around nine minutes and
  competes with live traffic; releases pull what CI built.

On a 4 vCPU / 8 GB host, set in the root `.env`:

```dotenv
ANALYTICS_WORKER_CPUS=3
ANALYTICS_WORKER_MEMORY=3G
```

nginx publishes plain HTTP on `${APP_BIND:-127.0.0.1}:${APP_PORT}`; TLS is terminated outside
the stack, in front of it. See the `nginx` service comment in `docker-compose.production.yml`.

## Bundled Postgres (profile `db`)

| Service     | Image                          | Reached as                    |
| ----------- | ------------------------------ | ----------------------------- |
| `postgres`  | `postgres:18`                  | `postgres:5432` — migrations, backups, the metrics exporter |
| `pgbouncer` | `edoburu/pgbouncer:v1.25.2-p0` | `pgbouncer:6432`, transaction pooling — every service and the gateway |

Neither is published to the host. Data lives in the `owt_postgres-data` volume.
Both containers read `backend/env/common.env`: the Postgres image takes the same
`POSTGRES_USER` / `POSTGRES_PASSWORD` / `POSTGRES_DB` as the services, so the credentials
exist once.

Memory settings are sized for the minimum host. A bigger host overrides them in the root
`.env`, never in the compose file — a release checkout must stay clean
(`ops/deploy/remote-deploy.sh`):

| Root `.env`                     | Default  | 16 GB host |
| ------------------------------- | -------- | ---------- |
| `POSTGRES_MEMORY`               | `2G`     | `4G`       |
| `POSTGRES_SHARED_BUFFERS`       | `512MB`  | `1GB`      |
| `POSTGRES_EFFECTIVE_CACHE_SIZE` | `1536MB` | `3GB`      |

### Configure

Root `.env`:

```dotenv
COMPOSE_PROFILES=db,telemetry
# telemetry only: the metrics exporter goes straight to Postgres, not through pgBouncer
POSTGRES_EXPORTER_DSN=postgresql://owt:<password>@postgres:5432/owt?sslmode=disable
```

Drop `telemetry` and the DSN if the host does not report to monitoring
([`monitoring/README.md`](../monitoring/README.md)).

`backend/env/common.env`:

```dotenv
POSTGRES_USER=owt
POSTGRES_PASSWORD=<openssl rand -hex 24>
POSTGRES_DB=owt
POSTGRES_HOST=pgbouncer
POSTGRES_PORT=6432
DB_PGBOUNCER=true
DATABASE_URL=postgresql+psycopg://owt:<same password>@postgres:5432/owt
```

- `DATABASE_URL` is the direct connection. Alembic prefers it over `POSTGRES_*`
  (`backend/migrations/env.py`), so migrations bypass transaction pooling, and pgBouncer
  takes its upstream from it. Keep the password hex: pgBouncer's entrypoint parses the URL
  without URL-decoding.
- `POSTGRES_USER` is the cluster superuser the image creates at first start; changing
  `POSTGRES_*` later does not touch an initialized volume.
- pgBouncer accepts 500 clients. That covers `replicas × (DB_POOL_SIZE + DB_MAX_OVERFLOW)
  + GATEWAY_DB_MAX_CONNS` at `PROD_SIZE=large` with the default pools (436). Raise
  `MAX_CLIENT_CONN` in the compose file together with the pools.

Backups ([`backup-rustfs.md`](./backup-rustfs.md)) — `ops/backup/s3.env` overrides the
default container and superuser names in `backup.sh`:

```dotenv
CONTAINER=owt-postgres-1
PGSUPER=owt
HOSTTAG=<host name for the S3 prefix>
```

### First boot

```bash
make prod-pull
docker compose -f docker-compose.production.yml up -d --wait postgres pgbouncer
make prod-migrate
make prod-up PROD_SIZE=small
```

To start from an existing database instead of an empty one, restore the dump between
the second and third steps. The dump carries `alembic_version`, so `prod-migrate` then
applies only the revisions newer than it:

```bash
docker exec -i owt-postgres-1 pg_restore -U owt -d owt --no-owner --no-acl < <dump>
```

### Releases and day-to-day

- `ops/deploy/remote-deploy.sh` and `make prod-up` need nothing extra: the profile comes
  from the root `.env`, migrations reach Postgres through `DATABASE_URL`. Compose recreates
  `postgres` only when its own config changes (image, memory knobs) — a few seconds of
  database downtime that the service pools reconnect through.
- psql: `docker compose -f docker-compose.production.yml exec postgres psql -U owt -d owt`.
- The image tag pins the major version on purpose. The volume holds a PostgreSQL 18
  cluster; moving to 19 is a dump and restore into a fresh volume, not a tag bump.

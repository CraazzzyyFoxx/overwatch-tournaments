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
# The same user as backend/env/common.env: pgBouncer's admin console admits it
# (ADMIN_USERS), which the post-migration RECONNECT needs. Unset, it falls back to `postgres`.
POSTGRES_USER=owt
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
- pgBouncer sizing is in the compose file, with the arithmetic in its comments. See
  [pgBouncer](#pgbouncer) below.

Backups ([`backup-rustfs.md`](./backup-rustfs.md)) — `ops/backup/s3.env` overrides the
default container and superuser names in `backup.sh`:

```dotenv
CONTAINER=owt-postgres-1
PGSUPER=owt
HOSTTAG=<host name for the S3 prefix>
```

### pgBouncer

- **Clients: 2000** (`MAX_CLIENT_CONN`). That covers `replicas × (DB_POOL_SIZE +
  DB_MAX_OVERFLOW) + GATEWAY_DB_MAX_CONNS`, which comes to 496 at `PROD_SIZE=large` with the
  default pools, and leaves room to grow the pools. A client slot costs pgBouncer memory, not a
  Postgres backend.
- **Servers: 60 at most.** That is a pool of 50 (`DEFAULT_POOL_SIZE`) plus 10 reserve
  connections (`RESERVE_POOL_SIZE`), handed out once a client has waited 3 s.
  `MAX_DB_CONNECTIONS=60` caps the database whatever the user. Postgres allows
  `POSTGRES_MAX_CONNECTIONS` (root `.env`, default 100). That covers the 60, plus direct
  sessions (migrations, the exporter, backups, psql), plus 3 superuser slots. Raise it
  together with `MAX_DB_CONNECTIONS`, and never below it.
- **Timeouts.** A client that waits 30 s for a backend is disconnected
  (`QUERY_WAIT_TIMEOUT`; the default is 120 s). So is a client that sits idle inside a
  transaction for 60 s (`IDLE_TRANSACTION_TIMEOUT`). Code must not hold a transaction open
  across a slow external call.
- **Prepared statements.** The services keep asyncpg's prepared-statement cache behind
  pgBouncer, so a repeated statement costs one round trip instead of three (prepare,
  execute, close). This needs pgBouncer ≥ 1.21 with `max_prepared_statements > 0`. The
  bundled one sets 200 (`MAX_PREPARED_STATEMENTS`); 1.24+ defaults to 200.
  - **External pooler** (Moscow's `db_pgbouncer`): it must run pgBouncer ≥ 1.21 with
    `max_prepared_statements ≥ 200` (check `SHOW CONFIG;` on its admin console). If it
    does not, set `DB_PGBOUNCER_PREPARED_STATEMENTS=false` in `backend/env/common.env`.
    Otherwise queries fail with `prepared statement "__asyncpg_…__" does not exist`.
  - **Postgres memory.** Each backend keeps up to 200 prepared statements, so 60 backends
    hold up to 12,000 cached statements. Lower `MAX_PREPARED_STATEMENTS` if backend memory
    grows.
  - **After a migration that changes the type of a column the services select**, the
    statements pgBouncer shares across clients keep failing with `cached plan must not
    change result type` until their backend is recycled (pgBouncer
    [docs](https://www.pgbouncer.org/config.html#max_prepared_statements)). `RECONNECT` on
    the admin console recycles every server connection as its transaction ends.
    - **Bundled pgBouncer:** automatic. `make prod-migrate` and `ops/deploy/remote-deploy.sh`
      run `make prod-pgbouncer-reconnect` right after a successful `alembic upgrade head`
      when the `pgbouncer` container is running. It logs in as `POSTGRES_USER` with
      `POSTGRES_PASSWORD`, so the root `.env` must carry `POSTGRES_USER` (see
      [Configure](#configure)). A failure only prints a warning and the deploy goes on: then
      restart pgBouncer (`docker compose -f docker-compose.production.yml restart pgbouncer`).
    - **External pooler:** a manual step, right after the migration. Connect to its admin
      console as one of its `admin_users` and run `RECONNECT;`
      (`psql -h <pooler host> -p <port> -U <admin user> -d pgbouncer -c RECONNECT`), or
      restart it.
- **`statement_timeout`.** pgBouncer rejects it as a startup parameter. The services
  therefore apply `DB_STATEMENT_TIMEOUT` (30 s) at the start of every transaction. The
  gateway sends none under pgBouncer and relies on its request deadlines.
  `ALTER ROLE <user> SET statement_timeout` would cover the gateway too, but it also
  applies to every other session that logs in as that user, migrations included (`pg_dump`
  overrides it itself). Long migrations then need `PGOPTIONS='-c statement_timeout=…'`, as
  in the [cutover runbook](./releases/2026-10-23-prod-cutover.md).

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
  `postgres` only when its own config changes (image, the `POSTGRES_*` knobs) — a few
  seconds of database downtime that the service pools reconnect through.
- A migration that changes a selected column's type needs pgBouncer's shared prepared
  statements re-prepared afterwards: automatic for the bundled pooler, manual for an external
  one ([pgBouncer](#pgbouncer)).
- A release that cannot migrate under live traffic goes behind the maintenance page:
  `make maint-on MIN=<minutes>` / `maint-eta` / `maint-off` (nginx answers 503 with an ETA countdown, `/health`
  stays live). Runbook: [`releases/2026-10-23-prod-cutover.md`](./releases/2026-10-23-prod-cutover.md).
- psql: `docker compose -f docker-compose.production.yml exec postgres psql -U owt -d owt`.
- The image tag pins the major version on purpose. The volume holds a PostgreSQL 18
  cluster; moving to 19 is a dump and restore into a fresh volume, not a tag bump.

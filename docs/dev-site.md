# Runbook — a second deployment (dev site)

A second, self-contained deployment of the same stack, for trying a change against real data
before it is tagged for production. It shares nothing with production except object storage
and the OAuth applications; separate database, separate Redis/RabbitMQ, separate JWT secret,
separate cookie namespace.

| | Production | Dev site |
| --- | --- | --- |
| Compose project | `owt` | e.g. `owt-dev` (`COMPOSE_PROJECT_NAME`) |
| Images | GHCR, tag = release tag | built on the box, tag `dev` |
| nginx | `${APP_BIND}:${APP_PORT}` | its own `APP_PORT` |
| Platform zone | `owt.craazzzyyfoxx.me` (default) | the dev host (`PLATFORM_ZONE`) |
| Tracing | on | off (`TRACING_ENABLED=false`) |
| Telemetry agent | `alloy` + `nginx-exporter` (`COMPOSE_PROFILES=telemetry`) | none — profile left off |
| Cookie names | `owt_*` | e.g. `owtdev_*` (`COOKIE_PREFIX`/`SESSION_COOKIE_PREFIX`) |
| discord-worker | 1 replica | 1 replica, own bot token |

## Why `PLATFORM_ZONE` exists

A dev host under the production platform zone (`dev.<zone>`) would, with the zone hardcoded,
read as production's `dev` *tenant*: `proxy.ts` resolves the host to a workspace, finds none,
and rewrites every request to `/not-configured` (404) — and its session cookies, written under
`Domain=.<zone>`, would collide with production's. Both sides of the stack therefore take the
zone from the environment:

- backend — `PLATFORM_ZONE` in `backend/env/common.env` (`shared/tenancy/hostnames.py`);
- frontend — `NEXT_PUBLIC_PLATFORM_ZONE`, a **build arg** as well as a runtime variable
  (`frontend/src/lib/site/host.ts`), because the client bundle inlines it;
- compose — `PLATFORM_ZONE` in the root `.env` feeds that build arg.

Both default to `owt.craazzzyyfoxx.me`, so production needs no configuration to keep working.

## Why the cookie prefix exists

The zone split is not enough on its own. Production writes `owt_access_token`,
`owt_refresh_token` and `owt_oauth_csrf` with `Domain=.<zone>` for cross-subdomain SSO, so
the browser sends them to a dev host under that zone as well — and the `Cookie` header carries
no `Domain`, so the dev deployment cannot tell them from its own. RFC 6265 orders same-name
cookies by path length then creation time, so the older **production** token wins every dev
request, fails signature verification against the dev JWT secret, and cannot be cleared from
the dev side at all (a delete cannot match production's `Domain`). That is a permanently
broken dev session for anyone who is logged into production.

So each deployment owns a cookie namespace:

- frontend — `NEXT_PUBLIC_COOKIE_PREFIX`, build arg **and** runtime variable
  (`frontend/src/lib/auth/cookie-names.ts` is the single source of the names);
- gateway — `SESSION_COOKIE_PREFIX` in `backend/env/gateway.env`
  (`gateway/internal/auth`), which MUST match;
- compose — `COOKIE_PREFIX` in the root `.env` feeds the frontend build arg.

Default `owt`, so production is untouched. The `aqt_*` fallback names stay unprefixed: they
are read-only leftovers of the old rename and were always host-only, so they cannot leak
across deployments.

Quick check that the namespace is live (a production-named cookie must be invisible):

```bash
curl -sX POST -H 'Cookie: owt_refresh_token=x' https://<dev-host>/auth/refresh
# {"message":"Missing refresh token"}      <- ignored, correct
curl -sX POST -H 'Cookie: owtdev_refresh_token=x' https://<dev-host>/auth/refresh
# {"message":"Failed to refresh"}          <- read, then rejected upstream
```

## Prerequisites outside the repo

1. **DNS** — a record for the dev host. If the production zone has a wildcard, the specific
   record is what must win.
2. **OAuth redirect** — every provider app (Discord, Twitch, Battle.net; the same client IDs
   production uses) must allow `https://<dev-host>/auth/callback`. The site works fully while
   logged out without this; login fails at the provider.
3. **TLS** — terminated in front of nginx, routed to the dev deployment's `APP_PORT`.

## Untracked files the box needs

`.gitignore` keeps these out of the repo, so a fresh clone cannot start without them:

- `.env` — the compose overlay (`COMPOSE_PROJECT_NAME`, `IMAGE_TAG=dev`, `APP_PORT`,
  `APP_BIND=127.0.0.1`, `SITE_URL`, `SITE_NAME`, `PLATFORM_ZONE`, `COOKIE_PREFIX=owtdev`,
  `TRACING_ENABLED=false`,
  `SENTRY_ENVIRONMENT=development`, empty `NEXT_PUBLIC_GA_ID`/`NEXT_PUBLIC_YM_ID`,
  `ANALYTICS_WORKER_CPUS`/`ANALYTICS_WORKER_MEMORY` sized for the box, and
  `NEXT_PUBLIC_DISCORD_CLIENT_ID` — the **dev** bot's application id, i.e. the same value as
  `DISCORD_CLIENT_ID` in `backend/env/auth.env`, never production's; it is baked into the
  frontend bundle as the `client_id` of the "Add bot to server" link, so pointing it at
  production's app would invite production's bot). No `COMPOSE_PROFILES=telemetry`: the Alloy
  agent in `docker-compose.production.yml` pushes into production monitoring and is
  production-only.
- `backend/env/*.env` — from the `.example` files, with `PLATFORM_ZONE`,
  `GATEWAY_WS_ALLOWED_ORIGINS` and `OAUTH_REDIRECT` on the dev host,
  `SESSION_COOKIE_PREFIX=owtdev` in `gateway.env`, a
  **dev-only** `JWT_SECRET_KEY` (and `gateway.env`'s `JWT_PUBLIC_KEY` for it: `make
  prod-jwt-public-key` after the build below), a **dev-only** `OAUTH_TOKEN_ENCRYPTION_KEY`
  (base64url of 32 random bytes, the generator is in `auth.env.example`; the same value in
  `auth.env`, `stats.env` and `tournament.env` — identity refuses to start without it while
  Discord or Twitch OAuth is on), and `POSTGRES_*` pointing at the dev database.
- `proxy/xray.json` — the `proxy` sidecar's config, if outbound API calls need it. A dead
  outbound shows up as every Discord check answering `unknown`.

## Home PostgreSQL resource limits

On `home`, `db_postgres` is managed outside this repo by
`/home/craazzzyyfoxx/postgres/docker-compose.yml`. The `postgres` service has
`mem_limit: 8g` and `cpus: 4`, so container recreation retains both limits.
Apply these limits to a running container without restarting PostgreSQL:

```bash
docker update --memory 8g --memory-swap 16g --cpus 4 db_postgres
```

The swap setting is RAM plus swap: 8 GiB RAM and up to 8 GiB additional swap,
matching Compose's default when `memswap_limit` is unset.

## Deploy / update

```bash
git fetch origin <branch>:<branch> && git checkout <branch>   # or `git am` a patch
docker compose -f docker-compose.production.yml build
docker compose -f docker-compose.production.yml run --rm --no-deps -T app-svc \
    alembic upgrade head </dev/null
make prod-discord-emoji    # the dev bot's own application emoji; skips what is already there
NGINX_CONF_SHA=$(sha256sum nginx/nginx.conf | cut -c1-12) \
docker compose -f docker-compose.production.yml up -d --wait --no-build \
    --scale app-svc=1 --scale identity-svc=1 --scale tournament-svc=2 --scale frontend=2 \
    proxy rabbitmq redis app-svc identity-svc identity-auth-svc tournament-svc stats-svc stats-worker balancer-svc \
    analytics-svc analytics-worker stream-svc gateway frontend nginx
```

Same replicas and limits as production `PROD_SIZE=small` (`PROD_SCALE_small` in the
`Makefile`), minus `discord-worker` until its outbox is reviewed (see below) — which is why
this is not `make prod-up`. `analytics-worker` takes `ANALYTICS_WORKER_CPUS`/`_MEMORY` from
the box's `.env`.

`discord-worker` runs with its own bot token, not production's. Reusing production's token
would double-handle every Discord event. That also means its own application emoji: the dev
bot shows Unicode stand-ins until `make prod-discord-emoji` has uploaded them, and picks them up
within 10 minutes without a restart. `stream-svc` gets no Twitch credentials — polling
would share production's Helix rate-limit bucket.

Tear down with `make prod-down`; the database survives it.

## Building and heavy jobs

Build images off-host, one at a time, importing the existing registry cache without publishing to
it. Do not run the frontend compiler on an unstable dev server: the observed Turbopack build
exceeded a 3 GiB builder limit; the successful off-host build used 2 CPUs / 6 GiB, not server resources.
Transfer completed immutable images with a checksum and load them sequentially or throttle the
input stream. Do not overlap image imports, database exports and receipt capture. Build-time
memory requirements do not change the runtime ceilings above.

For full-data evidence, use one read-only job/connection at a time: low client CPU/memory limits,
`work_mem=16MB`, `hash_mem_multiplier=1`, JIT off and no parallel PostgreSQL workers. Lower only
that job's verified database backend to nice 19 / idle I/O priority; never change other database
processes or shared server settings. A receipt job may additionally cap its own backend's address
space growth and must fail rather than waive a proof when that budget is exceeded. Decode the
entire backup payload and verify its checksum before activation. Preserve any interrupted attempt;
publish new evidence in a new directory instead of overwriting an immutable receipt.

## Refreshing the data

Restore the latest production dump into a **new isolated database**, not over the currently
running dev database. For P4 the staged database is `owt_dev`; retain `anak_dev` for rollback.
Check the dump's revision before choosing migration checkpoints:
`pg_restore -a -t alembic_version -f - <dump>`.

With all writers to the staged database absent, apply the pinned migration source, complete
the source/native reconciliation and publish the immutable receipt described in
[`backend/README.md`](../backend/README.md#p4-statistics-cutover-stats01--stats01a).
Keep the source dump/checksum, code revision, receipt, verification report and a final backup
whose complete payload has been decoded successfully with `pg_restore --file=/dev/null`.
Equal table counts alone are not a losslessness proof.

### Isolate the dataset before activation

- Use a new Compose project generation (`owt-dev-p4` for this cutover). Its project-owned
  Redis/RabbitMQ volumes and network must be new, not external/shared. This retires old
  cache payloads and ID-bearing queue/DLQ messages together without deleting them.
  Keep the old project stopped, not removed; never attach its broker to the new database.
- Give the new deployment its own S3 bucket (`owt-dev-p4-20261017` for this cutover), including
  a public URL for that bucket. Reuse `scripts/configure_s3_policies.py`: only `avatars/*`
  and `assets/*` are public. Verify an actual raw-object round trip and denied anonymous read.
  Parser retention can delete objects; a separate database alone does not protect shared S3.
  Historical raw references remain `unverified` until actual copied bytes are inspected.
- Rotate the **dev-only** `JWT_SECRET_KEY` for identity and put its new `make prod-jwt-public-key`
  into gateway's `JWT_PUBLIC_KEY`. Recreate
  gateway too: it has an in-memory identity cache. Missing SQL sessions do not invalidate
  otherwise valid access JWTs; old Redis refresh/RBAC responses cannot be reused.
  A fresh project avoids flushing shared cache namespaces or deleting SID revocation flags.
- Keep `discord-worker` stopped unless its restored outbox/destinations are separately reviewed;
  a dev bot token is not a destination allowlist. Keep stream Twitch credentials absent.
  `ENVIRONMENT=staging` is not a delivery sandbox. Disable automatic Challonge sync and
  historical log reaping for this activation; these switches do not disable every scheduler.
- Inventory all restored pending/failed `event_outbox` types, including delayed retries,
  without exposing payloads. Do not falsely mark messages published or delete history to pass
  a gate. After activation, normal dev schedulers may create legitimate audited changes.

Only after proof and isolation: stop the old project, atomically install the paired database,
S3, project and signing configuration, verify effective overrides, and start the explicitly
selected new services. Do not use an unqualified `up` that also starts the Discord worker.
Run at `PROD_SIZE=small` scale (see Deploy / update).

Record the actual source commit, built/running image IDs, effective database/head, Compose
project, bucket, backup SHA and receipt identity. Set backend `GIT_SHA` to the verified build
revision; a floating `:dev` tag or the service's static version is not release evidence.
Exercise real API and browser paths after readiness checks.

Rollback is paired: stop the new project, restore the protected old environment files, then
start the retained old containers against their old database, broker and cache volumes.
Do not recreate them using the new dataset configuration.

## Verify

```bash
curl -s -o /dev/null -w '%{http_code}\n' https://<dev-host>/health   # 200, valid TLS
curl -s https://<dev-host>/ | grep -o '<title>[^<]*</title>'         # NOT /not-configured
curl -s 'https://<dev-host>/api/v1/tournaments?page=1&per_page=2'    # data from the restore
```

A homepage that renders `/not-configured` means `PLATFORM_ZONE` is wrong (or missing) on one
of the two sides — the frontend one is baked into the image, so it needs a rebuild, not a
restart.

## Local frontend against the dev site

Run only `next dev` locally; everything behind `/api` is the dev site. In `frontend/.env.local`:

```bash
NEXT_INTERNAL_API_URL=https://<dev-host>     # next.config.mjs rewrites /api/* there; SSR fetches it
NEXT_PUBLIC_COOKIE_PREFIX=owtdev             # the dev gateway's SESSION_COOKIE_PREFIX
DEV_AUTH_EMAIL=dev-admin@<dev-host>
DEV_AUTH_PASSWORD=<password>
```

OAuth cannot finish on localhost: `OAUTH_REDIRECT` is fixed to the dev host, which keeps the
session on itself. With `DEV_AUTH_*` set, `/admin` without a session redirects to
`/auth/dev-login` (`frontend/src/app/(site)/auth/dev-login/route.ts`). That route signs in through
`POST /api/v1/auth/login` and sets the usual host-only cookies on `localhost`. From there it is an
ordinary session: `/auth/refresh` rotates it for 30 days, and once it dies the next `/admin` load
signs in again. Other pages: open `/auth/dev-login?next=/path`. The route answers 404 in a
production build or without both variables, and on bad credentials it shows a plain error page
(no redirect loop).

The account is `dev-admin` (`auth.user`, superuser, password-only) in the dev database. A data
refresh from a production dump drops it; recreate it:

```bash
curl -sX POST https://<dev-host>/api/v1/auth/register -H 'Content-Type: application/json' \
    -d '{"email":"dev-admin@<dev-host>","username":"dev-admin","password":"<password>"}'
docker exec db_postgres psql -U system -d owt_dev -c \
    "UPDATE auth.\"user\" SET is_superuser = true, is_verified = true WHERE username = 'dev-admin'"
```

Realtime does not reach the dev site from localhost: the WebSocket goes to
`ws://localhost:3000/api/v1/realtime/ws`, and `GATEWAY_WS_ALLOWED_ORIGINS` does not list
`http://localhost:3000`.

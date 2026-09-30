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
- `backend/env/*.env` — from the `.example` files, with `PLATFORM_ZONE`, `PROJECT_URL`,
  `CORS_ORIGINS`, `GATEWAY_WS_ALLOWED_ORIGINS` and `OAUTH_REDIRECT` on the dev host,
  `SESSION_COOKIE_PREFIX=owtdev` in `gateway.env`, a
  **dev-only** `JWT_SECRET_KEY`/`ACCESS_TOKEN_SERVICE`, and `POSTGRES_*` pointing at the dev
  database.
- `proxy/xray.json` — the `proxy` sidecar's config, if outbound API calls need it. A dead
  outbound shows up as every Discord check answering `unknown`.

## Deploy / update

```bash
git fetch origin <branch>:<branch> && git checkout <branch>   # or `git am` a patch
docker compose -f docker-compose.production.yml build
docker compose -f docker-compose.production.yml run --rm --no-deps -T app-svc \
    alembic upgrade head </dev/null
make prod-up PROD_SCALE='app-svc=1 identity-svc=1 tournament-svc=1 frontend=1'
```

`discord-worker` runs with its own bot token, not production's. Reusing production's token
would double-handle every Discord event. `stream-svc` gets no Twitch credentials — polling
would share production's Helix rate-limit bucket.

Tear down with `make prod-down`; the database survives it.

## Refreshing the data

The database is a restore of the production dump ([`backup-rustfs.md`](./backup-rustfs.md)),
not a live replica: drop and recreate the dev database, then `pg_restore --no-owner --no-acl`
the latest production dump into it.

Check where a dump sits in the chain before restoring — `pg_restore -a -t alembic_version -f -
<dump>` prints its revision, and that decides how many migrations `upgrade head` will run.

## Verify

```bash
curl -s -o /dev/null -w '%{http_code}\n' https://<dev-host>/health   # 200, valid TLS
curl -s https://<dev-host>/ | grep -o '<title>[^<]*</title>'         # NOT /not-configured
curl -s 'https://<dev-host>/api/v1/tournaments?page=1&per_page=2'    # data from the restore
```

A homepage that renders `/not-configured` means `PLATFORM_ZONE` is wrong (or missing) on one
of the two sides — the frontend one is baked into the image, so it needs a rebuild, not a
restart.

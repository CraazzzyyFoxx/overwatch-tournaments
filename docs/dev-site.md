# Runbook — the dev site (`dev.owt.craazzzyyfoxx.me`)

A second, self-contained deployment of the same stack on the home server
(`home.craazzzyyfoxx.me`, `91.135.214.75`), for trying a change against real data before it
is tagged for production. It shares nothing with production except MinIO objects and the
OAuth applications; separate database, separate Redis/RabbitMQ, separate JWT secret,
separate cookie namespace.

| | Production | Dev site |
| --- | --- | --- |
| Host | `217.149.19.31`, `/root/overwatch-tournaments` | `home`, `~/owt-dev` |
| Compose project | `owt` | `owt-dev` (`COMPOSE_PROJECT_NAME`) |
| Images | GHCR, tag = release tag | built on the box, tag `dev` |
| Edge | Traefik (host) → nginx `127.0.0.1:80` | Traefik (host) → nginx `127.0.0.1:8081` |
| Platform zone | `owt.craazzzyyfoxx.me` | `dev.owt.craazzzyyfoxx.me` |
| Postgres | its own | host `db_postgres` via `db_pgbouncer`, database `anak_dev` |
| Tracing | otel-collector → Tempo/Sentry | off (`TRACING_ENABLED=false`) |
| Cookie names | `owt_*` | `owtdev_*` (`COOKIE_PREFIX`/`SESSION_COOKIE_PREFIX`) |
| discord-worker | 1 replica | **0 replicas** |

## Why `PLATFORM_ZONE` exists

`dev.owt.craazzzyyfoxx.me` is a subdomain of the production platform zone, so with the zone
hardcoded the dev site read as production's `dev` *tenant*: `middleware.ts` resolved the host
to a workspace, found none, and rewrote every request to `/not-configured` (404) — and its
session cookies, written under `Domain=.owt.craazzzyyfoxx.me`, would have collided with
production's. Both sides of the stack therefore take the zone from the environment:

- backend — `PLATFORM_ZONE` in `backend/env/common.env` (`shared/tenancy/hostnames.py`);
- frontend — `NEXT_PUBLIC_PLATFORM_ZONE`, a **build arg** as well as a runtime variable
  (`frontend/src/lib/host.ts`), because the client bundle inlines it;
- compose — `PLATFORM_ZONE` in the root `.env` feeds that build arg.

Both default to `owt.craazzzyyfoxx.me`, so production needs no configuration to keep working.

## Why the cookie prefix exists

The zone split is not enough on its own. Production writes `owt_access_token`,
`owt_refresh_token` and `owt_oauth_csrf` with `Domain=.owt.craazzzyyfoxx.me` for
cross-subdomain SSO, so the browser sends them to the dev site as well — and the `Cookie`
header carries no `Domain`, so the dev deployment cannot tell them from its own. RFC 6265
orders same-name cookies by path length then creation time, so the older **production**
token won every dev request, failed signature verification against the dev JWT secret, and
could not be cleared from the dev side at all (a delete cannot match production's `Domain`).
That is a permanently broken dev session for anyone who is logged into production.

So each deployment owns a cookie namespace:

- frontend — `NEXT_PUBLIC_COOKIE_PREFIX`, build arg **and** runtime variable
  (`frontend/src/lib/cookie-names.ts` is the single source of the names);
- gateway — `SESSION_COOKIE_PREFIX` in `backend/env/gateway.env`
  (`gateway/internal/auth`), which MUST match;
- compose — `COOKIE_PREFIX` in the root `.env` feeds the frontend build arg.

Default `owt`, so production is untouched. The `aqt_*` fallback names stay unprefixed: they
are read-only leftovers of the old rename and were always host-only, so they cannot leak
across deployments.

Quick check that the namespace is live (a production-named cookie must be invisible):

```bash
curl -sX POST -H 'Cookie: owt_refresh_token=x' https://dev.owt.craazzzyyfoxx.me/auth/refresh
# {"message":"Missing refresh token"}      <- ignored, correct
curl -sX POST -H 'Cookie: owtdev_refresh_token=x' https://dev.owt.craazzzyyfoxx.me/auth/refresh
# {"message":"Failed to refresh"}          <- read, then rejected upstream
```

## Prerequisites that live outside the repo

1. **DNS** — `dev.owt` A record → `91.135.214.75` in the Timeweb zone for
   `craazzzyyfoxx.me`. Note the zone also has a `*.owt` wildcard pointing at production, so
   the specific record is what wins; without it Traefik cannot pass the HTTP-01 challenge and
   the ACME error is `the server didn't respond to our request (status=pending)`.
2. **OAuth redirect** — every provider app (Discord, Twitch, Battle.net; the same client IDs
   production uses) must allow `https://dev.owt.craazzzyyfoxx.me/auth/callback`. The site
   works fully while logged out without this; login fails at the provider.
3. **Traefik** — `/etc/traefik/dynamic.yml` on the host carries the router and service:

   ```yaml
   http:
     routers:
       owt-dev:
         rule: "Host(`dev.owt.craazzzyyfoxx.me`)"
         service: owt-dev-svc
         entryPoints: [websecure]
     services:
       owt-dev-svc:
         loadBalancer:
           servers:
             - url: "http://127.0.0.1:8081"
   ```

   Traefik watches the file, but it only re-requests a failed certificate when the config
   actually **changes** — rewriting identical bytes is a no-op. If the cert is missing after
   fixing DNS, append a comment line to force a reload, then check
   `journalctl -u traefik -f | grep -i acme`.

## Untracked files the box needs

`.gitignore` keeps these out of the repo, so a fresh clone cannot start without them:

- `.env` — the compose overlay (`COMPOSE_PROJECT_NAME`, `IMAGE_TAG=dev`, `APP_PORT=8081`,
  `APP_BIND=127.0.0.1`, `SITE_URL`, `SITE_NAME`, `PLATFORM_ZONE`, `COOKIE_PREFIX=owtdev`,
  `TRACING_ENABLED=false`,
  `SENTRY_ENVIRONMENT=development`, empty `NEXT_PUBLIC_GA_ID`/`NEXT_PUBLIC_YM_ID`,
  `ANALYTICS_WORKER_CPUS=3`, `ANALYTICS_WORKER_MEMORY=3G`).
- `backend/env/*.env` — from the `.example` files, with `PLATFORM_ZONE`, `PROJECT_URL`,
  `CORS_ORIGINS`, `GATEWAY_WS_ALLOWED_ORIGINS` and `OAUTH_REDIRECT` on the dev host,
  `SESSION_COOKIE_PREFIX=owtdev` in `gateway.env`, a
  **dev-only** `JWT_SECRET_KEY`/`ACCESS_TOKEN_SERVICE`, `POSTGRES_*` pointing at
  `host.docker.internal:6432` + `DB_PGBOUNCER=true`, and `PROXY_TYPE=socks5`,
  `PROXY_IP=proxy`, `PROXY_PORT=1080`.
- `proxy/xray.json` — the xray sidecar's config. **`discord.com` is not reachable from this
  host directly**, so every outbound API call goes through it; a dead outbound shows up as
  every Discord check answering `unknown`. The working one is the same config
  `~/pm-specs/proxy/xray.json` uses.

## Deploy / update

```bash
ssh home
cd ~/owt-dev
git fetch && git checkout <branch-or-tag>            # or `git am` a patch for unpushed work
docker compose -f docker-compose.production.yml build
docker compose -f docker-compose.production.yml run --rm --no-deps -T app-svc \
    alembic upgrade head </dev/null
make prod-up PROD_SCALE='app-svc=1 identity-svc=1 tournament-svc=1 frontend=1 discord-worker=0'
```

`discord-worker=0` is not optional: it would be a second bot process on production's token,
double-handling every Discord event. `stream-svc` gets no Twitch credentials for the same
reason — polling would share production's Helix rate-limit bucket.

Tear down with `make prod-down` (in `~/owt-dev`); the database survives it.

## Refreshing the data

The database is a restore of the production dump, not a live replica.

```bash
# on home; dumps arrive here through the backup contour (docs/backup-rustfs.md)
docker run --rm --network host -e PGPASSWORD=<pw> postgres:18.1 \
    psql -h 127.0.0.1 -p 5432 -U system -d postgres \
    -c 'drop database anak_dev with (force)' -c 'create database anak_dev owner system'
docker run --rm --network host -v ~/backups:/b -e PGPASSWORD=<pw> postgres:18.1 \
    pg_restore -h 127.0.0.1 -p 5432 -U system -d anak_dev -j 4 --no-owner --no-acl \
    /b/db-dumps/amsterdam/cold/anak_v5.dump
```

Restore `anak_v5` (production), not `anak_dev`: the dump named `anak_dev` on the production
host is a stale database that stops the migration chain twice — `wsgdvrf01` on duplicate
`workspace.discord_guild_id` and `mix3nf02` on legacy `custom_game.config_json` shapes.
Those guards are working as designed; production's own data passes them.

Check where a dump sits in the chain before restoring — `pg_restore -a -t alembic_version -f -
<dump>` prints its revision, and that decides how many migrations `upgrade head` will run.

## Verify

```bash
curl -s -o /dev/null -w '%{http_code}\n' https://dev.owt.craazzzyyfoxx.me/health   # 200, valid TLS
curl -s https://dev.owt.craazzzyyfoxx.me/ | grep -o '<title>[^<]*</title>'         # NOT /not-configured
curl -s 'https://dev.owt.craazzzyyfoxx.me/api/v1/tournaments?page=1&per_page=2'    # data from the restore
```

A homepage that renders `/not-configured` means `PLATFORM_ZONE` is wrong (or missing) on one
of the two sides — the frontend one is baked into the image, so it needs a rebuild, not a
restart.

# Gateway

The Go gateway is OWT's **sole HTTP and WebSocket entry point**. It terminates HTTP,
resolves the caller's credential, and translates REST routes into typed **request/reply RPC over
RabbitMQ** (`rpc.<service>.<method>`) to the headless FastStream workers. Business logic
stays in the workers; the gateway routes, authorizes, proxies, and relays realtime events.

See [`../docs/architecture.md`](../docs/architecture.md) for the full system overview.

- **Entry point:** `cmd/gateway/main.go`
- **HTTP port:** `8080` (`GATEWAY_PORT`)
- **Metrics port:** `9110` (`GATEWAY_METRICS_PORT`, Prometheus — internal only)

## Overview

Every API request enters through the gateway (nginx sends page traffic straight to the
Next.js frontend). Public reads are served from an in-process cache or fanned out as RPC to
workers; realtime updates are relayed from a Redis bus to WebSocket subscribers. The Python
workers expose **no HTTP** — the gateway is the only backend that speaks HTTP to the outside
world.

## Responsibilities

- **AuthN / AuthZ** — resolves the bearer credential (session JWT or API key) via
  `rpc.identity.validate_token` and injects the resulting RBAC payload into every downstream
  RPC as `data["identity"]`. Every credential first passes a local check — a session JWT's
  EdDSA signature against identity-svc's public key (`JWT_PUBLIC_KEY`), an API key's shape —
  so junk never costs an RPC. See [Authentication](#authentication).
- **RPC dispatch** — typed request/reply RPC over RabbitMQ to `rpc.<service>.*` workers
  (`app`, `identity`, `tournament`, `stats`, `balancer`, `analytics`), with `reply_to` +
  `correlation_id`, an `x-deadline-ms` deadline, and a per-queue in-flight bulkhead
  (`GATEWAY_RPC_MAX_INFLIGHT`) that sheds with a 503 when a queue is saturated. Requests are
  published `mandatory`, so a call to a queue no worker has declared fails at once with 503
  instead of waiting out its timeout; every socket write to the broker is bounded (10 s), and
  while the broker blocks the connection (memory/disk alarm) calls are shed immediately. A JSON
  request body is relayed byte-exact as `data["payload"]`: 413 over the size limit, 400 for
  anything after the JSON value.
- **Realtime hub** — a Redis→WebSocket hub at `/ws` and `/api/v1/realtime/ws`, replaying
  `realtime.workspace_event` rows from Postgres so reconnecting clients catch up. Each connection
  has one ordered writer with at most 64 queued jobs and 4 MiB of serialized backlog, including
  the in-flight job. Replay and its subscription acknowledgement occupy one atomic job before
  live events. Queue overflow or the 2-second frame write deadline disconnects a slow peer without
  blocking Redis event processing; revoked topic frames still queued are discarded before writing.
  A subscription is registered before its cursor is read and holds live frames until its replay
  and acknowledgement are queued, so no event falls between replay and live delivery. When the
  Redis subscription is re-established after a drop (frames may have been lost), the gateway
  flushes its principal, ACL and response caches and closes every socket with 1012, so clients
  reconnect and replay from their cursor. A workspace API key is confined to its own workspace's
  topics and never receives its owner's personal ones.
  The topic ACL runs at subscribe time and again whenever it may have changed: on
  `realtime:user:{id}:rbac` the gateway drops that user's cached workspace memberships and
  re-checks every topic their live connections hold (a removed member gets `forbidden` and stops
  receiving the workspace); on `chat.visibility_changed` it re-checks that chat room's subscribers.
  Response-cache invalidation runs before WebSocket notification. Presence (`*:balancer`,
  `draft:*:board`) is throttled per topic: the first join/leave in a quiet period broadcasts
  at once, and every change inside the following 1 s window folds into one trailing broadcast
  of the hub state at the window's end, so a room filling up costs each subscriber at most two
  presence frames per window instead of one per join.
- **Response cache** — an in-process, in-memory cache of anonymous public reads
  (`respcache`, default 30s TTL), invalidated by workers' Redis pub/sub. Tournament entries
  drop on `tournament:{id}:invalidation`, narrowed to the frame's stale resources. The live
  draft reads (session board, tournament draft lookup, anonymous chat history) are scoped to
  the draft session with a 5s TTL: any frame on `draft:{session_id}:board` drops that
  session's boards, any frame on `draft:{session_id}:chat` its chat pages, and neither ever
  touches a tournament. Bearer requests to the chat history bypass the cache. A
  `tournament.structure` frame drops the tournament's whole scope, since visibility can change
  any page. Bodies over 1 KiB are stored with a gzip copy, served with `Content-Encoding: gzip`
  to clients that accept it (`Vary: Accept-Encoding` on every cached response).
- **Rate limiting** — per-IP token buckets (auth endpoints, anonymous API traffic, and the
  pre-handshake WS custom-domain Origin lookup). "Anonymous" means no valid session JWT and no
  API key identity-svc accepted, so a junk bearer is charged too. The client IP comes from
  `X-Real-IP` / `X-Forwarded-For` only when the socket peer is a trusted proxy
  (`GATEWAY_TRUSTED_PROXIES`). Per-API-key quotas are a different layer, enforced in
  `balancer-service` (see [Authentication](#authentication)).
- **Uploads** — every multipart/binary upload reserves its peak memory from one process-wide
  budget (`GATEWAY_UPLOAD_MEMORY_BUDGET_MB`) before the body is parsed, and is refused with
  503 + `Retry-After` when the budget is spent; a lone upload larger than the budget still runs.
- **API docs** — Scalar API-reference pages served from the gateway's own route tables.
- **Observability** — Prometheus metrics on `:9110` (top endpoints, active-users
  HyperLogLog, RPS/errors/latency) and OpenTelemetry tracing.

## Request flow

```
internet → nginx :80 ─┬─ /api/*, /ws, /api/v1/realtime/ws, /health → gateway :8080 →
                      │      ├─ RPC over RabbitMQ → headless workers + the discord bot (rpc.app.* / rpc.identity.* / rpc.tournament.* / rpc.stats.* / rpc.balancer.* / rpc.analytics.* / rpc.discord.*)
                      │      └─ /ws + /api/v1/realtime/ws → Redis→WebSocket hub (replay from realtime.workspace_event)
                      └─ everything else (pages, /_next/*, /bff/*, /api/health) → frontend :3000
```

## URL shape

Every route is `/api/v{n}/<domain>/...` — one version axis, always the second segment, and no
namespace beside it. `internal/apiver` normalises the inbound path onto that one table before
routing, which is why there is a single 404 catch-all in `cmd/gateway/main.go` instead
of one per namespace, and why `internal/respcache` and the OpenAPI specs only ever see
canonical paths.

| | |
|---|---|
| `/api/v1/...` | the contract: unwrapped, FastAPI-shaped JSON |
| `/api/v2/...` | the same paths, handlers and statuses; body is the RPC envelope (`internal/apierr`) |
| `/api/docs`, `/api/openapi*.json` | the generated reference — outside the version because it describes the versions |
| `/api/health` | the frontend container's probe; nginx routes it to Next, not here |
| `/bff/*` | the frontend's own cookie-authenticated endpoints; nginx routes them to Next, never here |

`auth`, `analytics`, `balancer`, `streams`, `notifications` and `announcements` used to sit
beside the version. Those spellings are still answered — the table is `apiver.LegacyPrefixes`,
matched segment-wise so `/api/authx` is untouched — and every legacy response carries
`Deprecation: true`, `Sunset: <apiver.SunsetDate>` and `Link: <canonical>; rel="successor-version"`.
Deleting the table is the whole removal: the route tables already speak only canonical paths.

The WebSocket is the one exception to the rewrite. `/ws`, `/api/realtime/ws` and
`/api/v1/realtime/ws` are three registrations on the outer router, which sits outside `apiver`
— a hijacked, hour-long connection gains nothing from passing through it.

## Authentication

Two credential types share the `Authorization: Bearer` header, and every authenticated REST
route accepts either one.

| | Session JWT | API key |
|---|---|---|
| Format | EdDSA (Ed25519) JWT — claims `sub`, `sid`, `type`, `iat`, `exp`, `iss`=`owt-identity`, `aud`=`owt`, `jti`; no email, username or superuser bit | `owt_sk_<16 hex>_<64 hex>` (keys issued before the rename carry `aqt_sk_` and still work) |
| Issued by | `POST /api/v1/auth/login` (refreshed via `/api/v1/auth/refresh`) | `POST /api/v1/auth/api-keys` — the plaintext key is returned once and never again |
| Lifetime | short, tied to a session that can be revoked | until its `expires_at`, or until revoked |
| Reach | the caller's full RBAC — global roles/permissions and every workspace | one workspace, and only the permissions the key was scoped to |

```bash
curl -H "Authorization: Bearer owt_sk_a1b2c3_..." https://<host>/api/v1/...
```

REST routes read the credential from the `Authorization` header only
(`internal/principal`, `internal/identity/handler.go`). The `owt_access_token` cookie (legacy
`aqt_access_token` as a fallback) is read by `internal/auth` for WebSocket handshakes, not for REST
authorization. A `?token=` query parameter is never read: a credential in a URL lands in every
proxy access log and in browser history.

### How a credential becomes authorization

`internal/principal` calls `rpc.identity.validate_token` — the gateway is not an auth authority,
it only caches the verdict (30s TTL, 5s for an API key; concurrent misses for one credential
collapsed by singleflight). Before a cache miss may cost that RPC, the credential passes a local
check (`internal/auth`): a session JWT must verify against identity-svc's Ed25519 public key and
carry `type`=`access`, `iss`, `aud` and an unexpired `exp`; an API key must have the exact shape
identity-svc mints. A credential failing it is refused with no RPC and no cache entry, so junk
neither reaches identity-svc nor evicts live sessions. Only identity-svc's verdicts on the
credential (`unauthorized`, `forbidden`, `bad_request`) are cached as rejections; any other error
or malformed reply is a 503 and is not cached. A session verdict never outlives its token's `exp`.

The TTL is a backstop: identity-svc publishes `realtime:user:{id}:rbac` whenever it drops a user's
cached RBAC (membership, role, deny, merge) and after every session revocation (logout, password
change, an admin's revoke), and the resolver — a leg of the realtime fan-out — evicts every token
it cached for that user, so grants and revocations apply on the next request. identity-svc is the
single place that branches on credential type; both branches return the same payload shape, which
the gateway injects as `data["identity"]` — the reply bytes exactly as cached, never re-marshaled —
and the workers rehydrate into an `AuthUser`.

For an API key that payload is its **owner's RBAC, narrowed to the key**: one workspace entry
whose permissions are the key's scopes intersected with what the owner actually holds there, no
global permissions and no role names. Scopes are RBAC permission names (`team.create`,
`registration.approve`, the `admin.*` wildcard) from `backend/shared/rbac/catalog.py` — the same
vocabulary the endpoints are checked against — so a key is authorized by the ordinary permission
check, with no key-specific branch in any worker. A key can never outrank its owner, never
reaches a second workspace, and a key with no scopes can do nothing. See
[`../backend/ARCHITECTURE.md`](../backend/ARCHITECTURE.md) § "Two credentials, one branch".

### Canonical ingest relay

`POST /api/v1/stats/matches` is served by `internal/stats/ingest.go`, not the generic dispatcher: the dispatcher decodes
the body into a map and re-marshals it, which would change the bytes the backend hashes for idempotency. The relay
resolves the key itself, requires `application/json`, caps the body at 25 MiB (`413 match_document_too_large`) and
forwards the original bytes base64-encoded next to the identity. `GET /api/v1/stats/ingest-jobs/{id}` is an ordinary
route.

### Session-only surfaces

`/api/v1/auth` operations that act on the caller's own account or session — logout, session list
and revoke, `/api/v1/auth/me`, password changes, and creating/updating/revoking API keys — resolve
the caller by JWT-decoding the bearer inside identity-svc, so an API key is rejected there with
401. A key can therefore neither mint another key nor extend a session. `DELETE /api/v1/auth/me`
forwards an optional JSON body (`{"current_password": ...}`, the re-auth proof identity-svc asks a
password account for); an empty body stays valid.
`GET /api/v1/auth/api-keys/self` is the inverse: it describes the calling key, so it needs one.

### WebSocket authentication

WebSocket connections (`/ws`, `/api/v1/realtime/ws`) take the credential from the `Authorization`
header (scripts) or the session cookie (browsers) — never from `?token=`. A session JWT passes the
local EdDSA check (its `exp` bounds the socket's lifetime) and then `validate_token`, which supplies
the superuser bit and catches a revoked session; a token identity-svc rejects connects anonymously.
If identity-svc cannot answer, the socket is admitted on the local check alone as that user without
superuser, and a warning is logged. An API key authenticates the socket only if it holds at least
one grant in its workspace (a zero-scope key connects anonymously); its socket is pinned to that
workspace, is never a superuser, and is refused the owner's personal topics (`user:{id}:*`).

On `realtime:user:{id}:rbac` the `ws.TopicRevoker` — after the resolver has evicted that user's
verdicts — re-judges each of the user's live sockets: one whose credential is no longer valid is
closed with 1008 (policy violation, reason `credential revoked`); a valid one takes its fresh
principal and has its topics re-checked against the ACL.

### Rate limits

Anonymous traffic is metered per-IP (`internal/ratelimit`). API keys are metered
per key against `requests_per_minute` when the credential carries one, otherwise
`GATEWAY_API_KEY_RATE_LIMIT` (default 60/min). Balancer job quotas — `jobs_per_day`,
`concurrent_jobs`, `max_upload_bytes`, `max_players`, solver `config_policy` — live
in `balancer-service` (`src/core/security/api_key_limiter.py` / `api_key_policy.py`)
and are not identity defaults. Exceeding a quota returns 429 with `Retry-After`. A key
identity-svc rejects is answered 401 at the edge, and an identity outage 503, so neither
reaches a worker.

`QUOTA_EDGE_WORKSPACE_METERING=true` (default false, shared with the Python enforcer)
additionally counts **every** REST request against its workspace's
`q:ws:{workspace_id}:rpm` bucket and enforces the workspace-scope
`requests_per_minute` ceiling at the edge. The workspace is attributed from the
credential and the `?workspace_id=` query parameter:

- **API key** — its own workspace; still metered on `q:key:{id}:rpm` with the
  unchanged `RateLimit-*` headers and 429.
- **Session** — the queried workspace when the user is a member (or a superuser),
  otherwise its single workspace. No per-user bucket and no `RateLimit-*` headers.
- **Anonymous, or a session that is not a member** — counted in
  `q:pub:ws:{workspace_id}:rpm`, statistics only: public traffic is never refused,
  so strangers cannot spend a tenant offline.

Nothing is charged when the request names no (existing) workspace, when the token
cannot be validated, or when Redis is unreachable (fail-open). A refused request
charges no bucket at all. With the flag off the gateway meters API keys exactly as
described above and writes no `q:ws`/`q:pub` keys.

## Internal packages

Under `internal/`:

| Package | Role |
|---|---|
| `auth` | local EdDSA access-token verification and API-key shape check (credential precheck, WebSocket handshake, request logging, active-user metrics) |
| `principal` | credential resolution via `rpc.identity.validate_token` (session JWT or API key) + RBAC injection |
| `acl` | workspace membership authorization |
| `rpc` | RabbitMQ request-reply client (per-queue bulkhead, `x-deadline-ms`) |
| `edge` | typed route dispatcher |
| `respcache` | in-memory anonymous response cache (with stored gzip copies) |
| `cachecontrol` | cache-control policy |
| `ratelimit` | per-IP rate limiting |
| `clientip` | client IP from forwarding headers, believed only from trusted proxies |
| `upload` | process-wide upload memory budget + base64 RPC body encoding |
| `ws` | WebSocket hub / handler / topic / conn-limit / origin |
| `events` | Redis `realtime:*` fan-out |
| `workspace` | custom-domain resolver + ACL over Postgres |
| `replay` | Postgres `realtime.workspace_event` replay |
| `metrics` | Prometheus + active-users HyperLogLog |
| `tracing` | OpenTelemetry |
| `openapi` / `apidocs` | Scalar API docs |
| `db` | pgx Postgres pool |

Per-domain route tables live under `internal/{tournament,app,stats,balancer,identity,analytics}`.

The gateway reads Postgres **read-only** (ACL / workspace membership, event replay,
custom-domain resolution), uses Redis for the realtime bus + cache-invalidation + active-user
HLL, and RabbitMQ for all RPC, events, and job queues.

## Configuration

Configuration is environment-driven via `internal/config`; see
[`../backend/env/gateway.env.example`](../backend/env/gateway.env.example) for the full,
annotated set. Highlights:

- `JWT_PUBLIC_KEY` — **required**: identity-svc's Ed25519 public key, raw 32 bytes base64url
  without padding (identity logs it at startup; `make jwt-public-key` prints it). The gateway
  never holds the signing secret and no longer loads `backend/env/auth.env`.
- `GATEWAY_PORT=8080`, `GATEWAY_METRICS_PORT=9110`.
- `RABBITMQ_URL`, `REDIS_URL`, `POSTGRES_*` / `DB_PGBOUNCER` (shared with the workers).
- WebSocket knobs (`WS_IDLE_TIMEOUT`, `WS_REPLAY_LIMIT`, `GATEWAY_WS_ALLOWED_ORIGINS`,
  per-IP conn/topic caps), rate-limit knobs (`GATEWAY_AUTH_RATE_LIMIT`,
  `GATEWAY_ANON_RATE_LIMIT`, `GATEWAY_API_KEY_RATE_LIMIT`,
  `QUOTA_EDGE_WORKSPACE_METERING`, WS custom-domain lookup limits), the
  response-cache TTL (`GATEWAY_RESPONSE_CACHE_TTL`), and the RPC bulkhead
  (`GATEWAY_RPC_MAX_INFLIGHT`).
- `GATEWAY_TRUSTED_PROXIES` (CIDRs whose forwarding headers are believed; default loopback +
  private ranges), `GATEWAY_UPLOAD_MEMORY_BUDGET_MB` (default 256), `GATEWAY_WRITE_TIMEOUT`
  (default 180 s), `GATEWAY_SHUTDOWN_TIMEOUT` (drain on SIGTERM, default 30 s; keep the
  container's `stop_grace_period` above it).

A malformed value (`GATEWAY_RPC_MAX_INFLIGHT=abc`, `GATEWAY_DOCS_ENABLED=fales`) stops startup
with an error naming each variable instead of silently falling back to the default.

## Build & run

Go 1.26. A two-stage Dockerfile builds a static binary and ships it on a distroless
`nonroot` image (`EXPOSE 8080`; no shell, hence no container healthcheck — nginx uses
`depends_on: service_started`). `GET /health` is liveness (always 200 while the process
serves); `GET /ready` is readiness: 503 while the RabbitMQ transport is down and from the
moment shutdown starts draining. nginx reaches the gateway through a keepalive upstream
(`gateway_api`) that re-resolves its address in the background.

```bash
# Local
go run ./cmd/gateway

# Docker (default stack — there is no separate gateway profile)
docker compose up -d gateway
```

nginx fronts the gateway on `:80`. In dev, compose
publishes the gateway directly (`GATEWAY_HOST_PORT:8080`) for testing; in production only
nginx ingresses.

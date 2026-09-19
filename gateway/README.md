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

Every browser and API request enters through the gateway. Public reads are served from an
in-process cache or fanned out as RPC to workers; realtime updates are relayed from a
Redis bus to WebSocket subscribers; the frontend is reverse-proxied. The Python workers
expose **no HTTP** — the gateway is the only thing that
speaks HTTP to the outside world.

## Responsibilities

- **AuthN / AuthZ** — resolves the bearer credential (session JWT or API key) via
  `rpc.identity.validate_token` and injects the resulting RBAC payload into every downstream
  RPC as `data["identity"]`; WebSocket handshakes additionally validate a session JWT locally
  against the shared HS256 secret. See [Authentication](#authentication).
- **RPC dispatch** — typed request/reply RPC over RabbitMQ to `rpc.<service>.*` workers
  (`app`, `identity`, `tournament`, `parser`, `balancer`, `analytics`), with `reply_to` +
  `correlation_id`, an `x-deadline-ms` deadline, and a per-queue in-flight bulkhead
  (`GATEWAY_RPC_MAX_INFLIGHT`) that sheds with a 503 when a queue is saturated.
- **Reverse proxy** — proxies non-API requests (`/`) to the Next.js frontend.
- **Realtime hub** — a Redis→WebSocket hub at `/ws` and `/api/v1/realtime/ws`, replaying
  `realtime.workspace_event` rows from Postgres so reconnecting clients catch up.
- **Response cache** — an in-process, in-memory cache of anonymous public reads
  (`respcache`, default 30s TTL), invalidated by workers' Redis pub/sub.
- **Rate limiting** — per-IP token buckets (auth endpoints, anonymous API traffic, and the
  pre-handshake WS custom-domain Origin lookup). Per-API-key quotas are a different layer,
  enforced in `balancer-service` (see [Authentication](#authentication)).
- **API docs** — Scalar API-reference pages served from the gateway's own route tables.
- **Observability** — Prometheus metrics on `:9110` (top endpoints, active-users
  HyperLogLog, RPS/errors/latency) and OpenTelemetry tracing.

## Request flow

```
internet → Traefik (TLS) → nginx :80 → gateway :8080 →
    ├─ RPC over RabbitMQ → headless workers (rpc.app.* / rpc.identity.* / rpc.tournament.* / rpc.parser.* / rpc.balancer.* / rpc.analytics.*)
    ├─ reverse proxy → frontend (Next.js)
    └─ /ws + /api/v1/realtime/ws → Redis→WebSocket hub (replay from realtime.workspace_event)
```

## URL shape

Every route is `/api/v{n}/<domain>/...` — one version axis, always the second segment, and no
namespace beside it. `internal/apiver` normalises the inbound path onto that one table before
routing, which is why there is a single `/api/v1/` 404 guard in `cmd/gateway/main.go` instead
of one per namespace, and why `internal/respcache` and the OpenAPI specs only ever see
canonical paths.

| | |
|---|---|
| `/api/v1/...` | the contract: unwrapped, FastAPI-shaped JSON |
| `/api/v2/...` | the same paths, handlers and statuses; body is the RPC envelope (`internal/apierr`) |
| `/api/docs`, `/api/openapi*.json` | the generated reference — outside the version because it describes the versions |
| `/api/health` | the frontend container's probe, proxied through |
| `/bff/*` | the frontend's own cookie-authenticated endpoints, reverse-proxied to Next and never served here |

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
| Format | HS256 JWT | `aqt_sk_<public_id>_<secret>` |
| Issued by | `POST /api/v1/auth/login` (refreshed via `/api/v1/auth/refresh`) | `POST /api/v1/auth/api-keys` — the plaintext key is returned once and never again |
| Lifetime | short, tied to a session that can be revoked | until its `expires_at`, or until revoked |
| Reach | the caller's full RBAC — global roles/permissions and every workspace | one workspace, and only the permissions the key was scoped to |

```bash
curl -H "Authorization: Bearer aqt_sk_a1b2c3_..." https://<host>/api/v1/...
```

REST routes read the credential from the `Authorization` header only
(`internal/principal`, `internal/identity/handler.go:787`). The `owt_access_token` cookie
(legacy `aqt_access_token` as a fallback) and the `?token=` query parameter are read by
`internal/auth` and apply to WebSocket handshakes, not to REST authorization.

### How a credential becomes authorization

`internal/principal` calls `rpc.identity.validate_token` — the gateway is not an auth authority,
it only caches the verdict (30s TTL, concurrent misses for one credential collapsed by
singleflight). identity-svc is the single place that branches on credential type; both branches
return the same payload shape, which the gateway injects as `data["identity"]` and the workers
rehydrate into an `AuthUser`.

For an API key that payload is its **owner's RBAC, narrowed to the key**: one workspace entry
whose permissions are the key's scopes intersected with what the owner actually holds there, no
global permissions and no role names. Scopes are RBAC permission names (`team.create`,
`registration.approve`, the `admin.*` wildcard) from `backend/shared/rbac/catalog.py` — the same
vocabulary the endpoints are checked against — so a key is authorized by the ordinary permission
check, with no key-specific branch in any worker. A key can never outrank its owner, never
reaches a second workspace, and a key with no scopes can do nothing. See
[`../backend/ARCHITECTURE.md`](../backend/ARCHITECTURE.md) § "Two credentials, one branch".

### Session-only surfaces

`/api/v1/auth` operations that act on the caller's own account or session — logout, session list
and revoke, `/api/v1/auth/me`, password changes, and creating/updating/revoking API keys — resolve
the caller by JWT-decoding the bearer inside identity-svc, so an API key is rejected there with
401. A key can therefore neither mint another key nor extend a session.
`GET /api/v1/auth/api-keys/self` is the inverse: it describes the calling key, so it needs one.

WebSocket connections (`/ws`, `/api/v1/realtime/ws`) accept either credential, but a key
authenticates the socket only if it holds at least one grant in its workspace; a zero-scope key
connects anonymously and cannot subscribe to auth-gated topics.

### Rate limits

Anonymous traffic is metered per-IP (`internal/ratelimit`). API keys are metered
per key against `requests_per_minute` when the credential carries one, otherwise
`GATEWAY_API_KEY_RATE_LIMIT` (default 60/min). Balancer job quotas — `jobs_per_day`,
`concurrent_jobs`, `max_upload_bytes`, `max_players`, solver `config_policy` — live
in `balancer-service` (`src/core/security/api_key_limiter.py` / `api_key_policy.py`)
and are not identity defaults. Exceeding a quota returns 429 with `Retry-After`.

## Internal packages

Under `internal/`:

| Package | Role |
|---|---|
| `auth` | local JWT validation (WebSocket handshake, request logging, active-user metrics) |
| `principal` | credential resolution via `rpc.identity.validate_token` (session JWT or API key) + RBAC injection |
| `acl` | workspace membership authorization |
| `rpc` | RabbitMQ request-reply client (per-queue bulkhead, `x-deadline-ms`) |
| `edge` | typed route dispatcher |
| `proxy` | reverse proxy to HTTP upstreams |
| `respcache` | in-memory anonymous response cache |
| `cachecontrol` | cache-control policy |
| `ratelimit` | per-IP rate limiting |
| `ws` | WebSocket hub / handler / topic / conn-limit / origin |
| `events` | Redis `realtime:*` fan-out |
| `workspace` | custom-domain resolver + ACL over Postgres |
| `replay` | Postgres `realtime.workspace_event` replay |
| `metrics` | Prometheus + active-users HyperLogLog |
| `tracing` | OpenTelemetry |
| `openapi` / `apidocs` | Scalar API docs |
| `db` | pgx Postgres pool |

Per-domain route tables live under `internal/{tournament,app,parser,balancer,identity,analytics}`.

The gateway reads Postgres **read-only** (ACL / workspace membership, event replay,
custom-domain resolution), uses Redis for the realtime bus + cache-invalidation + active-user
HLL, and RabbitMQ for all RPC, events, and job queues.

## Configuration

Configuration is environment-driven via `internal/config`; see
[`../backend/env/gateway.env.example`](../backend/env/gateway.env.example) for the full,
annotated set. Highlights:

- `JWT_SECRET_KEY` — **required**, ≥ 32 chars (shared with the workers).
- `GATEWAY_PORT=8080`, `GATEWAY_METRICS_PORT=9110`.
- `RABBITMQ_URL`, `REDIS_URL`, `POSTGRES_*` / `DB_PGBOUNCER` (shared with the workers).
- Upstreams: `UPSTREAM_FRONTEND`, `UPSTREAM_PARSER`, `UPSTREAM_ANALYTICS`.
- WebSocket knobs (`WS_IDLE_TIMEOUT`, `WS_REPLAY_LIMIT`, `GATEWAY_WS_ALLOWED_ORIGINS`,
  per-IP conn/topic caps), rate-limit knobs (`GATEWAY_AUTH_RATE_LIMIT`,
  `GATEWAY_ANON_RATE_LIMIT`, WS custom-domain lookup limits), the response-cache TTL
  (`GATEWAY_RESPONSE_CACHE_TTL`), and the RPC bulkhead (`GATEWAY_RPC_MAX_INFLIGHT`).

## Build & run

Go 1.26. A two-stage Dockerfile builds a static binary and ships it on a distroless
`nonroot` image (`EXPOSE 8080`; no shell, hence no container healthcheck — nginx uses
`depends_on: service_started`).

```bash
# Local
go run ./cmd/gateway

# Docker (default stack — there is no separate gateway profile)
docker compose up -d gateway
```

nginx fronts the gateway on `:80`; TLS is terminated upstream by Traefik. In dev, compose
publishes the gateway directly (`GATEWAY_HOST_PORT:8080`) for testing; in production only
nginx ingresses.

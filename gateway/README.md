# Gateway

The Go gateway is OWT's **sole HTTP and WebSocket entry point**. It terminates HTTP,
validates JWTs locally, and translates REST routes into typed **request/reply RPC over
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

- **AuthN / AuthZ** — validates JWTs locally against the shared HS256 secret; RBAC-gated
  routes are revalidated via `rpc.identity.validate_token`, which injects the principal and
  permission set.
- **RPC dispatch** — typed request/reply RPC over RabbitMQ to `rpc.<service>.*` workers
  (`app`, `identity`, `tournament`, `parser`, `balancer`, `analytics`), with `reply_to` +
  `correlation_id`, an `x-deadline-ms` deadline, and a per-queue in-flight bulkhead
  (`GATEWAY_RPC_MAX_INFLIGHT`) that sheds with a 503 when a queue is saturated.
- **Reverse proxy** — proxies non-API requests (`/`) to the Next.js frontend.
- **Realtime hub** — a Redis→WebSocket hub at `/ws` and `/api/realtime/ws`, replaying
  `realtime.workspace_event` rows from Postgres so reconnecting clients catch up.
- **Response cache** — an in-process, in-memory cache of anonymous public reads
  (`respcache`, default 30s TTL), invalidated by workers' Redis pub/sub.
- **Rate limiting** — per-IP token buckets (auth endpoints, anonymous API traffic, and the
  pre-handshake WS custom-domain Origin lookup).
- **API docs** — Scalar API-reference pages served from the gateway's own route tables.
- **Observability** — Prometheus metrics on `:9110` (top endpoints, active-users
  HyperLogLog, RPS/errors/latency) and OpenTelemetry tracing.

## Request flow

```
internet → Traefik (TLS) → nginx :80 → gateway :8080 →
    ├─ RPC over RabbitMQ → headless workers (rpc.app.* / rpc.identity.* / rpc.tournament.* / rpc.parser.* / rpc.balancer.* / rpc.analytics.*)
    ├─ reverse proxy → frontend (Next.js)
    └─ /ws + /api/realtime/ws → Redis→WebSocket hub (replay from realtime.workspace_event)
```

## Internal packages

Under `internal/`:

| Package | Role |
|---|---|
| `auth` | local JWT validation |
| `principal` | RPC JWT validation (`rpc.identity.validate_token`) + RBAC injection |
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

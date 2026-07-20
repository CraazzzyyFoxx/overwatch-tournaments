# Tournament Service

The heart of OWT's tournament lifecycle — from registration through bracket generation, results,
and realtime updates.

- **Type:** headless FastStream (RabbitMQ) RPC worker + APScheduler + durable job consumers — no HTTP
  server of its own
- **Entry point:** `serve.py`
- **Run:** `faststream run serve:app`
- **Reached via:** the Go gateway (the sole HTTP entry point) under `/api/v1`

See [`../../docs/architecture.md`](../../docs/architecture.md) for the system overview.

## Responsibilities

The RPC surface is grouped as representative `rpc.tournament.*` methods served behind the gateway:

- **Reads** — typed read RPC for tournaments, encounters, teams, and standings.
- **Admin CRUD** — generic admin CRUD via the shared engine (`rpc.tournament.admin.*`).
- **Admin misc** — bespoke admin operations plus division-grid.
- **Registration admin** — registration management and status catalog.
- **Integrations** — Challonge (read / import / export / push / log) and Google Sheets sync /
  preview / suggest.
- **Stage admin** — stage / stage-item lifecycle.
- **Map veto / draft** — encounter map-pool veto administration.
- **Public** — public captain results and public registration.

## Realtime & messaging

- Tournament realtime events are published as `realtime.workspace_event` rows for gateway WebSocket
  fan-out (multi-replica broadcast through the gateway).
- A RabbitMQ `tournament_changed` consumer handles cache invalidation.
- A transactional outbox publishes captain/admin tournament changes, recalculations, encounter
  completion, registration approvals/rejections, and tournament state changes; the outbox sweeper
  runs in `serve.py` (~1s).

## Background jobs

All background processing runs in the single worker process:

- Bracket job consumer (`tournament_bracket_jobs`) and standings job consumer
  (`tournament_standings_jobs`), both on an isolated compute channel.
- Recalculation-event consumers (`tournament.changed` / `standings.invalidated`).
- APScheduler jobs: registration Google Sheets sync, Challonge active-tournament auto-sync, and
  tournament auto-transitions — a state machine running every ~30s via
  [`shared/core/tournament_state`](../shared/README.md).

## Dependencies

- **Postgres** — shared ORM (tournament and related schemas).
- **Redis** — realtime publish + cache invalidation.
- **RabbitMQ** — RPC transport, durable job queues, and the outbox/event exchanges.

## Configuration & environment

See `backend/env/tournament.env`, which inherits `backend/env/common.env`.

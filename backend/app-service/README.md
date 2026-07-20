# App Service

The core public read/data API for OWT — serves tournament, player, team, hero, map, gamemode,
match, achievement, and statistics data, plus workspace, user/metadata admin, and binary assets.

- **Type:** headless FastStream (RabbitMQ) RPC worker — no HTTP server of its own
- **Entry point:** `serve.py`
- **Run:** `faststream run serve:app`
- **Reached via:** the Go gateway under `/api/v1` (the gateway is the sole HTTP entry point and
  serves the API docs via Scalar)

See [`../../docs/architecture.md`](../../docs/architecture.md) for the system overview.

## Responsibilities

The RPC surface is grouped as representative `rpc.app.*` methods served behind the gateway:

- **Core reads** — read-optimized data for tournaments, players, teams, heroes, maps, gamemodes,
  matches, achievements, and statistics (bespoke aggregations/lookups plus a shared CRUD read engine
  for hero/map/gamemode/achievement get+list).
- **Workspaces** — workspace reads/writes and workspace-member management.
- **Admin CRUD** — user + game-metadata (hero/map/gamemode) admin CRUD, profile merge, avatar, and
  CSV import (relocated here from parser-service).
- **Binary assets** — icons, assets, and match-log served as binary/base64 payloads.
- **Caching** — Redis-backed response caching (cashews) to keep reads fast and reduce DB load; a
  `tournament_changed` RabbitMQ consumer performs cache invalidation.

## Dependencies

- **Postgres** — shared ORM (players / public / overwatch and related schemas).
- **Redis** — response cache (cashews) + cache-invalidation pub/sub.
- **RabbitMQ** — RPC transport and the `tournament_changed` invalidation consumer.
- **S3** — binary asset storage.

## Configuration & environment

See `backend/env/app.env`, which inherits `backend/env/common.env`. Shared ORM models come from
[`shared/`](../shared/README.md).

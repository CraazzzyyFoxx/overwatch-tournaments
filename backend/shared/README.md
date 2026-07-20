# Shared Library

This library holds the common database models and cross-service code used by every backend service
(`app-service`, `identity-service`, `tournament-service`, `parser-service`, `balancer-service`,
`analytics-service`, and the `discord-service` bot). It is the **single source of truth** for the ORM
layer — one SQLAlchemy `MetaData` defines every table for the whole platform.

For the system overview (RPC-worker + gateway model, request flow, data model) see
[`../../docs/architecture.md`](../../docs/architecture.md).

## Structure

```
shared/
├── core/            # db.py (Base, TimeStamp mixins, create_database() w/ pgBouncer),
│                    #   enums, config, pagination, errors, impact.py, tournament_state.py
├── models/          # ORM models, one subpackage per domain (see below)
├── repository/      # thin async CRUD (flush-only, no framework deps)
├── services/        # cross-service business logic (bracket engine, realtime publisher, …)
├── rpc/             # identity rehydrate, generic CRUD-over-RPC engine, deadline
├── messaging/       # RabbitMQ topology (DLX/DLQ, TTLs) + transactional outbox
├── tenancy/         # host → workspace resolution (subdomains + verified custom domains)
├── schemas/         # cross-service Pydantic (incl. events.py, realtime, settings)
├── rbac/            # grant-only PERMISSION_CATALOG + deny overlay bootstrap
├── clients/         # HTTP client, circuit breaker, S3
├── observability/   # logging, correlation-id, OTel, Sentry, health, metrics, broker factory
├── domain/          # shared domain helpers
├── balancer/        # shared balancer types/helpers
├── division_grid.py # runtime in-memory catalog
└── hero_catalog.py  # runtime in-memory catalog
```

### `core/`
`db.py` defines `Base`, the `TimeStamp` mixins, and `create_database()` (with pgBouncer support),
alongside `enums`, config, pagination, `errors`, `impact.py`, and `tournament_state.py` (the
tournament state-machine enum/logic).

### `models/<domain>/`
ORM models are partitioned into **Postgres schemas as domain boundaries**, all registered on a single
SQLAlchemy metadata (the single source of truth). Domains:

`achievements`, `analytics`, `balancer`, `catalog` (→ `overwatch` schema), `division_grid`,
`identity` (→ `auth` + `players`), `ingestion` (→ `log_processing`), `matches`, `platform`,
`preferences`, `ranks` (→ `overwatch_rank`), `registration` (tables in the `balancer` schema),
`tenancy`, and `tournament`.

### Other subpackages
- **`repository/`** — thin async CRUD, flush-only, no framework dependencies. Governed by
  [`../docs/repository-boundaries.md`](../docs/repository-boundaries.md).
- **`services/`** — cross-service business logic: bracket engine, realtime publisher,
  division-grid access/normalization, tournament visibility, Challonge/stage refs.
- **`rpc/`** — `identity` (rehydrate `AuthUser` from the gateway RBAC payload, no DB), `crud`
  (config-driven generic CRUD-over-RPC engine), `deadline`.
- **`messaging/`** — RabbitMQ topology (DLX/DLQ per queue, TTLs) plus the transactional outbox
  helpers (`public.event_outbox`).
- **`tenancy/`** — host → workspace resolution: subdomains and verified custom domains.
- **`schemas/`** — cross-service Pydantic models, including `events.py`, realtime, and settings.
- **`rbac/`** — grant-only `PERMISSION_CATALOG` + workspace system roles + `user_permission_deny`
  overlay bootstrap.
- **`clients/`** — HTTP client, circuit breaker, S3.
- **`observability/`** — Loguru logging, correlation-id, OTel tracing, Sentry, health checks, worker
  metrics, and the RabbitMQ broker factory.
- **`domain/`**, **`balancer/`**, and the `division_grid.py` / `hero_catalog.py` runtime catalogs.

## Usage

Services re-export the shared models and core helpers through their own `src/models` and `src/core`
packages, so application code imports them locally:

```python
from src import models

user = models.User(name="example")
tournament = models.Tournament(name="Tournament #1")
```

Base classes and enums are exposed through each service's `src.core`:

```python
from src.core import db, enums
```

## Important

- **Do not edit** the per-service `src/models/` files directly — they are proxies for `shared/models/`.
- All database model changes must be made in `shared/models/`.
- Shared enums belong in `shared/core/enums.py`.
- Service-specific enums (for example, `RouteTag`) stay in that service's own `src/core/enums.py`.

## Benefits

1. **Single source of truth** — models are defined in one place, on one SQLAlchemy metadata.
2. **Consistency** — every service uses identical model definitions.
3. **Easier maintenance** — model changes are made only in `shared`.
4. **Code reuse** — common logic is available to all services.

## Layering & status

The layered service hierarchy (routes → flows, private `_mappers`/`_repositories`) is enforced via
import-linter and documented in [`../docs/architecture/layering.md`](../docs/architecture/layering.md).
`shared/` is still a **monolithic kernel** — the strategic split (P3-D) is tracked in
[`../docs/architecture/p3-strategic-refactors.md`](../docs/architecture/p3-strategic-refactors.md).

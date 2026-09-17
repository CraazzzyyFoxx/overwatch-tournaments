# Shared kernel

`shared/` is a library, not a service. It is a uv workspace member (`backend/pyproject.toml`:
`members = [...]`, `shared = { workspace = true }`), installed editable into the single venv every
backend process runs from, so `import shared.*` resolves identically in every service and in
`backend/migrations/`.

Two rules make it the single source of truth and keep it from becoming another service:

1. **One metadata.** Every table in the platform is declared on `shared.core.db.Base.metadata`.
   No service declares a `__tablename__`, and no service ships migrations — there is exactly one
   Alembic project, `backend/migrations/`.
2. **The dependency arrow points one way.** Services import `shared`; `shared` imports no service.
   There are currently zero `from src.…` imports anywhere under `shared/`, and that is the
   invariant, not an accident. Code belongs here **iff two or more services already need it** (not
   "might") and it can be written without reaching into any service's `src/`.

System overview (processes, RabbitMQ, gateway, deployment):
[`../../docs/architecture.md`](../../docs/architecture.md).

## What lives here

- The ORM — every table, on one metadata (`models/`).
- CRUD repositories over those tables (`repository/`).
- Session-taking logic two or more services already call (`services/`): bracket advancement,
  admission, realtime publishing, workspace scoping, distributed locks, subscriptions, audit,
  notifications — `services/notifications.py:notify()` is the one write point for a
  `notification` row. It validates the payload against the kind's registered schema, calls
  `session.add` and returns the row, so the caller's transaction owns the commit and a
  rolled-back mutation notifies nobody; the realtime signal is published after that commit,
  best-effort. Same contract as `record_audit` beside it. Producers pass `source_workspace_id` —
  the tenant whose activity caused the row, set for personal notifications too — which is what
  the workspace operator screen scopes and retires on.
- Pure algorithms and value types two or more services already call (`domain/`).
- Wire contracts that cross a service boundary (`schemas/`), above all the event payloads in
  `schemas/events.py`.
- Transport plumbing every worker reuses (`rpc/`, `messaging/`, `observability/broker.py`): the
  gateway envelope, the deadline middleware, queue/exchange/DLQ names, the transactional outbox.
- Process wiring that is identical everywhere: `BaseServiceSettings`, the engine factory, logging,
  correlation ids, OTel, Sentry, health checks, worker metrics, the resilient HTTP client and its
  circuit breaker, S3, the RBAC permission catalog, host → workspace resolution.
- Test scaffolding every suite needs (`testing/`).

## What must not live here

- **Service-specific business logic.** One consumer means it is that service's `src/services/` or
  `src/domain/`. A second consumer that does not exist yet is not a second consumer.
- **Anything importing a service package.** `from src.core import config` inside `shared/` inverts
  the dependency direction and couples the kernel to one service's deployment. A shared module that
  needs one service's settings *is* that service's module; the second consumer calls it over RPC.
- **A service's settings object, read implicitly.** Per-service inputs (a Redis URL, a feature flag,
  a TTL) arrive as arguments or as plain constants. `balancer_registration_statuses.py` spells this
  out: its cache TTL is a hardcoded constant precisely because `shared` may not read any single
  service's config.
- **HTTP framework code.** Nothing here imports FastAPI. `shared.core.errors.BaseAPIException`
  (imported as `HTTPException` at call sites) and `shared.core.http_status` are the replacements;
  `starlette` is a dependency only for ASGI middleware and multipart reconstruction.
- **Wire contracts and enums with one sender.** A schema only one service emits stays in its
  `src/schemas/`; an enum only one service reads stays in its `src/core/enums.py`. The reverse also
  applies, and `RouteTag` is the worked example: three services held a byte-identical 14-member
  copy, so it moved *into* `shared.core.enums`, and the services that use it re-export it from
  their own `src/core/enums.py`.

## Subpackages

| Package | Belongs in it | Does not |
| --- | --- | --- |
| `core/` | Process-wide primitives: `db.py` (`Base`, timestamp mixins, `create_database()` with pgBouncer handling), `config.py` (`BaseServiceSettings`), `enums.py`, `errors.py`, `http_status.py`, `pagination.py`, `utils.py`, `proxy.py`, and pure rule modules (`tournament_state.py`, `draft_state.py`, `impact.py`, `social.py`) | Anything that takes an `AsyncSession` or runs a query — a `core/` module that grew a query is a `services/` module wearing the wrong name |
| `models/` | SQLAlchemy models only, one subpackage per domain (see below) | Queries, business methods, Pydantic |
| `repository/` | `BaseRepository[Model]` plus one concrete repository per model: CRUD SQL and named locking reads | Analytical SQL (CTEs, windows, leaderboards, recalculation) — that lives in a `queries.py`/service class |
| `services/` | Session-taking orchestration with two or more service consumers | Anything a single service uses, or anything needing a service's settings |
| `domain/` | Pure logic with two or more consumers: roster shapes, sub-role vocabulary, invite tokens, OW ladder, division ranks | `AsyncSession`, `await`, repository imports |
| `schemas/` | Cross-service Pydantic: `events.py`, `realtime.py`, `rpc.py` (the envelope shape), `settings.py` (the typed JSON shape of every `Settings` row), catalog/challonge/healthcheck contracts | Wire contracts only one service emits |
| `rpc/` | The typed-RPC toolkit every worker reuses — see below | Per-service handlers or permission gates |
| `messaging/` | Queue/exchange/DLQ name constants, `declare_dead_letter_queue` topology, the transactional outbox (`enqueue_outbox_event` / `publish_pending_outbox_events`), `request_dict` for synchronous cross-service calls | String literals at call sites, `broker.publish` from inside a request |
| `jobs/` | The job runtime: `JobSpec`/`Status` lifecycle (`created → running → succeeded\|failed`, with `Retry` back to `created`), the ORM job store, the Redis metadata store, injectable concurrency policies (`Unlimited`, `OneActive`, `SlotLimited`) | The jobs themselves — a service owns its handlers |
| `quota/` | The one quota gate: policy resolution over the `quota` schema (plans, per-operation cost, the two override tables), the Redis counters and lease sets behind `charge`/`lease`/`release`, and the admin writes those tables take. A service calls it; it owns every number | Deciding *which* operations cost something — that is a `charge()` line at the call site, plus a `quota.operation` row |
| `rbac/` | The grant-only `PERMISSION_CATALOG`, workspace system roles, scope normalization and legacy aliases, and the bootstrap that reconciles them plus the `user_permission_deny` overlay | Per-route authorization decisions; those are `rpc/` gates |
| `tenancy/` | Host → workspace hostname rules: the platform zone, reserved subdomains, label validation, custom-domain normalization | The workspace lookup queries (those are `rbac/workspace_lookup.py` and `services/workspace_scope.py`) |
| `observability/` | Loguru setup, correlation ids, OTel tracing and SQLAlchemy instrumentation, Sentry, dependency health checks, worker metrics (`start_worker_metrics_server`), and `make_rabbit_broker` — which always prepends `DeadlineDropMiddleware` to a broker's middleware stack | Business metrics; those are counters next to the code that moves them |
| `clients/` | External-API clients with two or more consumers: `ChallongeClient`, `S3Client`, `ResilientHttpClient`, `CircuitBreaker` | Constructing them from settings — that is one line in the service's `src/clients/<name>.py` |
| `balancer/` | The `BalancerAlgorithm` protocol and its IO types (`PlayerInput`, `RoleMask`, `BalanceOutput`, …), so a caller can depend on a balancer without importing one | Any concrete balancing algorithm |
| `testing/` | pytest scaffolding every service's `conftest.py` imports: dotenv load (local `.env` then committed `testing/test.env`) so `Settings()` constructs, cashews backend setup, a real-Postgres session that probes with a 2s timeout (or starts `docker-compose.test.yml` on the dummy DSN), skips cleanly, and refuses production databases, factories, SQLite dialect shims | Service-specific fixtures |
| `tests/` | This package's own suite (84 test modules) covering shared services, repositories and domain logic | — |

Five flat modules sit at the package root and predate the subpackage split:
`division_grid.py` and `hero_catalog.py` (runtime catalogs), `catalog_aliases.py` (alias
normalization shared by three admin writers and the alias-attach RPC),
`balancer_registration_statuses.py` (the workspace status-meta map, cached), and
`balancer_subrole_catalog.py` — which is explicitly a one-line facade over
`PlayerSubRoleService.catalog_for_workspace`, kept so callers do not move. New code of this shape
goes into `services/` or `domain/`, not the root.

### `rpc/`

Everything a typed-RPC worker needs that is not its own domain:

- `common.py` — the `{ok, data, error}` envelope (`envelope(...)` runs the handler inside a DB
  session, maps `BaseAPIException.status_code` through `status_to_code`, flattens pydantic
  `ValidationError` into per-field `details`, and turns anything else into `internal`), plus the
  param decoding for the gateway-forwarded body: `q`/`q1`/`qbool`, `payload`, `require_id`,
  `require_query_int`, `require_path_int`, `identity_user_id`, `dump`, and the actor helpers
  (`actor`, `optional_actor`, `require_active`, `require_permission`, `require_superuser`).
- `deadline.py` — `DeadlineDropMiddleware`. The gateway stamps each publish with `x-deadline-ms`;
  RabbitMQ's per-message TTL drops what is still queued, this drops what was already prefetched
  when it expired (500 ms slack for clock skew), acks it, and counts it in
  `rpc_stale_dropped_total`. Messages without the header pass through, so it is safe broker-wide.
- `query.py` — `build_query_model`, which rebuilds a route's query-params model from the gateway's
  `{key: [values]}` shape, including resolving `Field(Query(default=…))` markers for absent fields.
- `identity.py` — rehydrate an `AuthUser` from the gateway-injected RBAC payload, no DB round-trip.
- `crud.py` — a config-driven generic CRUD-over-RPC engine: a service declares `EntityConfig` rows
  and wires the generic subscribers under its own queue prefix instead of hand-writing uniform
  handlers.
- `openapi.py` — the `Op`/`QueryParam` types a service's `OPERATIONS` table is built from.
  `scripts/export_openapi_schemas.py` turns those tables into the JSON-Schema manifest the gateway
  embeds and serves at `/api/docs`, which is why the module imports nothing heavy: the export runs
  with no broker and no DB.

This is why every service's `src/rpc/_common.py` is a re-export, not an implementation: it imports
the names above from `shared.rpc.common`, binds `envelope` to its own service name with
`functools.partial`, and adds only the gates that are genuinely local (`app-service` adds exactly
one, `gate_tournament`).

## Models and migrations

`models/` is partitioned into domain packages, each mapping to one or more Postgres schemas.
`models/__init__.py` star-imports all of them, so importing the package loads every module and
string-based relationship resolution and `configure_mappers()` work against the one metadata.

The domain packages are exactly the sections of
[`../../docs/database_erd.md`](../../docs/database_erd.md), which is generated from
`Base.metadata` by `backend/scripts/export_erd.py` and CI-gated with `--check` in
`.github/workflows/lint-backend.yml`:

`identity` (`auth`, `players`), `tenancy` (`public`), `member_rank` (`balancer`), `catalog`
(`overwatch`), `division_grid` (`public`), `ranks` (`overwatch_rank`), `tournament` (`tournament`,
`casual`), `registration` (`balancer`), `balancer` (`balancer`), `custom_game` (`balancer`),
`casual` (`casual`), `matches` (`matches`), `ingestion` (`log_processing`), `achievements`
(`achievements`), `analytics` (`analytics`), `subscriptions` (`subscriptions`), `preferences`
(`players`, `tournament`), `platform` (`public`, `realtime`).

Migrations live only in `backend/migrations/` (config: `backend/alembic.ini`); its `env.py` imports
`shared.core.db` and `shared.models` and diffs against that same metadata. Baseline revision is
`initial_v6` — see [`../migrations/README`](../migrations/README) for the fresh-database vs.
already-migrated procedure.

**What one metadata buys.** A single migration ordering for the whole platform, so no service can
half-apply another's schema change. Relationships and joins that span domains, because every mapper
is registered in every process. Cross-service reads with no API call. And a data-model document
that cannot silently drift, because it is generated from the same metadata the migrations diff
against.

**What it costs.** Every table change is a change to a package every worker process imports, so they
redeploy against it together — this is the coupling P3-D proposes to break and which is currently
on hold ([`../docs/architecture/p3-strategic-refactors.md`](../docs/architecture/p3-strategic-refactors.md)).
Nothing at the database level stops one service writing another's tables; the rule — read freely
through `shared`, write only what your service owns — is convention, enforced by review, not by
Postgres. And because service images do not ship Alembic, migrations are deployed separately from
the services that need them.

## Using it from a service

`shared` is a workspace dependency (`dependencies = ["shared", …]` in each service's
`pyproject.toml`), so nothing needs to be published or pinned. Application code reaches it through
thin per-service facades:

```python
from src import models          # curated re-export of shared.models
from src.core import db, enums  # re-exports over shared.core.db / shared.core.enums

user = models.User(name="example")
tournament = models.Tournament(name="Tournament #1", slug="tournament-1")
```

- `src/models*` is a re-export facade over `shared.models` and declares no table of its own. Adding
  or changing a column means editing `shared/models/<domain>/` and adding an Alembic revision — never
  editing the facade.
- `src/core/enums.py` star-re-exports `shared.core.enums`; `src/core/db.py` re-exports `Base` and
  the timestamp mixins and adds only what is per-process — the engine and `async_session_maker`
  built from *this* service's settings via `create_database_from_settings`. `src/core/__init__.py`
  re-exports `errors`, `pagination` and `utils` so `from src.core import …` keeps working.
- A service's `Settings` extends `shared.core.config.BaseServiceSettings`.
- A service's `tests/conftest.py` imports its env, cache and database fixtures from
  `shared.testing`; do not re-implement them per test module.

## Layering and boundaries

- The `rpc → services → domain → repository → models` stack every service is built from, and the
  rule for which layer new code belongs in, is
  [`../ARCHITECTURE.md`](../ARCHITECTURE.md). That document also covers session/transaction
  ownership, the outbox, realtime patches, caching and error mapping.
- Repositories take an `AsyncSession`, return ORM rows or row tuples, **flush but never commit**,
  and import no Pydantic schema, cache client, outbox publisher or service settings. The full rule
  set, the two ratcheted exemption lists and why they exist:
  [`../docs/repository-boundaries.md`](../docs/repository-boundaries.md).
- `app-service` additionally enforces a five-layer hierarchy *inside* its own `services/` package
  with import-linter (`backend/app-service/.importlinter`; `analytics-service` has three flatter
  contracts of the same kind). Run from `backend/`:
  `uv run lint-imports --config app-service/.importlinter`. The layers, the grandfathered
  violations and how to place a new domain:
  [`../docs/architecture/layering.md`](../docs/architecture/layering.md). Note that these contracts
  are run locally, not in CI.
- `shared/` itself has no import-linter contract. Its boundary is the one stated at the top: no
  module here imports a service, and code arrives only when a second service already needs it.

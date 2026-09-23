# Backend code architecture: what goes where, in every service

This is the code-level counterpart to [`../docs/architecture.md`](../docs/architecture.md).
That document describes the *system*: processes, RabbitMQ, Postgres, deployment topology.
This one describes what happens **inside one service's `src/`** — the layers every domain
(`hero`, `draft`, `registration`, `token_validation`, …) is built from, and the rule for
which layer new code belongs in.

It is not a proposal. It is a description of the pattern `identity-service` has followed
since it was written, that `app-service` (2026-08-20), `balancer-service` (2026-08-21),
`parser-service` (2026-08-21), `tournament-service` (2026-08-22) and
`analytics-service` (2026-08-24) were converted to. Every new domain, in every service,
follows it. Case studies with before/after numbers live in
`docs/plans/2026-08-20-app-service-oop-repositories.md`,
`docs/plans/2026-08-21-balancer-service-oop-repositories.md`,
`docs/plans/2026-08-21-parser-service-oop-repositories.md`,
`docs/plans/2026-08-22-tournament-service-oop-repositories.md` and
`docs/plans/2026-08-24-analytics-service-oop-repositories.md`.

## The five layers

```
serve.py                          FastStream worker entrypoint. Registers every rpc/*.py
                                   module's subscribers on the broker. No HTTP, no business logic.
  ↓
src/rpc/<domain>.py                TRANSPORT. register(broker, logger); one @broker.subscriber
                                   per "rpc.<service>.<domain>.<method>" topic. Decodes the
                                   envelope, resolves the actor/workspace, gates permissions,
                                   calls exactly ONE service method, wraps the result in
                                   c.envelope(...). Owns zero SQL, zero business rules.
  ↓
src/services/<domain>/*.py         ORCHESTRATION. One class + one exported module-level
                                   singleton per cohesive responsibility. Takes `session:
                                   AsyncSession` as the first parameter of every method — never
                                   owns or creates one. Talks to repositories and to domain/,
                                   maps ORM rows to schemas, applies cache decorators, decides
                                   commit boundaries are the CALLER's job (see "Session and
                                   transaction ownership" below).
  ↓
src/domain/**/*.py                 PURE LOGIC. Dataclasses, algorithms, validation rules. Zero
  (or shared/domain/**/*.py for    `AsyncSession`, zero `await`, zero `asyncio`. Safe to call
  logic shared across services)    from a synchronous test with no DB fixture and no
                                   `asyncio.run`. See "The domain/ boundary, precisely" below.
  ↓
shared.repository.*                CRUD. `BaseRepository[Model]` + concrete repos
                                   (`HeroRepository`, `DraftPickRepository`, …). Accepts a
                                   session, returns ORM rows or row tuples. Never imports
                                   Pydantic, FastAPI/FastStream, cache clients, or outbox
                                   publishers. Write methods flush only — see
                                   `backend/docs/repository-boundaries.md`.
  ↓
shared.models.*                    ORM. SQLAlchemy models, one shared `MetaData`, the single
                                   source of truth for the schema (`backend/migrations/`). Every
                                   table lives here; a service's `src/models*` is a curated
                                   re-export facade over `shared.models` (zero `__tablename__` in
                                   all seven services as of this writing) and never declares a
                                   table of its own.
```

`src/schemas/*.py` sits beside this stack, not inside it: Pydantic wire contracts for the RPC
boundary (and OpenAPI docs generation). Schemas convert *at* the boundary
(`schemas.HeroRead.model_validate(hero, from_attributes=True)` in a service's `to_read`, or
`DraftFeasibilityResponse.model_validate(report)` in an rpc handler) — they are never passed
down into `domain/` or `shared.repository`, and `domain/`'s own dataclasses are never redefined
as schemas just to "have one type." Two vocabularies exist on purpose: `schemas` is what the
wire carries; `domain` is what the algorithm thinks in. See
`docs/plans/2026-08-21-balancer-service-oop-repositories.md` §6 for the fuller reasoning
(`DraftSnapshot`/`DraftResult` hold live ORM rows and would force
`arbitrary_types_allowed`, defeating Pydantic validation, if merged into `schemas`).

`src/clients/*.py` sits beside the stack too, for the same reason schemas do: a wrapper
around a *shared* external-API client (`shared.clients.ChallongeClient`, a bespoke
`OverFastCatalogClient`, ...) has no orchestration to inject collaborators into and no pure
algorithm to test — it isn't a `service` and isn't `domain`. It gets `src/clients/<name>.py`,
holding exactly one line of substance: construct the instance from this service's settings,
export it.

```python
# src/clients/challonge.py
challonge_client = ChallongeClient.from_settings(config.settings)
```

Callers import the instance and call its real bound methods directly —
`challonge_client.fetch_tournament(...)`. **Do not** rebind its methods as module-level names
(`fetch_tournament = challonge_client.fetch_tournament`, `fetch_participants = ...`, one line
per method): that was `parser-service`'s original shape for this exact file
(`services/challonge/service.py`, converted 2026-08-21), and it bought nothing over exposing
the instance itself — one indirection that reads like a `service.py` (misleading: no
orchestration lives there) for the price of an `__all__` entry updated by hand every time the
wrapped client grows a method. Nothing in this document flagged that shape as wrong at the
time — it matched an identical pre-existing file in `tournament-service`, so it was carried
forward as "established precedent" during the parser-service conversion instead of being
questioned. That second copy is gone too: `tournament-service`'s
`services/challonge/service.py` was deleted on 2026-08-22 in favour of
`src/clients/challonge.py`, so no instance of the shape survives — which is the point of
writing the rule down rather than letting the next reader infer it from whatever exists.

Two placement traps this avoids:

1. Do not put it under `src/services/<domain>/` when the "domain" is nothing but a client —
   that misleads a reader into expecting orchestration/session-handling that isn't there
   (parser-service's `services/challonge/service.py` did this).
2. Do not put it under `src/rpc/` (e.g. a `rpc/_clients.py` grab-bag of process-global clients)
   if any `services/` code needs to import it — a service reaching into the transport package
   inverts the `rpc → services` dependency direction. `app-service`'s original `rpc/_clients.py`
   moved to `core/clients.py` for exactly this reason (§2.5 of
   `docs/plans/2026-08-20-app-service-oop-repositories.md`), and `parser-service`'s did the same
   once `services/subscription_collection/scheduler.py` started importing `realtime_redis` from
   it. Both live in `core/clients.py` now; a new `rpc/_clients.py` is the mistake this names.

`src/core/*.py` is the third thing beside the stack: process-wide wiring, not layers.
`config.py` (pydantic settings), `db.py` (engine + `async_session_maker`), `caching.py`,
`clients.py`, `broker.py`, `redis.py`, `enums.py`, `workspace.py`. Any layer may import from
`core`; `core` imports from no layer — that is the whole rule, and it is why `rpc/_clients.py`
had to become `core/clients.py` (above). A service with a `core/auth.py`/`core/metrics.py`
beyond this set is fine; a `core/` module that grew a query or a business rule is a
`services/` file wearing the wrong name.

## Where does this go

| The code… | goes in |
| --- | --- |
| decodes an envelope, gates permission, calls one service method | `src/rpc/<domain>.py` |
| awaits a session/repository, orders several steps, maps rows to schemas | `src/services/<domain>/*.py` |
| is pure: no `session`, no `await` | `src/domain/` (one service) or `shared/domain/` (two+) |
| awaits a session and two+ services need it | `shared/services/` |
| is CRUD SQL for one model | `shared/repository/<x>.py` |
| is an analytical query (CTE, window fn, leaderboard) | the domain's `queries.py` / service class |
| is a wire contract | `src/schemas/` (or `shared/schemas/` if two+ services send it) |
| is a process-wide singleton or setting | `src/core/` |
| is a table | `shared/models/` + an Alembic revision in `backend/migrations/` |
| is a fact other services must learn about | an event in `shared/schemas/events.py`, sent via the outbox |

## `shared/` vs `src/`, for session-taking code

`shared/domain/` is the easy half (pure logic, two+ consumers). The harder half is
`shared/services/` — ~50 modules that *do* take an `AsyncSession`: `bracket/`, `encounter/`,
`team_export/`, `workspace_scope`, `registration_window`, `subscription_*`, `audit`,
`distributed_lock`, `realtime_publisher`. Something belongs there **iff two or more services
already need it** (not "might"), and it can be written without importing any service's `src.*`.
Per-service inputs — a Redis URL, a feature flag, a settings object — arrive as arguments, never
as `from src.core import config`. A `shared/services/` module that needs one service's settings
is that service's `services/` file, and the second consumer should call it over RPC.

## Concrete shape of a layer

**`rpc/<domain>.py`** (`app-service/src/rpc/heroes.py`):

```python
def register(broker: Any, logger: Any) -> None:
    @broker.subscriber("rpc.app.heroes.leaderboard")
    async def _leaderboard(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            await c.gate_tournament(session, data, c.q1(data, "tournament_id", int))
            ws = await resolve_workspace_context(session, c.q1(data, "workspace_id", int))
            return await hero_service.get_hero_leaderboard(session, hero_id=..., grid=ws.grid)

        return await c.envelope(logger, "heroes.leaderboard", op, session_factory=_SF)
```

**`services/<domain>/service.py`** (`app-service/src/services/hero/service.py`):

```python
class HeroService:
    def __init__(self, *, queries: HeroQueries = hero_queries, repo: HeroRepository = HeroRepository()) -> None:
        self.queries = queries
        self.repo = repo

    async def get_hero_leaderboard(self, session: AsyncSession, hero_id: int, ...) -> Paginated[...]:
        rows, total = await self.queries.get_hero_leaderboard(session, hero_id=hero_id, ...)
        ...

heroes = HeroService()
```

`queries.py` is the same shape, split out only when a domain's analytical SQL (leaderboards,
window functions, recalculation queries — anything `repository-boundaries.md` bans from a
CRUD repository) is large enough to want its own class, its own singleton, and its own
`__all__`. Small domains keep everything in one `service.py`; large ones (`balancer-service`'s
`draft` package) split by *feature*, not by CRUD-vs-analytics — `lifecycle.py`,
`selection.py`, `board.py`, `role_edit.py`, `export.py`, `clock.py` are six classes, six
singletons, one shared injected `feasibility_service`.

**`domain/<x>.py`** (`balancer-service/src/domain/draft/rules.py`):

```python
def resolve_pick_slot(shape: RosterShape, counts: Mapping[str, int], player: DraftPlayer, target_role: HeroClass | None) -> SlotDecision:
    if not role_is_legal(player, target_role if shape.has_role_slots else None):
        raise _err("illegal_role", ...)
    ...
```

No `session`, no `await`, no repository import. `services/draft/selection.py`'s
`DraftSelectionService.select` calls `rules.resolve_pick_slot(...)` synchronously, in the
middle of an otherwise-async method.

## The `domain/` boundary, precisely

A function or dataclass belongs in `domain/` (per-service `src/domain/` or, when the logic is
useful to more than one service, `shared/domain/` — e.g. `shared/domain/roster_shape.py`,
`invite_token.py`, `team_roster.py`, consumed by both `balancer-service` and
`tournament-service`) **iff it never touches `AsyncSession`, never awaits, and never runs on
the event loop**. Concretely:

- Value types (dataclasses/`NamedTuple`s the algorithm passes around) that don't need pydantic
  validation because nothing external ever constructs one directly.
- Deterministic algorithms: bipartite matching, genetic/NSGA balancing, feasibility analysis,
  role/rank scoring, seat ordering, slot-vocabulary rules.
- Validation functions that raise a domain error from in-memory state (`validate_draft_rounds`,
  `role_is_legal`) — they take the already-loaded rows as arguments; loading those rows is the
  service's job, not theirs.

Everything else — anything that calls `session.execute`, `session.get`, `session.add`, awaits a
repository method, or runs `asyncio.to_thread` to offload the pure algorithm above off the event
loop — is a method on a `services/<domain>/*.py` class, never a `domain/` function. `domain/`
code is exactly what you can unit-test with plain constructed objects and no `pytest.mark.db`,
no `AsyncSession` mock, no `asyncio.run`.

Do not force a class onto pure code just to "match the pattern": a `domain/` module with a
curated `__all__` and direct imports from services/tests **is** the correct shape for that code.
Forcing a singleton class onto a pure algorithm is the "pointless split" the app-service
refactor's own correction pass explicitly walked back — see §6-7 of
`docs/plans/2026-08-20-app-service-oop-repositories.md`.

## Session and transaction ownership

- `AsyncSession` is always a parameter, threaded through every layer below `rpc/`. Nothing
  below `rpc/` ever calls `db.async_session_maker()` or opens its own session.
- Repository write methods (`create`, `update`, `delete`) **flush only**. `commit()`/`rollback()`
  are decided by the caller that owns the unit-of-work — usually the `rpc/*.py` handler, inside
  or just after `c.envelope`'s `op(session)` callback (see `rpc/draft.py`'s explicit
  `await session.commit()` after every mutating handler).
- A service method that needs a read-then-write invariant to hold (the pick-selection race, a
  locked re-seed) does the locking read itself via a repository's `get_for_update`/
  `with_for_update(skip_locked=True)` method — never a bare `sa.select(...).with_for_update()`
  inlined in the service, and never generalized into `BaseRepository.get(..., lock=True)`; each
  locking shape is preserved verbatim in its own named repository method.

## Events leave through the outbox, never `broker.publish`

A service never publishes to RabbitMQ from inside a request. It calls
`shared.messaging.outbox.enqueue_outbox_event(session, event, exchange=..., routing_key=...)`
in the *same transaction* as the mutation, so "the row changed" and "the world was told" commit
or roll back together. `serve.py`'s scheduler drains the table with
`publish_pending_outbox_events` (`tournament-service/serve.py`'s `event_outbox_drain`), retrying
failures with exponential backoff capped at 300s.

- Event payloads are Pydantic models in `shared/schemas/events.py` and **must** carry
  `event_id` — `enqueue_outbox_event` raises `ValueError` without one. That id is the
  consumer's idempotency key; every consumer must tolerate redelivery.
- Exchange/queue/DLQ names are constants in `shared/messaging/config.py`, declared with
  `shared.messaging.topology.declare_dead_letter_queue`. No string literals at call sites.
- Exactly one service owns each queue (`TOURNAMENT_CHANGED_APP_QUEUE` → app-service's
  `services/tournament_events.py`). Two consumers of one queue is a bug, not fan-out; fan-out
  is two queues bound to the same exchange.
- Synchronous cross-service calls use `shared.messaging.request_dict(broker, payload, queue)`
  and nothing else — `broker.request()` returns a message, not a body, and mistaking the two
  is how the Discord entity endpoints shipped empty lists to production.

## Realtime patches are part of the transaction

`shared/services/realtime_publisher.publish_event` / `publish_patch` persist a `WorkspaceEvent`
row on the caller's session and *then* push to Redis. Call them inside the mutation's
transaction so the persisted event id orders with the write; Redis failures are swallowed on
purpose (clients self-heal by refetching from the ordered event log). Topics come from
`shared/services/realtime_topics.py` — never a formatted string at the call site — and a patch
event names the client-cache `resource` it mutates so the frontend folds the delta instead of
refetching.

## Cache

Cache decorators live on `services/` methods, never on a repository or a `domain/` function.
Backends are registered per key-prefix in `src/core/caching.py`: cashews has no default backend
and raises `NotConfiguredError` for an unroutable key, so **every** entrypoint that can read,
write, or invalidate the cache calls `configure_cache()` before the first subscriber runs
(`app-service/serve.py`). The prefix tuple in `core/caching.py` is the single source for
invalidation patterns — an invalidation consumer generates its patterns from it rather than
re-typing them.

## Errors

Nothing below `rpc/` imports FastAPI. Services and domain code raise
`shared.core.errors.BaseAPIException`, imported as `HTTPException`
(`from shared.core.errors import BaseAPIException as HTTPException`) so raise/except sites read
like the FastAPI ones they replaced. `c.envelope` maps `status_code` through `status_to_code`
and flattens `detail` into the `{ok, data, error}` envelope; unhandled exceptions become
`internal`. Error codes are contract, not prose: `backend/tests/test_rpc_error_code_parity.py`
keeps them in step with the gateway.

## Cross-service data access

All services share one Postgres and one `MetaData`, so nothing *stops* a service from selecting
another's tables. The rule is: **read freely through `shared/repository` and `shared/services`;
write only what your service owns.** A write to a table another service owns goes through that
service — `request_dict` for a command that needs an answer, an outbox event when it doesn't.
Direct cross-service writes are the failure mode this convention exists to prevent, because the
DB will not catch them and neither will a test.

## Class + singleton, not a bag of functions, not a DI container

Every `services/<domain>/*.py` file exports exactly one class and one instance of it, built with
its collaborators' own singleton defaults:

```python
class DraftSelectionService:
    def __init__(self, *, teams_repo: DraftTeamRepository = DraftTeamRepository(), feasibility: DraftFeasibilityService = feasibility_service) -> None:
        ...

selection_service = DraftSelectionService()
```

This buys constructor-injectable collaborators for tests (`DraftSelectionService(teams_repo=fake)`)
without a DI framework — the default argument *is* the production wiring, and a test overriding
one keyword is the entire seam. Do not add a container, a factory registry, or a `Protocol`-based
interface for a service that has exactly one implementation; that is the abstraction
`ponytail`/the app-service correction pass exists to keep out.

## Repository rules

Unchanged, repo-wide, since `backend/docs/repository-boundaries.md`:

- Repositories accept an `AsyncSession`, return ORM models or row tuples.
- Repositories never import Pydantic, FastAPI/FastStream, cache clients, outbox publishers, or
  service settings.
- Write methods flush only.
- Large analytical queries (CTEs, window functions, leaderboards, ML feature extraction,
  achievement/recalculation queries) live in a domain's `queries.py`/service class, never behind
  a CRUD repository method.
- `backend/tests/test_repository_boundaries.py` enforces this by regex across every service.
  It exempts two named sets: `APPROVED_DIRECT_WRITE_FILES` (intentionally not CRUD — outbox
  draining, bracket advancement, bulk association-table updates) and
  `PENDING_REPOSITORY_MIGRATION` (debt, one line to delete per finished migration). Both are
  ratcheted — an exemption whose file stopped writing directly fails the suite — so neither
  list can rot the way the single allowlist did.

## Import layering between domains, when it's worth enforcing

Most services are a flat set of mutually-non-importing domains (`balancer-service`'s
`admin/*`/`draft/*`; most of `identity-service`) — nothing to enforce beyond "don't import
another domain's private module," checked by grep at review time, not by tooling.

Only reach for an `.importlinter` contract when a service has grown a genuine multi-level
dependency hierarchy — `app-service`'s `services.achievements` → `services.{dashboard,user}` →
`services.{hero,map,statistics,workspace}` (`app-service/.importlinter`,
`backend/docs/architecture/layering.md`). The contract states the layers, forbids the reverse
direction, and grandfathers pre-existing violations by name so they can't grow silently. Adding
one to a flat service (`balancer-service`) would enforce nothing real; skip it there and say so
in the plan doc, as `docs/plans/2026-08-21-balancer-service-oop-repositories.md` §5/§7 do.

## What actually lives in `serve.py`

"Registers subscribers, no business logic" is the rule; the honest list of what a real
`serve.py` also does is: `setup_logging`/`setup_sentry`/`setup_tracing`, `make_rabbit_broker`,
`configure_cache()`, `start_worker_metrics_server`, health checks, the scheduler loops (each
wrapped in `observe_scheduled_job`, e.g. the outbox drain), and `@app.on_shutdown` client
teardown. Event *consumers* are subscribers too, but they belong in a module
(`services/tournament_events.py`, `rpc/<domain>.py`) that `serve.py` calls `register(...)` on —
a handler body in `serve.py` is business logic in the entrypoint.

`identity-service` was the long-standing exception — 55 `@broker.subscriber` handlers inline in
a 1091-line `serve.py`, no `src/rpc/` package — and is now split like everything else
(`src/rpc/{tokens,auth,oauth,api_keys,rbac,players,avatars}.py`). Its envelope helpers stayed
identity-local in `src/rpc/_common.py` rather than moving to `shared.rpc.common`: this service
takes a flat `data` dict and resolves the caller from a bearer `data["access_token"]` itself,
so the shared `{payload, query, identity}` decoders do not apply.

## Two credentials, one branch

`Authorization: Bearer` carries either a **session JWT** or a **workspace-scoped API key**
(`owt_sk_<public_id>_<secret>`; legacy `aqt_sk_` keys still validate). Exactly one place in the backend knows the difference:
`rpc.identity.validate_token` → `services/token_validation.py::TokenValidationService.validate`,
which asks `ApiKeyService.is_api_key` and forks. Both branches return the same
`schemas.TokenPayload`, the gateway injects it into every RPC as `data["identity"]`, and
`shared.rpc.identity.rehydrate_user` rebuilds an `AuthUser` from it. Everything downstream —
every gate in every service — sees one shape and must keep it that way: a handler that inspects
`credential_type` to decide authorization has re-implemented the fork in the wrong layer.

An API key's payload is its **owner's RBAC, narrowed**
(`services/api_keys.py::ApiKeyService.validate`):

- `is_superuser=False`, `roles=[]`, `permissions=[]`. The emptiness is deliberate, not an
  omission. Global permissions would ignore the key's workspace, and role *names* are worse:
  `AuthUser._has_admin_equivalent_role` and `is_workspace_admin` short-circuit
  `has_workspace_permission` (`shared/models/identity/auth_user.py:167-207`) on a name like
  `owner`/`admin` before any permission is examined, so a key carrying one would inherit its
  owner's whole workspace instead of its scopes.
- `denies` is the owner's deny overlay, **verbatim**. It is the one thing that must not be
  narrowed: `has_workspace_permission` checks `is_denied` first, so dropping it makes negative
  RBAC fail open for keys.
- `workspaces` has exactly one entry — the key's workspace — with `rbac_roles=[]` and
  `rbac_permissions` set to the key's scopes **intersected** with what the owner effectively
  holds there. The intersection is the whole security model: a key cannot outrank its owner, and
  revoking the owner's grant revokes the key's.
- `credential_type="api_key"` plus an `api_key` block (`id`, `public_id`, `workspace_id`,
  `scopes`) for the consumers that legitimately need the credential itself. It carries no
  numbers: quotas live in the `quota` schema and are enforced by `shared/quota/`, which every
  service calls at the operations that cost something (`quota.charge` / `quota.lease`). Two
  scopes are checked on every metered call — the workspace's shared budget and the
  key's/session's own — and the tighter one refuses. The client-side contract, the seeded
  numbers and the refusal shapes are published in
  [`../docs/api-rate-limits.md`](../docs/api-rate-limits.md). There is no per-key config policy:
  an API client passes the same solver arguments a browser does.

Because the intersection is already written into `rbac_permissions`, an API key is authorized by
the ordinary path: `AuthUser.has_workspace_permission`, the single source of truth for
precedence. Do not add scope checks alongside it.

A scope **is** a permission name from `PERMISSION_CATALOG` (`shared/rbac/catalog.py`) —
`team.create`, `registration.approve`, the `admin.*` wildcard — not a parallel taxonomy.
`shared/rbac/scopes.py` owns that vocabulary: `normalize_scopes` (expands legacy aliases, drops
names retired from the catalog), `unknown_scopes` (creation-time validation), `scope_pairs`, and
`scope_grants` for the rare gate that must test scopes directly. Keys minted before scopes were
real carry `balancer.jobs`; `LEGACY_SCOPE_ALIASES` maps it to `team.create`, the permission the
balancer job paths already checked, so no data migration is needed. An empty scope list means
zero permissions — there is no implicit default.

Key and session management stay JWT-only, and structurally so rather than by an explicit check:
those handlers resolve the caller through `src/rpc/_common.py::with_active_user` →
`TokenValidationService.resolve_active_user` → `_resolve_bearer`, which JWT-decodes the bearer
(`services/token_validation.py:99-102`). An `owt_sk_` string is not a JWT, so it 401s. That
covers creating/updating/revoking keys, logout and logout-all, session list and revoke, and the
`/api/auth/me` family (profile read/update, delete, password change) — a key can neither mint
another key nor extend a session. Login and refresh never see a bearer at all: they take
credentials or a refresh token from the request body.

A third payload never rides a bearer at all: **`credential_type="discord"`**, the bot acting for
the account that linked the Discord user who pressed a button on a notification card.
discord-service calls `rpc.identity.discord_identity` with the clicker's Discord id (which
Discord signs; the button carries only the action and its target) and gets that account's
ordinary `TokenPayload` back, or `not_found` when nothing is linked -- the OAuth link *is* the
credential. The payload is the owner's full RBAC, unnarrowed, because the bot can only ever run
the fixed, self-service action list in `discord-service/src/interactions/actions.py`, each
through the same user RPC the site calls; widening that list is a reviewed change there, not a
scope on the credential. The type exists for the journal alone: `record_audit` stores such rows
with `source="discord"` and a `(via Discord)` actor suffix. Like `oauth_discord_guilds`, the
subject has no gateway route and trusts the internal broker.

## Gateway contract

The Go gateway is the only HTTP surface; it publishes to `rpc.<service>.<domain>.<method>` and
waits for the envelope. Three things must agree for a route to exist, and none of them is
checked at startup — a missing subscriber shows up as a client-side *timeout* with nothing in
the logs:

1. the gateway route table (`gateway/internal/<service>/`),
2. the `@broker.subscriber("...")` literal,
3. `src/openapi_docs.py` (prose) and `src/openapi_schemas.py` (request/response shapes), keyed
   by subject and merged into the published OpenAPI by
   `backend/scripts/export_openapi_schemas.py`.

`backend/tests/test_rpc_route_parity.py` statically compares (1) and (2) for all seven RPC
services. It resolves f-string subjects (`f"rpc.app.{prefix}.admin_list"`) as templates, because
a factory that registers twelve subjects from one literal would otherwise read as twelve
orphans. Nothing checks (3): an openapi entry missing for a live subject only shows up as a hole
in the published API docs.

## Testing conventions that fall out of this

- `domain/` — plain `pytest` functions, constructed objects, no fixtures, no `pytest.mark.db`,
  deterministic. This is where property-style and exhaustive-case tests belong (bipartite
  matching, slot-vocabulary edge cases, seat-order rules).
- `services/<domain>/*.py` — either a real-Postgres integration test (`test_draft_integration.py`
  style: a throwaway session against migrated schema, exercising the full flow) or a unit test
  against a fake repository passed to the constructor. Prefer the former for anything with a
  concurrency-sensitive repository method (locking reads, optimistic-lock finalize); it is the
  only way to actually exercise the lock.
- `rpc/<domain>.py` — `backend/tests/test_rpc_route_parity.py`-style contract tests (route
  presence, auth requirements) rather than re-testing business logic already covered one layer
  down.

## Checklist: adding a new domain (or a new file inside an existing one)

1. **Repository first.** If the domain needs new CRUD, write the repository methods in
   `shared/repository/<x>.py` before any consumer code — this is the "shared prerequisite"
   step; every layer above it depends on the exact method shape.
2. **Pure logic next, if any.** Any algorithm/validation/scoring that doesn't touch a session
   goes in `src/domain/<x>.py` (or `shared/domain/` if more than one service will use it), with
   a curated `__all__`. Write and run its tests with no DB fixture before touching a service.
3. **Service class.** One class, one singleton, constructor-injected repositories/domain
   collaborators with singleton defaults. `session` is a method parameter, never stored on
   `self`.
4. **RPC handler.** One `@broker.subscriber` per method, decoding via `src.rpc._common`
   (`c.q1`, `c.require_id`, `c.gate_*`, `c.envelope`), calling exactly one service method, no
   inline SQL, explicit `session.commit()` if the handler mutates.
5. **Side effects, if the handler mutates.** Outbox event (same transaction) for anything
   another service must learn about; `publish_patch`/`publish_event` for anything a connected
   client is watching; cache invalidation for any prefix the write invalidates.
6. **Contract.** Gateway route + `openapi_docs.py` + `openapi_schemas.py` entries for the new
   subject; a new table also needs an Alembic revision in `backend/migrations/`.
7. **Verify:** `ruff check`, the service's `pytest` suite (with a real, migrated Postgres —
   `alembic upgrade head` first if the DB is fresh), `python -c "import serve"` to catch import
   cycles, `lint-imports` if the service has an `.importlinter`, and the repo-wide guards in
   `backend/tests/` (`test_repository_boundaries.py`, `test_rpc_route_parity.py`,
   `test_rpc_error_code_parity.py`).

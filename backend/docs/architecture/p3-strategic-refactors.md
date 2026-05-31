# P3 Strategic Refactors — Implementation Plans

This document captures the three remaining strategic items from the
architecture review (P3-A/B/D). Each section ends with a concrete
question that needs an architectural decision before implementation can
start.

E (WorkspaceContext via `Depends`) and C (import-linter layering) are
already in place; see `layering.md`.

---

## P3-A — De-duplicate `app-service` ↔ `tournament-service` reads

**Status:** Implemented 2026-05-24 (HTTP boundary split + `_internal/` rename). Narrow-DTO follow-up deferred. See [`specs/2026-05-24-p3a-tournament-flow-extraction-design.md`](specs/2026-05-24-p3a-tournament-flow-extraction-design.md).

### Problem

Public-read endpoints `/tournaments`, `/encounters`, `/registration`,
`/lookup` exist in both `backend/app-service/src/routes/` and
`backend/tournament-service/src/routes/` with byte-near-identical handler
bodies. Each calls its own service layer. Schema drift is inevitable —
two routers will eventually return different shapes for the same path,
and the boundary between the two services has effectively collapsed.

### Affected files

```
backend/app-service/src/routes/{tournament,encounter,match,registration}.py
backend/tournament-service/src/routes/{tournament,encounter,registration}.py
backend/app-service/src/services/{tournament,encounter,registration}/**
backend/tournament-service/src/services/{tournament,encounter,registration}/**
```

### Option 1 — Read/Write split (recommended)

- **app-service**: read-only public API. Owns `GET /tournaments`,
  `GET /encounters`, `GET /matches`, `GET /registrations`. Already
  caches these via cashews (P1-#5). Stays mostly as-is; we delete the
  *write* equivalents and any duplicated read code that drifted from
  tournament-service.
- **tournament-service**: tournament-lifecycle/write API. Owns POST/PUT
  for creating/editing tournaments, encounters, registrations. Receives
  admin traffic. Deletes its duplicate read endpoints.

Routing in Kong:
```
GET /api/v1/tournaments/**  → app-service
POST/PUT/DELETE /api/v1/tournaments/** → tournament-service
```

Kong already supports HTTP method-based routing.

Effort: 4-6 weeks.
- Week 1: audit drift, list every diverging field
- Weeks 2-3: pick canonical shape per resource, fix tests
- Week 4: route split in Kong, deploy, monitor errors
- Weeks 5-6: delete duplicates, run import-linter sweep

### Option 2 — Shared router package

Extract `backend/shared-routers/` containing FastAPI router objects
mounted by both services. Both services keep their own service layers
but share request handlers.

Pros: less migration work; duplication eliminated at handler level.
Cons: doesn't fix the underlying service-layer duplication; both services
remain coupled to the same DB tables.

Effort: 2 weeks. **Not recommended** — addresses the symptom, not the cause.

### Open question

**Which split?** Read-only/write (Option 1) is cleaner long-term but
requires Kong method-based routing. Shared router (Option 2) is faster
but leaves DB coupling in place.

---

## P3-B — Replace string `entities=` with typed projection

### Problem

44 endpoints across 8 route files accept `entities: list[str] = Query([])`
and pass strings opaquely to `flows.to_pydantic(..., entities)` which
dispatches loads. There is no whitelist enforcement, no per-entity cost
accounting, the response shape is documented only in route docstrings,
and frontend callers couple to ORM-internal names. This is pseudo-GraphQL
on top of REST — neither the type guarantees of REST nor the query
planning of GraphQL. A single
`entities=tournament,stage,home_team.players,away_team.players,matches.stats`
request fans out into dozens of joins. Once selectinload is on (P0),
each entity is a separate `IN(...)` query, so the cost scales linearly
with the number of entities — but it's still unbounded.

### Option 1 — Typed projection enum + cost weights (recommended)

For each resource, define:

```python
class EncounterField(StrEnum):
    tournament = auto()      # cost 1
    stage = auto()           # cost 1
    home_team = auto()       # cost 1
    home_team__players = auto()  # cost 5 (loads collection)
    matches = auto()         # cost 5
    matches__map = auto()    # cost 1 per match

_FIELD_COST: dict[EncounterField, int] = {...}
_MAX_FIELD_COST_PER_REQUEST = 25
```

Route signature:
```python
async def get_encounters(
    fields: list[EncounterField] = Query([]),
    ...
):
    total_cost = sum(_FIELD_COST[f] for f in fields)
    if total_cost > _MAX_FIELD_COST_PER_REQUEST:
        raise errors.ApiHTTPException(
            status_code=400,
            detail=[errors.ApiExc(code="field_set_too_expensive", ...)],
        )
```

Benefits:
- Typed at the API boundary
- OpenAPI auto-documents the allowed field names
- Frontend `apiFetch` can type-check `entities` against generated SDK
- Per-request cost capped — defence-in-depth against repeated incidents
  like the encounters page hang (see P0 root cause)

Effort: 2-3 weeks.
- Week 1: define enums + cost tables for 5 main resources
  (Encounter, Match, Team, Tournament, User)
- Week 2: thread through routes/flows, update tests
- Week 3: update frontend `apiFetch` SDK to use typed names

### Option 2 — Explicit endpoint per response shape

Split heavy reads:
- `GET /encounters` → minimal shape
- `GET /encounters/full` → tournament + stage + teams
- `GET /encounters/full-with-players` → adds players (most expensive)

Pros: simpler, no client coupling to projection enum.
Cons: combinatorial explosion of endpoints; doesn't scale.

Effort: 1-2 weeks per resource. **Not recommended** — combinatorial.

### Open question

**Which model?** Typed projection enum (Option 1) is the right
architecture; Option 2 is a stopgap. Decision affects how the frontend
SDK is regenerated.

---

## P3-D — Split `backend/shared/`

### Problem

`backend/shared/` contains:

- `models/` — SQLAlchemy ORM models (used by every service)
- `schemas/` — cross-service Pydantic schemas
- `clients/` — HTTP/S3/auth clients (used by ~4 services)
- `observability/` — logging/tracing/metrics middleware (used by all)
- `messaging/` — RabbitMQ config + outbox helpers
- `domain/` — division_rank, player_sub_roles (business logic!)
- `services/` — bracket engine, achievement_effective, realtime_publisher
  (cross-service business logic!)

`shared/` is no longer "shared primitives" — it's a hidden 9th service
with its own domain logic. Every service redeploy is coupled to shared
changes; a `shared.services.bracket` bug fix forces rebuilding all 8
service images.

### Proposed split

Three independently-versioned packages in the uv workspace:

```
backend/
  shared-core/        # observability, errors, clients, messaging
  shared-models/      # SQLAlchemy ORM + shared Pydantic schemas
  shared-domain/      # bracket engine, achievement_effective, etc.
```

- `shared-core` rarely changes; can be versioned `^1.0`
- `shared-models` changes per migration; pinned per service
- `shared-domain` is the volatile one — services pinning explicit minor
  versions can deploy independently

### Effort

8-12 weeks. Major touchpoints:
- Every service's `pyproject.toml` (8 services)
- Every import: `from shared.X` → `from shared_core.X` or `from shared_domain.X`
- Docker build context (each package builds as a wheel)
- CI: each package gets its own test job
- Migration: keep `shared` as a meta-package re-exporting for one
  release cycle to avoid breaking external callers

### Open question

**Worth the cost?** This is the largest single piece of work in the
review. Without it, deployment coupling between services remains; with
it, the team gains the option to deploy services independently. Calling
this out as a 1-quarter project.

---

## Summary recommendation

1. **Done now**: P3-E (WorkspaceContext), P3-C (import-linter baseline).
2. **Next 2 weeks** if there's headcount: P3-B (typed projection) — the
   typed `EncounterField` work prevents future encounter-style outages.
3. **Quarter project**: P3-A (read/write split) — wait until P3-C debt
   is paid down (the user-shaped lower-layer imports), then split.
4. **Hold**: P3-D (shared split). Revisit when independent deploys
   become a hard requirement (right now redeploy-all is tolerable).

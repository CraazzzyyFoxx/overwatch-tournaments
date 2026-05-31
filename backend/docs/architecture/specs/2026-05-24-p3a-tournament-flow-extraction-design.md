# P3-A — Tournament Flow Extraction (Design)

**Date:** 2026-05-24
**Status:** Implemented.
**Supersedes:** P3-A in `../p3-strategic-refactors.md` (rejected Option 1 read/write split in favor of domain split)

## Goal

Move all tournament-flow HTTP endpoints from `app-service` into `tournament-service`. Leave statistics, user, achievements, dashboard, and metadata lookups in `app-service`. Eliminate the duplication of routes between the two services and remove cross-service HTTP shape drift risk.

## Outcome

- **HTTP routes** for `/tournaments`, `/encounters`, `/matches`, `/teams`, `/registration`, `/division-grids`, `/admin/*` are served **only** by `tournament-service` under the bare `/api/v1` prefix. `app-service` no longer has any of those route files and is mounted under `/api/v1/core` (static asset upload/delete included). Kong routes by single prefix per service (see [Kong routing](#kong-routing)).
- **`services/_internal/` was deleted entirely.** The previously moved service-layer modules (`tournament/`, `encounter/`, `team/`, `standings/`, `registration/`, `division_grid/`, `dto.py`) no longer exist in `app-service`. Their responsibilities split into:
  - **Per-consumer repositories**: `services/user/_repositories.py` and `services/achievements/_repositories.py` hold the SQL queries each consumer needs (paginated user encounters, bulk match/tournament fetch, team counts, player lookups). Each consumer owns its own queries — no cross-consumer sharing.
  - **Per-consumer mappers**: `services/user/_mappers.py` and `services/achievements/_mappers.py` convert ORM rows directly into the narrow DTOs that ship to the frontend.
  - **`services/tournament_events.py`** — top-level module that holds the RabbitMQ `task_router` for `tournament.changed` events (previously `_internal/tournament/recalculation_events.py`).
- **Wide DTOs removed.** The old `TournamentRead` / `EncounterRead` / `MatchRead` / `TeamRead` / `PlayerRead` / `StageRead` / `StandingRead` / `RegistrationRead` shapes do not exist in `app-service` anymore. They were never API contracts in `app-service` (those endpoints moved to tournament-service); they were leftover internal types.
- **Narrow DTOs defined in `schemas/user.py` + `schemas/achievement.py`** are the canonical response shapes for `/users/*` and `/achievements/*` endpoints:
  - `UserTournamentSummary` — fields the user-overview page actually uses
  - `UserTournamentPlayer` — fields TournamentTeamTable renders
  - `UserEncounterTournament`, `UserEncounterStageSummary`, `UserEncounterStageItemSummary`, `UserEncounterTeamSummary` (with `UserEncounterTeamPlayerRef` to identify the viewer) — fields the encounter list uses
  - `MatchReadWithUserStats` — standalone (no inheritance), contains the viewer's `performance` + `heroes`
  - `EncounterReadWithUserStats` — standalone, plus `user_team_id` convenience field
  - `AchievementTournamentLink`, `AchievementMatchLink` (with `AchievementMatchTeamRef`) — narrow refs for achievement payloads
- **Phase 3h**: `get_encounters_by_user` lives in `services.user.flows`. `routes/user.py` only imports from `services.user.flows`.
- **`app-service/.importlinter`** rewritten under the new layout:
  - Contract 1 is a tighter layered hierarchy (no `_internal` layer).
  - Contract 2 unchanged (routes via flows).
  - Contract 3 + 4 lock private `_repositories.py` / `_mappers.py` to their owning consumer — preventing future leakage.
- **Frontend types updated** in `frontend/src/types/user.types.ts` and `frontend/src/types/achievement.types.ts`:
  - `MatchWithUserStats` and `EncounterWithUserStats` no longer extend `Match` / `Encounter`. They are standalone interfaces matching the narrow API contract.
  - `UserProfile.tournaments: UserTournamentSummary[]` (was `Tournament[]`).
  - `UserTournament.players: UserTournamentPlayer[]` (was `Player[]`).
  - `AchievementRarity.tournaments / matches`, `AchievementEarned.last_tournament / last_match` use narrow link types.
- **Frontend components touched** to consume narrow types: `TournamentTeamTable` accepts a structural `TeamRosterPlayer`, `PlayerName` accepts any `{name, role?, sub_role?}` shape, `MatchesTable` reads `match.heroes` directly instead of digging through `match.{home,away}_team.players`, `AchiementUsers` handles `last_tournament / last_match` nullables.
- **Dead tests** `test_registration_validation.py` and `tests/test_registration_route.py` removed.

## Boundary

### Moves to `tournament-service` (routes + services + schemas)

| Resource | Source files in `app-service` |
| --- | --- |
| `/tournaments/**` | `routes/tournament.py`, `services/tournament/`, `schemas/tournament.py`, `schemas/stage.py`, `schemas/standing.py` |
| `/encounters/**` | `routes/encounter.py`, `services/encounter/`, `schemas/encounter.py` |
| `/matches/**` | `routes/match.py`, plus matches-related code inside `services/encounter/`, `schemas/match` parts of `schemas/encounter.py` |
| `/teams/**` | `routes/team.py`, `services/team/`, `schemas/team.py` |
| `/registration/**` | `routes/registration.py`, `services/registration/`, `schemas/registration.py` |
| `/division-grids/**` | `routes/division_grid.py`, `services/division_grid/`, `schemas/division_grid.py` |
| Standings (internal use only) | `services/standings/` |

`tournament-service` already owns its versions of tournaments, encounters, teams, registration. The work is reconciling drift, porting what is missing (`matches`, `division_grid`), and deleting the `app-service` copies.

### Stays in `app-service`

- `/statistics/*` (dashboard, champion, winrate, won-maps)
- `/users/*` including `{id}/tournaments`, `{id}/encounters`, `{id}/profile`, `{id}/maps`, `{id}/heroes`, `{id}/teammates`, `{id}/compare`, `/overview*`, `/search`
- `/achievements/*`
- `/heroes`, `/gamemode`, `/maps`, `/assets`, `/workspaces` (metadata, not division-grids), `/utils`
- Services: `services/user/`, `services/statistics/`, `services/dashboard/`, `services/achievements/`, `services/workspace/`, `services/hero/`, `services/map/`, `services/gamemode/`

## Data access strategy

`app-service` keeps direct DB access via `shared.models` ORM. There is no HTTP client to `tournament-service`. After deleting `services/tournament/`, `services/encounter/`, `services/team/`, `services/registration/`, `services/standings/`, `services/division_grid/` from `app-service`, the remaining consumers (user, statistics, achievements, dashboard) are rewritten to use inline SQLAlchemy queries against `shared.models`.

## URL changes

`/workspaces/{ws_id}/division-grids/...` conflicts with workspace metadata endpoints that stay in `app-service`. All division-grid endpoints consolidate under `/api/v1/division-grids` so Kong only needs one prefix rule:

| Old | New |
| --- | --- |
| `GET /api/v1/workspaces/{ws_id}/division-grids` | `GET /api/v1/division-grids/by-workspace/{ws_id}` |
| `POST /api/v1/workspaces/{ws_id}/division-grids` | `POST /api/v1/division-grids/by-workspace/{ws_id}` |
| `GET /api/v1/workspaces/{ws_id}/division-grids/{id}/versions` | `GET /api/v1/division-grids/{id}/versions` |
| `POST /api/v1/workspaces/{ws_id}/division-grids/{id}/versions` | `POST /api/v1/division-grids/{id}/versions` |
| `GET /api/v1/division-grid-versions/{version_id}` | `GET /api/v1/division-grids/versions/{version_id}` |
| `DELETE /api/v1/division-grid-versions/{version_id}` | `DELETE /api/v1/division-grids/versions/{version_id}` |
| `POST /api/v1/division-grid-versions/{version_id}/publish` | `POST /api/v1/division-grids/versions/{version_id}/publish` |
| `POST /api/v1/division-grid-versions/{version_id}/clone` | `POST /api/v1/division-grids/versions/{version_id}/clone` |
| `GET /api/v1/division-grid-mappings/{src}/{tgt}` | `GET /api/v1/division-grids/mappings/{src}/{tgt}` |
| `PUT /api/v1/division-grid-mappings/{src}/{tgt}` | `PUT /api/v1/division-grids/mappings/{src}/{tgt}` |
| `GET /api/v1/workspaces/{ws}/division-grid-marketplace/workspaces` | `GET /api/v1/division-grids/by-workspace/{ws}/marketplace/workspaces` |
| `GET /api/v1/workspaces/{ws}/division-grid-marketplace` | `GET /api/v1/division-grids/by-workspace/{ws}/marketplace` |
| `POST /api/v1/workspaces/{ws}/division-grid-marketplace/import` | `POST /api/v1/division-grids/by-workspace/{ws}/marketplace/import` |

All other tournament-flow URLs stay byte-identical for the frontend.

## Kong routing

`kong/kong.dev.yml` and `kong/kong.prod.yml` route by a **single prefix per service** instead of enumerating each tournament resource. `tournament-service` owns the bare `/api/v1` namespace; `app-service` is carved out under the more-specific `/api/v1/core` prefix. Kong's longest-prefix match sends `/api/v1/core/*` to `app-service` and everything else under `/api/v1/*` to `tournament-service`:

```yaml
- name: tournament
  url: http://tournament:8004
  routes:
    - name: tournament-v1-api
      paths: [/api/v1]
      strip_path: false
      preserve_host: true

- name: backend
  url: http://backend:8000
  routes:
    - name: backend-api
      paths: [/api/v1/core]   # wins over /api/v1 (longer prefix)
      strip_path: false
      preserve_host: true
```

`app-service` `root_path` is `/api/v1/core` (config `api_v1_str`); `tournament-service` `root_path` is `/api/v1`. Static asset upload/delete is served by `app-service` at `/api/v1/core/assets/*` — it rides along with the `/core` prefix, so no special override route is needed. Registration moved from `/workspaces/{ws}/tournaments/{t}/registration*` to `/tournaments/{t}/registration*` so the entire `/api/v1/tournaments` prefix flows to `tournament-service` without a `/workspaces` collision.

On the frontend, the `apiFetch` service map encodes this split: the `app` service uses `clientBase` `/api/v1/core`, the `tournament` service uses `/api/v1`. Resources owned by `tournament-service` (incl. `division-grids` and `matches`) must be called via the `tournament` service even when invoked from app-centric service modules.

## Response schema strategy

`app-service` endpoints that stay must stop returning shapes owned by `tournament-service`. They define their own narrow response DTOs in `app-service/src/schemas/user.py` (or a new `schemas/user_views.py`):

- `/users/{id}/tournaments` returns `UserTournamentParticipation[]` — `{ tournament_id, name, slug, placement, role, team_id, team_name }` instead of `TournamentRead`.
- `/users/{id}/encounters` returns `UserEncounterSummary[]` — narrow `{ encounter_id, tournament_id, opponent_team_id, result, ... }`.
- `/users/overview` already aggregates; row schema includes only what the frontend list view needs (no nested `TournamentRead`).
- Achievement responses currently include tournament data via `entities=tournaments` — replaced by a narrow `AchievementTournamentLink` schema.

This breaks compile-time coupling: `app-service` no longer imports `TournamentRead` / `EncounterRead` / `MatchRead` / `TeamRead`.

## Cross-service domain rules

Visibility/filter helpers that today live inside `services/tournament/service.py` and are needed by both services (for example "include only published tournaments", draft filter, workspace scoping) move into `shared/domain/tournament_visibility.py` as thin pure functions returning SQLAlchemy clauses:

```python
def visible_tournaments_filter(workspace_id: int | None, include_drafts: bool = False) -> ColumnElement[bool]: ...
```

Both services import and apply it in their own queries. No business logic lives in two places.

## Cache

`cashews` decorators on the moved endpoints move with them into `tournament-service`. Cache TTL constants (`tournaments_cache_ttl`, `encounters_cache_ttl`, `teams_cache_ttl`, `registration_cache_ttl`) migrate from `app-service/src/core/config.py` to `tournament-service/src/core/config.py`. The Redis keyspace (`fastapi:` prefix) is shared, so old cache keys remain valid. A one-shot `cache.delete_match("fastapi:*tournaments*")` runs on `tournament-service` lifespan startup for the first deploy.

## Import-linter

Implemented Contract 3 in `backend/app-service/.importlinter`:

```ini
[[importlinter.contracts]]
name = app-service routes do not depend on tournament-flow internals
type = forbidden
source_modules =
    src.routes
forbidden_modules =
    src.services._internal.tournament
    src.services._internal.encounter
    src.services._internal.team
    src.services._internal.registration
    src.services._internal.standings
    src.services._internal.division_grid
ignore_imports =
    src.routes.user -> src.services._internal.encounter.flows
```

The forbidden modules are tournament-flow private internals (renamed from `services/tournament/`, etc. — see Outcome note above). `user/`, `achievements/`, `dashboard/`, `statistics/` flows ARE allowed to import from `_internal/` because they need the data.

The single ignored import (`routes/user.py → encounter_flows.get_encounters_by_user`) is tracked debt — to be migrated into `services/user/flows.py` so the route only imports `user_flows`.

## Phases

### Phase 0 — Drift audit (≈3 days)

For each paired module pair `app-service/src/{routes,services,schemas}/X.py` and `tournament-service/src/{routes,services,schemas}/X.py`:

- Diff route signatures and response shapes; note divergence in `backend/docs/architecture/specs/2026-05-24-p3a-drift-audit.md`.
- Pick canonical shape per route (default: `tournament-service` version).
- Identify breaking changes that affect frontend; flag for Phase 5.
- Snapshot OpenAPI of both services as before/after baseline.

### Phase 1 — Complete tournament-service surface (≈1 week)

- Port `routes/match.py` to `tournament-service`.
- Port `routes/division_grid.py` with new URLs.
- Port `services/division_grid/` (including `marketplace.py`).
- Extend `services/encounter/` in `tournament-service` to cover matches (`get_all_matches`, `get_match_with_stats`).
- Apply `cashews` decorators with TTLs ported from `app-service` config.
- Port matching tests from `backend/tests/` paths.

### Phase 2 — Kong + shadow routing (≈3 days)

- Update `kong/kong.dev.yml` and `kong/kong.prod.yml`.
- Verify `tournament-service.api_root_path` = `/api/v1`.
- Deploy with `app-service` still serving the same routes; Kong picks `tournament-service` (longer prefix). Roll back by removing the new Kong route block.
- Run staging E2E smoke.

### Phase 3 — Refactor app-service consumers (deferred → narrow-DTO work only)

The original spec intent was: rewrite `services/user/flows.py`, `services/achievements/flows_v2.py`, `services/dashboard/*`, and migrate response shapes to narrow DTOs (`UserTournamentParticipation`, `UserEncounterSummary`, `AchievementTournamentLink`) so the schemas in `schemas/{tournament,encounter,team,match}.py` could be deleted from `app-service`.

What was actually done:

- `services/user/service.py` had its single `team_service.team_entities()` call inlined as `_team_load_options()` — see the file. This removed one ORM-internal coupling.
- `services/dashboard/*` and `services/statistics/*` were audited — they already use inline SQL and have no tournament-flow imports. No changes needed.
- `services/user/flows.py` and `services/achievements/flows_v2.py` were **not** rewritten. They still call `_internal.tournament.flows.to_pydantic`, `_internal.encounter.flows.to_pydantic_match`, etc. These calls flow through nested Pydantic conversions where `MatchReadWithUserStats` extends `MatchRead`, `EncounterReadWithUserStats` extends `EncounterRead`, and `UserProfile.tournaments` is `list[TournamentRead]`. Disentangling this without breaking the frontend requires designing narrow alternatives and updating frontend types in lockstep.

This deferred narrow-DTO work is now tracked separately and is not blocking the HTTP boundary split.

### Phase 4 — Rename to `_internal/` (≈1 day, done)

- Removed `routes/{tournament,encounter,match,team,registration,division_grid}.py` from `app-service`. ✅
- Renamed `services/{tournament,encounter,team,registration,standings,division_grid}/` → `services/_internal/{tournament,encounter,team,registration,standings,division_grid}/` via `git mv`. ✅
- Updated 11 import sites across `app-service` (`main.py`, `routes/user.py`, `services/achievements/flows_v2.py`, `services/user/flows.py`, `services/_internal/*/flows.py + service.py`, `test_registration_validation.py`). ✅
- Updated `routes/__init__.py` to drop the deleted routers. ✅
- Updated `.importlinter` with Contract 3 (routes/ cannot import _internal). ✅
- Schemas (`schemas/{tournament,encounter,team,match,registration,division_grid,standing,stage}.py`) **kept** — used by user/achievements response shapes. Narrow-DTO follow-up will remove them once frontend can absorb a breaking change.

### Phase 5 — Frontend (done)

- `frontend/src/services/workspace.service.ts` migrated to new `/api/v1/division-grids/...` URLs.
- `npx tsc --noEmit` passes.
- Full e2e is a deploy-time gate, not a code change.

## Total estimate (actual)

~3 working days for the HTTP boundary split + internal rename. Narrow-DTO work remains open-ended.

## Acceptance criteria (status)

- `GET /api/v1/tournaments`, `/encounters`, `/matches`, `/teams`, `/registration*`, `/division-grids*` served only by `tournament-service`. ✅
- No files: `backend/app-service/src/routes/{tournament,encounter,match,team,registration,division_grid}.py`. ✅
- No directories at `backend/app-service/src/services/{tournament,encounter,team,registration,standings,division_grid}/` — instead they live at `services/_internal/...`. ✅ (variant: rename, not delete)
- `import-linter` Contract 3 added; full lint run is CI-gated.
- Both services build (`py_compile` green); `frontend tsc --noEmit` green. ✅
- Schemas in `app-service/src/schemas/{tournament,encounter,team,...}.py` **not** deleted — kept for response shapes. Deferred.

## Risks

1. **HTTP shape drift between paired modules** — surfaced in Phase 0. If divergence is large, fold breaking-fix into the same release that ships Phase 2; involve frontend.
2. **`/users/{id}/tournaments` shape change** — `UserTournamentParticipation` is narrower than `TournamentRead`. Mitigation: ship frontend changes in the same release.
3. **Cache staleness on cut-over** — one-shot `cache.delete_match` on `tournament-service` first start handles it.
4. **Inline queries diverging in business rules from tournament-service** — Mitigation: `shared/domain/tournament_visibility.py` holds the one source of truth.
5. **Hidden imports** — there may be deep call chains through `app-service` services that the grep missed. Mitigation: `import-linter` baseline before Phase 4 catches them; CI fails fast.

# Custom Games — Design (Phase 1)

- **Date:** 2026-06-29
- **Status:** Approved (brainstorming) — pending implementation plan
- **Scope:** Phase 1 only. Persistent rating, leaderboard, seasons, self-serve queue, realtime live-drag, and match-log→stats integration are explicitly deferred to later phases.

## Context & goal

The platform is tournament-centric: `Tournament → Stage → Encounter → Match/Statistics`, and `Team`/`Player`, the **balancer** (config + `BalancerBalance`), **draft**, **match-log** (`LogProcessingRecord`), stats and analytics are all keyed on `tournament_id`. The **moo_core** balancing engine (`balancer-service/native/moo_core`, Rust/pyo3) is a *pure function*: roster + ranks + config → balanced teams. Only the service layer around it (config, persisted `BalancerBalance`, Form UI, realtime) is `tournament_id`-bound.

**Custom games** are organizer-run **balanced pickup games inside a workspace**, distinct from tournaments. Long-term they also accumulate an optional persistent in-house rating/leaderboard, but the **primary** workflow is the lobby leader controlling player ranks manually. Phase 1 delivers the game lifecycle + the per-member rank book that feeds it.

## Confirmed decisions

1. **Purpose:** balanced pickups (#1) that will later feed an optional in-house ladder (#3).
2. **Outcome granularity:** always record winner + per-map score; match-log upload is **optional** and deferred to a later phase.
3. **Entry (MVP):** organizer hand-picks the roster from workspace players. Self-serve queue/signup is later.
4. **Team formation:** autobalance via the moo_core engine (organizer can manually tweak via drag-and-drop).
5. **Rating:** OpenSkill-from-OW-rank is the eventual model, but **optional and secondary** — deferred to Phase 2. The primary rank input is the manual rank book below.
6. **Architecture:** **Approach B** — first-class `CustomGame` entity that reuses *only* the moo_core engine (stateless), no `tournament_id` / `BalancerBalance` persistence, no tournament pollution.
7. **Rank book:** a per-rater, per-player, per-role rank layer scoped to the workspace. The custom game balances from a **selectable rank source** (organizer's own book / a chosen member's book / aggregate).
8. **Aggregate method:** **median** across raters (robust to a single outlier opinion).

## Hosting

`balancer-service` owns custom games and the rank book (moo_core is in-process there; the service is already workspace-scoped with the right ACL patterns). ORM models live in `backend/shared/models/` (shared owns all models); migrations in `backend/migrations`.

## Component 1 — Workspace Rank Book

A workspace-scoped, per-member subjective rank layer over players. Independent and reusable (Phase 1 wires it only to custom games; the tournament balancer may consume it later).

### Data model
- **`workspace_player_rank`** (`backend/shared/models/custom_game.py` or a dedicated module):
  - `id`, `workspace_id` (FK `workspace.id`, CASCADE), `rater_user_id` (FK `auth.user.id`, CASCADE), `player_user_id` (FK `players.user.id`, CASCADE), `role` (HeroClass: tank/damage/support — honor the existing dps↔damage bridge), `rank_value` (int), timestamps.
  - `UniqueConstraint(workspace_id, rater_user_id, player_user_id, role)`.
  - Indexes for the two read patterns: by `(workspace_id, rater_user_id)` (a member's whole book) and by `(workspace_id, player_user_id, role)` (aggregate over a player+role).

### Rank resolution service (clean interface)
`resolve_rank(session, *, workspace_id, source, player_user_id, role) -> int | None`, where `source` is:
- `self` / `member:<user_id>` → the named rater's `rank_value` for `(player, role)`.
- `aggregate` → **median** of all raters' `rank_value` for `(player, role)` in the workspace.
- **Fallback** when the source has no value: the player's imported OW rank value (reuse the balancer's existing OW-rank resolution); if none, return `None` ("unrated" — organizer must set it on the game).

Batch variant `resolve_ranks(...)` for a full roster (one query per source, no N+1).

## Component 2 — Custom Game

### Data model (lean — 2 tables + status enum)
- **`custom_game`**:
  - `id`, `workspace_id` (FK, CASCADE), `name`, `status` (`draft` → `balanced` → `completed`, plus terminal `cancelled`),
  - `config_json` (team composition: `team_count`, `team_size`, `roles` — defaulted from the workspace balancer config),
  - `rank_source_type` (`self` | `member` | `aggregate`, default `self`), `rank_source_user_id` (FK `auth.user.id` SET NULL, nullable — only for `member`),
  - `result_json` (the balance output, **same shape as `BalancerBalance.result_json`** so the frontend team-display components are reused), nullable,
  - `outcome_json` (`{winner_team_index, maps: [{name, winner_team_index, score}]}`), nullable,
  - `created_by` (FK `auth.user.id` SET NULL), `played_at` (nullable), timestamps.
- **`custom_game_player`**:
  - `id`, `custom_game_id` (FK CASCADE), `player_user_id` (FK `players.user.id`), `role` (HeroClass), `rank_value` (int — seeded via the resolution service, **overridable per game**), `team_index` (nullable int, set on balance), `sort_order`.
  - `UniqueConstraint(custom_game_id, player_user_id)`.
- Teams are represented as index `0..team_count-1` (no separate team table for MVP); the winner references `team_index`.

### Lifecycle / state machine
`draft` (build roster, choose rank source, set/override ranks) → **balance** (moo_core assigns `team_index` + writes `result_json`; organizer may re-run or DnD-tweak) → `balanced` → **record outcome** (winner + per-map) → `completed`. `cancelled` is a terminal escape from any pre-`completed` state.

### Balancing integration
A `rpc.balancer.custom.balance` loads the roster + per-player `rank_value` + `config_json` and calls the **same pure moo_core entry point** the tournament balance uses — factored out so no `tournament_id` / `BalancerBalance` / config persistence is touched. The result is written to `custom_game.result_json` and per-player `team_index`. Manual DnD reuses the balancer's in-memory recompute logic on the custom roster (no realtime in Phase 1).

## API / RPC surface

balancer-service RPC subscribers (`rpc.balancer.*`):
- Rank book: `rpc.balancer.rankbook.{list, get_player, set, bulk_set, delete}` (a member operates only on their own book; reading aggregate/another member's book is allowed for workspace members).
- Custom game: `rpc.balancer.custom.{create, list, get, update, update_roster, set_rank, set_rank_source, balance, move_player, record_outcome, delete}`.

Gateway routes (Go), `AuthRequired`, workspace-scoped, body delivered under `data["payload"]` (read via `c.payload`):
- `/api/v1/rank-book/*`
- `/api/v1/custom-games/*`

## Frontend surface

- **Rank Book** page in the workspace: grid of workspace players × {tank, damage, support}; each member edits only their own cells; debounced `bulk_set`.
- **Custom Games**: list + a game editor reusing the balancer's rank-row and team-display components (roster picker, rank-source selector, per-player rank override, "Balance", DnD tweak, "Record outcome").
- New `custom-game.service.ts` / `rank-book.service.ts`. Public/SSR reads (if any) follow the existing Next Data Cache + `revalidateUser`/tag pattern; the editor is client-side react-query.

## Permissions / workspace scoping

New RBAC resource `custom_game` (`create/read/update/delete`), gated **per workspace** (workspace-member + manage capability), **superuser bypass** — mirroring the balancer's ACL. Heed the WS-ACL superuser lesson: the gateway WS-ACL must bypass for superusers (decode `is_superuser` in JWT). The rank book read is open to workspace members; writes are restricted to the rater's own rows.

## Testing

- Unit: rank resolution (self / member / aggregate-median / OW-rank fallback / unrated), batch resolution (no N+1), seeding on roster add, lifecycle transitions, outcome validation.
- Engine: a deterministic moo_core balance call over a fixed roster+ranks (seeded) produces stable team assignment.
- Integration (anak_dev): create game → set rank source → add roster → balance → record outcome → read back; rank-book set/get/aggregate.
- Frontend: `tsc` + `eslint` + component tests for the rank grid and the game editor.

## Out of scope (later phases)

- **Phase 2:** optional persistent OpenSkill rating auto-updated from outcomes (can seed the rank book / be a rank source); leaderboard.
- **Phase 3:** self-serve roster queue/signup; seasons; realtime live-drag/presence for the balance step; optional match-log upload → per-player stats (would generalize the match-log/stats pipeline off `tournament_id`).

## Risks / notes

- **moo_core factoring:** confirm the pure engine entry point is callable without the tournament balance job scaffolding; if it's entangled, a small refactor to expose a `balance(players, config) -> result` function is part of Phase 1.
- **Player pool:** "workspace players" = the set of players visible in the workspace (via its tournaments/registrations). Define the exact query for the rank-book player list during implementation.
- **dps↔damage role naming** must use the existing bridge so the rank book and moo_core agree on role keys.
- No tournament pollution: custom games never create `Tournament`/`Team`/`Player`/`BalancerBalance` rows.

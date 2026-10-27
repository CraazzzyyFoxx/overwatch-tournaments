# Tournament Service (`tournament-svc`)

The tournament domain: the lifecycle of a tournament from registration through check-in, bracket
generation, played encounters and final standings. It exists as its own process because it is the
only writer of the tournament tree and because it carries the system's long-running compute — bracket
and standings recomputation — which must not share a scheduling budget with the hot read paths in
`app-svc`. Like every service that writes outbox rows, it runs the shared outbox drain (see
[The transactional outbox](#the-transactional-outbox)).

It is a headless FastStream worker on RabbitMQ. It serves no HTTP and listens on no API port; every
request arrives as request/reply RPC published by the Go gateway on a `rpc.tournament.*` subject with
an `x-deadline-ms` budget, and is answered with an `{ok, data, error}` envelope. See
[`../../docs/architecture.md`](../../docs/architecture.md) for the system overview and
[`../ARCHITECTURE.md`](../ARCHITECTURE.md) for the `rpc → services → domain → repository → models`
layering.

- **Compose service:** `tournament-svc`
- **Entry point:** `serve.py`
- **Run command:** `faststream run serve:app`
- **Transport:** RabbitMQ request/reply (`rpc.tournament.*`, `rpc.tournament.admin.*`); no HTTP
- **Metrics:** Prometheus on `WORKER_METRICS_PORT` (dev 9103, prod 9103), including
  `event_loop_lag_seconds`, `db_pool_checked_out|overflow|size|max_overflow` and
  `scheduler_job_skipped_total` with `service="tournament-svc"`. The same port serves `GET /health`:
  200 once the broker connection is up and the consumers and scheduler run, 503 before that and from
  the start of shutdown (the compose healthcheck probes it)

## Responsibilities

- **Tournament lifecycle.** The status state machine, its phase schedule, and the time-driven
  automation that advances it.
- **Registration.** Player self-service registration and the admin queue behind it: approval,
  rejection, withdrawal, restoration, balancer inclusion, rank autofill, the per-workspace
  registration-status catalog, and the registration form itself.
- **Registered teams.** Captain-formed teams during registration: invites and their caps, accept /
  decline / kick / leave, captain transfer, disband, free agents, crest images.
- **Check-in and admission.** The check-in window and the single admission gate every write path
  asks — profile completeness plus subscription entitlement (Discord role / Twitch), resolved through
  the shared admission resolver.
- **Structure and brackets.** Stages, stage items and stage-item inputs; seeding, wiring and
  advancement edges; single/double elimination, round-robin and Swiss generation.
- **Encounters and results.** Games and per-participation game claims, series reports, and the result
  state machine (confirm / reopen / auto-confirm / dispute / import / cascade reset). Every result
  change takes the encounter row `FOR UPDATE`, bumps `result_version` and writes one
  `encounter.result_audit` row; results from a series claim, an admin or an import are never
  overwritten by games. The API returns participants as `teams[]` with slot numbers — no home/away —
  and bracket advancement follows the encounter's final positions.
- **Pick/ban.** The generic pick-ban engine over map and hero pools: configs, sessions, opener
  election, acting, undo, and admin overrides.
- **Standings.** Standing computation jobs and the recalculation triggered by results.
- **Organizer dashboard.** The workspace admin dashboard, its trends and the per-tournament readiness
  checklist (moved from app-service on 2026-10-23,
  [release note](../../docs/releases/2026-10-23-tournament-owns-organizer-dashboard.md)).
- **Integrations.** Challonge (fetch, import, export, push result, auto-sync) and Google Sheets
  registration feeds (mapping catalog, suggestion, preview, sync, export).
- **Division grids.** Rank-to-division grid versions, publishing/activation, portable import/export
  and marketplace import jobs.
- **Scrim rooms.** Ad-hoc rooms provisioned outside the tournament tree, then played through the same
  pre-game subjects.

## Interface

The worker subscribes to two namespaces on RabbitMQ:

| Namespace | What it carries |
| --- | --- |
| `rpc.tournament.*` | 241 typed methods, one subscriber per subject |
| `rpc.tournament.admin.*` | Generic admin CRUD (`create` / `update` / `get` / `list` / `delete`) dispatched by entity through the shared admin engine — 246 subjects in all |

Method groups:

| Group | Subject prefix | Purpose |
| --- | --- | --- |
| Public reads | `get_*`, `list_*`, `lookup_*`, `statistics_*`, `encounters_overview`, `encounters_insights`, `tournaments_facets`, `saved_view*` | Tournaments, teams, encounters, matches, stages, standings, statistics and saved encounter views |
| Computation jobs | `job_*`, `standing_recalculate` | Job status reads and manual standings recomputation |
| Registration (admin) | `reg_*`, `regstatus_*` | The registration queue, bulk operations, rank autofill, exports, status catalog |
| Registration (public) | `reg_pub_*`, `sub_me`, `sub_redeem_code` | Self-service registration, check-in, subscription status |
| Registered teams | `regteam_*` | Captain team formation, invites and invite caps, roster changes, crest images |
| Subscription config | `sub_config_*`, `sub_requirement_*` | Per-workspace provider credentials and the entitlement rule |
| Stages and brackets | `stage_*` | Activation, generation, merge, wiring, seeding, best-of, planned rounds, progress, preview |
| Encounters and results | `encounter_*`, `admin_encounter_reports_*`, `admin_match*`, `report_form_*` | Admin result writes, the result audit trail, the captain-report form, parsed-match reads, an organizer's match import by external id (`admin_match_import(s)`, with the stats warnings) |
| Captain surfaces | `captain_*` | A captain's own role, readiness, map reports, report submission, match import by external id (`captain_match_import(s)`), pick-ban state and actions |
| Pick/ban | `get_pick_ban_configs`, `admin_pick_ban_*` | Config CRUD, admin acting, opener election, session reset |
| Lifecycle | `tournament_status`, `tournament_finish`, `tournament_schedule_set` | Status transitions and the phase schedule |
| Images | `teams.image_*`, `tournaments.image_*`, `regteam_image_*` | Binary upload/delete (base64 on the wire) to S3 |
| Scrims | `scrim_*` | Ad-hoc room provisioning, claiming and closing |
| Preview access | `preview_access_*` | Pre-publication access grants |
| Challonge | `challonge_*` | Fetch, import, export, push result, team preview/apply, sync log |
| Google Sheets | `sheet_*` | Feed config, mapping catalog/suggestion/preview, sync, player export |
| Division grids | `grid_*` | Grid and version CRUD, publish/activate, portable and marketplace import |
| Organizer dashboard | `admin_dashboard`, `admin_dashboard_trends`, `tournament_readiness` | The workspace admin dashboard, its trends and the readiness checklist (see below) |

The full method list with request/response schemas is published at `/api/docs`, generated from
`src/openapi_schemas.py` (`OPERATIONS`) and `src/openapi_docs.py` (`DOCS`).

### Request handling

- **Deadlines and concurrency.** Every gateway request carries an `x-deadline-ms` header. At most
  `RPC_PREFETCH_COUNT` (default 16) such handlers run at once in the process: one process-wide pool
  of permits (`shared.rpc.deadline.configure_rpc_concurrency`), because AMQP prefetch applies per
  consumer and every subject is a consumer of its own. A request whose deadline passed while it
  waited for a permit is dropped unanswered (`rpc_stale_dropped_total`). A handler still running
  500 ms past its deadline is cancelled and its transaction rolled back
  (`rpc_deadline_cancelled_total{queue}`); the gateway has
  already answered 504. `rpc_duration_seconds{queue,code}` times every handled request. Events and
  compute jobs carry no deadline and take no permit.
- **Compute.** The three compute queues share one AMQP channel with `prefetch_count=4` per consumer,
  and one process-wide semaphore runs at most 4 bracket / standings / grid-import jobs at once.
- **Gateway timeouts.** The gateway gives the tournament public reads (`/tournaments*`,
  `/encounters*`, `/matches*`, `/teams*`, stage reads) a 30 s deadline.
- **Shutdown.** `/health` turns 503 first, the scheduler stops, then the broker gives in-flight
  handlers up to 20 s (`graceful_timeout`; compose `stop_grace_period: 30s`) before the Redis and
  quota clients close.

### Error contract

Every subject answers through `src/rpc/_helpers.py` (`_run` / `_read`), so these hold everywhere:

- A query value that does not parse (`?workspace_id=abc`, an empty `?limit=`) is 422 `unprocessable`
  with `details.fields[0].code = "invalid_query_param"`. It is never dropped as if absent.
  `workspace_id=all` means every workspace on the reads that accept it.
- A database constraint violation is 409 `conflict` (unique or exclusion) or 422 `unprocessable`
  (foreign key, check, not-null), with the constraint name in `details.constraint`. It is never 500.
- A subject that needs an identity answers 401 without one, reads included (`scrim_list_mine`,
  `ffa_stage_admin`).

Rules per area. `/api/docs` has them per subject:

- **Registration and teams.**
  - A link invite (no target user) redeems by `token` only. Accept or decline by `invite_id`
    answers 404 `invite_not_found`. Both bodies name exactly one of `token` and `invite_id` (422
    otherwise).
  - `regteam_accept` never moves a player who is already on a team (409 `already_on_team`). For a
    caller with no registration it runs the sign-up admission gate (400 refusal; 409
    `registration_changed` if the registration vanished in between).
  - Team check-in evaluates every member's admission in one batch before it takes the team lock.
    409 `roster_changed` when the roster moved in between.
  - The admission gate commits the request's session before it answers, so the entitlement and
    check-log rows survive a refusal. It ends its read transaction before any Discord or Twitch
    call, and a Discord guild whose batch lookup failed is not asked again within the request.
  - Sign-up grants the workspace's existing `player` role and seeds the role catalog only when that
    role is missing, so it no longer repairs a drifted role's permissions; role administration and
    workspace creation still do.
  - A status change through `reg_update` or `reg_create_manual` needs `registration.approve` (to
    approved) or `registration.reject` (to rejected or banned). `reg_restore` lands `approved`, so it
    needs `registration.approve` too. `reg_user_rank_history` checks its permission (403) before it
    validates (422).
  - Sheet sync re-applies only rows whose hash changed. An unchanged run counts nothing and sends no
    invalidation. It keeps ranks the sheet does not map, and one feed never syncs twice at once (the
    second run returns zero counts).
- **Results, brackets and standings.**
  - The FFA writes (`ffa_game_results_set`, `ffa_game_cancel`, `ffa_games_count_set`) and
    `ffa_lobby` refuse a duel with 409 `ffa_not_a_lobby`.
  - A games-count change or a game cancel that confirms a lobby runs every effect of a
    confirmation: the completed event, bracket advance, standings and the Challonge push. One that
    un-confirms a lobby retires every seat its old result advanced, as `encounter_reopen_result` does.
  - An admin game correction that leaves the series confirmed pushes the corrected result to
    Challonge.
  - `encounter_set_result` naming a participation outside the encounter is 422
    `not_a_participation`.
  - An admin encounter edit requests a standings recompute only when status, stage, stage item,
    round or `best_of` change.
  - `stage_seed` refuses a stage that has encounters (409) and waits for the stage row lock like the
    other stage writers. A stage-item input's `source_stage_item_id` must belong to the same
    tournament (400).
  - A standings job diff-writes its rows, so standing ids survive a recompute. A job that changed
    nothing publishes no invalidation and no achievement event. A refused Swiss round or
    requalification is logged and never fails the job.
  - A Swiss search out of budget pairs the round with the fewest rematches instead of stopping
    (under 1 s per call).
  - A job that was redelivered 3 times while running is marked `failed`.
- **Integrations.**
  - Challonge import and export answer real errors, never a 200 with `{error}`: 404 for an unknown
    tournament, 422 when it has no Challonge source, 409 while an import or export of it is
    already running (an admin request waits 3 s for it), and 503 `challonge_unavailable` when
    Challonge is unreachable, times out, rate-limits or fails.
  - On every Challonge-calling route, a Challonge 404 is 404 `challonge_not_found`.
  - A sync tick writes nothing for a match Challonge did not change: no log row, no recompute, no
    invalidation. Such a match counts as `skipped`, and `matches_synced` counts real writes only.
    The sync-log `limit` is clamped to 1..200, and `error_message` is `"<ExceptionType>: <message>"`.
  - Image uploads: base64 over the 5 MiB cap, or malformed, is 422. The gateway caps the multipart
    body at 5 MiB + 64 KiB.
  - The old image is deleted only after the new URL commits, and a delete clears the row before it
    touches S3. A failed S3 cleanup is logged, not an error. Tournament image replies include
    `rules`.
  - Division grids: an id the caller cannot see is 404 (the permission check, 403, comes after).
    `division_grid.read` holders read versions and mappings. A system grid is read-only: every write
    to it, its versions or tiers, and a mapping from one of its versions, is 403
    `division_grid_read_only` (copy it with `grid_workspace_create(from_version_id)` instead). A
    workspace's own rows that point at it stay allowed: activating a system version as the workspace
    default, and mapping the workspace's own versions onto one. A portable import validates every
    version (400). A stale import job is requeued after 15 minutes, and marketplace conflicts are 409
    or 404.
  - Tournament link writes refresh the public overview at once. Generated slugs skip retired
    (redirect) slugs.
- **Public reads.**
  - `list_tournaments`: `status` may repeat (`?status=live&status=playoffs` matches either), and
    `per_page=-1` returns at most 500 rows.
  - `lookup_tournaments`, `statistics_history` and `statistics_division` never list a hidden
    workspace's tournaments.
  - `list_teams?sort=group|placement` paginates, lists teams without a group or placement last, and
    its `total` matches the rows.

### Organizer dashboard

Three authenticated reads (`src/rpc/dashboard.py` over `src/services/dashboard/`), routed by the gateway's
`tournament.DashboardRoutes` (`gateway/internal/tournament/dashboard_routes.go`):

| HTTP | Subject | Gate |
| --- | --- | --- |
| `GET /api/v1/admin/dashboard?workspace_id=` | `rpc.tournament.admin_dashboard` | Any of `tournament.read`, `team.read`, `match.read`, `user.read`, `achievement.read` in the workspace; `workspace_id` is required even for a superuser (422 absent) |
| `GET /api/v1/admin/dashboard/trends?workspace_id=[&discipline=]` | `rpc.tournament.admin_dashboard_trends` | `tournament.read` in the workspace; `discipline` optional (absent or `all`: every game, an unknown code is 404 `discipline_not_installed`) |
| `GET /api/v1/admin/tournaments/{id}/readiness` | `rpc.tournament.tournament_readiness` | `tournament.read` or `team.read` in the tournament's workspace; no hidden-tournament gate |

Each granted permission unmasks its field group and a missing one yields `null`, never zero:
`tournament.read` the setup, bracket, log and recalculation fields (and the dashboard timeline), `team.read` the
registration, pool, balance and draft fields, `match.read` the result backlog and log coverage, `achievement.read` the
evaluation status.

- **Dashboard** (`overview.py`): one card per unfinished tournament plus each completed one still inside its 14-day
  wrap-up window whose wrap-up is not done, the schedule boundaries of the next 7 days and every overdue phase
  start, the work queue derived from the masked cards, and the backlog of the other tournaments. Whether a wrap-up
  is done is decided on unmasked data, so a card does not depend on who is looking.
- **Trends** (`trends.py`): the workspace's last 10 finished, public, non-league tournaments, one point each.
- **Readiness** (`readiness.py`): the hub's living checklist for one tournament, in one statement; a
  dashboard card's readiness comes from the rows the dashboard already fetched.

Besides this service's own schemas they read `achievements.evaluation_run` (the newest run's status) and
`achievements.rule` (whether the tournament's game has an enabled rule), log coverage through `encounter.has_logs`,
which is derived from game-bound `stats.match` observations (only duels count: a lobby never produces a match log),
`balancer.balance`, `draft.session`, and the roster's player identities (`players.user`, `players.social_account`,
`public.workspace_member`).

### Durable queues consumed

| Queue | Exchange | Payload |
| --- | --- | --- |
| `tournament_bracket_jobs` | `tournament.compute` | Bracket generation / regeneration job |
| `tournament_standings_jobs` | `tournament.compute` | Standings computation job |
| `division_grid_import_jobs` | `tournament.compute` | Marketplace grid import job |
| `cache_invalidation_tournament_service` | `cache.invalidation` | A `CacheInvalidatedEvent` from any service's outbox (`cache.invalidated.#`): re-bumps only the shared cache generations whose commit-time bump was lost (5 min message TTL, own DLQ) |
| `tournament_standings_invalidated` | `tournament.events` | `stats-service`'s door into the standings path (a parsed log landed): requests the same coalesced standings job an in-service write requests |
| `match.ingested.tournament` | `match.ingested` | Ingest evidence from `stats-service`: the match layer decides (`logs_official`, owner policy) and journals one `match_ingested` receipt (10 min TTL, own DLQ) |
| `tournament_challonge_push` | `tournament.events` | A confirmed result to push to Challonge; skipped when the encounter's `result_version` moved on or the link is gone, requeued on a transport error, Challonge 429/5xx or a transient database error, dead-lettered otherwise (own channel, `prefetch_count=1`; no transaction is open during the HTTP call) |
| `tournament_pick_ban_room_open` | `tournament.events` | A mix match started with hero bans (balancer-service's Start match): runs the room healer on its encounter, which opens the room from the preset Start froze on the lobby; idempotent, dead-lettered on failure (10 min TTL) |

The three compute queues run on a dedicated AMQP channel with `prefetch_count=4` per consumer, so a
burst of recomputes cannot occupy the RPC consumers' QoS slots, and one process-wide semaphore runs
at most 4 of their jobs at once (see [Request handling](#request-handling)). Each has a dead-letter
queue, declared on startup.

### Domain events published

All of these go through the outbox, never directly from the request transaction:

| Routing key | Exchange | Emitted when |
| --- | --- | --- |
| `cache.invalidated.tournament.{tournament_id}` | `cache.invalidation` | A write staled tournament resources another service caches (`publish_tournament_invalidation`): a `CacheInvalidatedEvent` naming them, the durable copy of the commit-time generation bump |
| `tournament.state.changed` | `tournament.events` | Status transition (manual or automatic); consumed by `analytics-worker`, which creates the compute job of a `completed` tournament |
| `tournament.registration.approved` | `tournament.events` | Registration approved |
| `tournament.registration.rank_check_requested` | `tournament.events` | Registrant asked to re-check their profile |
| `tournament.encounter.completed` | `tournament.events` | Encounter result confirmed |
| `tournament.encounter.challonge_push_requested` | `tournament.events` | A write left a Challonge-linked encounter confirmed (every confirm path, corrections included); one per `result_version`, consumed by this service's `tournament_challonge_push` |
| `tournament.compute.division-grid-import` | `tournament.compute` | Grid import job dispatched |
| `pickup_mix_changed` (queue) | default (`""`) | A mix match's hero room completes, is cancelled, reopened or reset — the Pre-game ↔ Live crossing (`realtime_commit._announce_mix_overview_change`); `PickupMixChangedEvent{change: "pick_ban"}`, consumed by discord-service |

A rejected registration publishes no domain event: nothing consumed one. The registrant's
`registration.rejected` notification and the realtime invalidation still go out.

Standings have one path: `jobs_service.request_standings_recalculation` creates the job row and its
`tournament.compute.standings` outbox row in the transaction of whatever moved the inputs — a result
write, a structure edit, a finished bracket job, an organizer's recompute — coalesced per tournament
(`idempotency_key` plus a generation counter, and one request per transaction). Nothing in this
service publishes `tournament.standings.invalidated`; it is only the cross-service door into that
same call.

Encounter-completed and recalculation events are suppressed for scrim containers: a scrim has no
stage items, seeds or rosters, and recalculating one invents standings rows for its rosterless teams.

### Realtime topics published

| Topic | Durable | Content |
| --- | --- | --- |
| `tournament:{id}:bracket` | yes | `tournament.updated` with a `reason` of `bracket_changed`, `results_changed`, `structure_changed` or `registration_changed` |
| `encounter:{id}:map-veto` | yes | `map_veto.updated` — a bare signal; subscribers refetch the pool |
| `encounter:{id}:pick-ban:hero` | yes | `pick_ban.updated` — same shape, separate topic so a hero-only change never wakes map-veto subscribers |
| `workspace:{id}:subscriptions` | no | `subscription.updated` from the shared admission resolver when a gate flips a verdict — a Redis-only signal with `event_id=0`, so clients refetch on subscribe rather than replay |

Durable means the event is persisted as a `realtime.workspace_event` row inside the same transaction
as the change that caused it, then published to Redis after commit for the gateway to relay to
WebSocket subscribers — so a client that reconnects can replay what it missed. Persistence and
publishing are staged by `shared.services.realtime_transaction.register_realtime_update`, which means
a rolled-back transaction publishes nothing. The non-durable signal is best-effort: it is dropped if
Redis is unavailable and logged, nothing more.

Multiple reasons registered for one tournament in a single transaction are merged into the strongest
one before the row is written, so a burst of writes yields one event, not one per statement.

### Pre-game room reads and the room healer

`GET …/pick-ban/{kind}/state` is a **pure read**: it takes no row lock, writes nothing, commits
nothing and publishes nothing. It renders the room as it stands. (It used to create the session,
settle an expired step, append a hero round, repair game projections and open freeplay positions
on the way past — which put every viewer's poll behind the encounter's `FOR UPDATE` and so behind
the captains and behind each other.)

Every heal now belongs to `PickBanActionService.reconcile_room`, which prechecks unlocked
(`room_owes_write`), locks encounter → session, applies the owed heals in that order, publishes one
signal per kind it changed and commits once. It is driven from three places
(`services/encounter/room_reconcile.py`):

- a post-commit trigger staged by `emit_pick_ban_update`, so every room write heals the room it
  touched; writes that move a room without signalling it (team changes, stage activation, pick-ban
  config edits) stage it themselves. A config edit re-checks only rooms that are fully seated with
  every seat ready, one transaction per room;
- the `pick_ban_room_due` tick, for the only change nobody writes — a step's timer running out. A
  room whose steps fail to build counts as due, so the healer isolates and logs it instead of
  failing the tick;
- the `pick_ban_room_sweep` backstop, every 5 minutes, for a room left owing a heal anyway (a missed
  tick, a writer that died after its commit). An SQL prefilter skips rooms that cannot owe anything
  (no live session, no pick-ban config at the tournament level or on the room's own stage, and an
  open game already) and closed scrim rooms; each room it visits gets its own transaction.

Both sweeps take the encounter with `SKIP LOCKED`, which is what makes running them on every
replica safe. Clients do not need to poll for progress: the reconcile signals the room when it
lands. Paused steps still never expire.

### Scheduled work

| Job | Interval | What it does |
| --- | --- | --- |
| `event_outbox_drain` | 1 s | Drains `public.event_outbox` (batch of 100, any producer's rows) |
| `pick_ban_room_due` | 1 s | Settles pick-ban rooms whose step timer ran out (`SKIP LOCKED`) |
| `pick_ban_room_sweep` | 5 min | Backstop: reconciles rooms still owing a heal (see above) |
| `auto_transition_tournaments` | 30 s | Applies due phase transitions |
| `registration_google_sheet_sync` | 5 min | Pulls due Google Sheets registration feeds |
| `challonge_active_sync` | `CHALLONGE_AUTO_SYNC_INTERVAL_MINUTES` (default 5) | Pulls Challonge → local for active tournaments |
| `division_grid_import_recovery` | 5 min (plus once at startup) | Requeues import jobs still `running` 15 minutes after they started (their worker was lost to a restart) |
| `realtime_workspace_event_purge` | daily, 04:00 | Deletes `realtime.workspace_event` rows on `tournament:%:bracket`, `%:invalidation` and `%:chat` older than 7 days |
| `chat_purge` | daily, 04:00 | Deletes `chat_message` rows older than 90 days and `chat_mute` rows whose `muted_until` elapsed over 90 days ago |
| `event_outbox_purge` | daily, 04:00 | Deletes `published` `public.event_outbox` rows older than 7 days. The table is shared and only this service schedules it; `dead` rows are kept |
| `computation_job_purge` | daily, 04:00 | Deletes terminal (`succeeded` / `failed` / `superseded`) `computation_job` rows created over 30 days ago |
| `challonge_sync_log_purge` | daily, 04:00 | Deletes `challonge_sync_log` rows older than 30 days |

The daily jobs are cron jobs at 04:00 in the scheduler's local time, with up to 10 minutes of jitter
and a one-hour misfire grace, so a worker redeployed more often than daily still runs them. The
three new purges delete 5000 rows per transaction. A run APScheduler skips (still running, or
missed) counts in `scheduler_job_skipped_total{service,job_id,reason}`.

Registration windows and invite caps are *not* scheduled: registration openness is evaluated from the
`REGISTRATION` phase-schedule row on every read and write, and invite caps are reset on demand
through `regteam_invite_cap_reset`.

## The tournament state machine

Status lives on `tournament.tournament.status`. The machine itself is
[`shared/core/tournament_state.py`](../shared/core/tournament_state.py); this service is the only
process that applies it.

```
REGISTRATION ──▶ CHECK_IN ──▶ DRAFT ──▶ LIVE ──▶ PLAYOFFS ──▶ COMPLETED ◀──▶ ARCHIVED
      │             │            │        │                       ▲
      └─────────────┴────────────┴────────┴───────────────────────┘
                    (forward skips legal; rollback edges omitted)
```

- `CHECK_IN` is optional and `DRAFT` applies only to `team_formation="draft"` tournaments, so forward
  transitions may skip phases. `REGISTRATION → LIVE` is a legal single hop.
- Rollback edges exist for the phases before the current one (e.g. `CHECK_IN → REGISTRATION`,
  `LIVE → DRAFT`), so an organizer can reopen a phase without the superuser `force` bypass.
- `LIVE → COMPLETED` is direct; `PLAYOFFS` is an optional stop in between and only leads to
  `COMPLETED`. `COMPLETED ↔ ARCHIVED` is reversible.
- `is_finished` is derived, not set independently: it is true exactly for `COMPLETED` and `ARCHIVED`.

**What triggers a transition.** Two things, and only two:

1. **An admin**, via `rpc.tournament.tournament_status` (or the legacy `tournament_finish` toggle).
   The target is validated against the transition matrix unless a superuser passes `force`. A manual
   transition also sets `auto_transitions_enabled = false` in the same transaction, so the automation
   never fights an admin decision — re-enabling it is an explicit edit.
2. **The 30-second automation tick**, from `tournament_phase_schedule` rows. Each row's `starts_at`
   is the moment its phase begins; `ends_at` never moves the status, it only closes that phase's
   action window early (`is_within_phase_window`).

**What the tick will and will not do.** It moves forward only, and only *out of* `REGISTRATION`,
`CHECK_IN` or `DRAFT` — so the furthest it can take a tournament is `LIVE`. `PLAYOFFS` and
`COMPLETED` depend on the actual course of play and stay manual. Tournaments with
`auto_transitions_enabled = false` are never touched. When several rows are due at once the tick
picks the *latest* due phase and jumps straight to it rather than stepping through the intermediate
ones.

Candidates are selected with one coarse SQL filter, then each is re-locked
`FOR UPDATE SKIP LOCKED` in its own session and re-checked under the lock before transitioning — one
transaction per tournament, so a failure on one never aborts the rest of the tick and two replicas
never transition the same row twice.

Reaching `LIVE` has one side effect: if the target stage has ready inputs and no encounters yet, the
service enqueues a bracket job (`activate_and_generate` or `generate_stage`) so the group stage
starts without a second admin action.

## The transactional outbox

Every domain event this service emits is written as a `public.event_outbox` row **inside the same
transaction as the state change that caused it** (`enqueue_outbox_event`), and published to RabbitMQ
later by a separate sweeper. This is the standard remedy for the dual-write problem: publishing to
the broker from inside a request would either emit an event for a transaction that then rolls back,
or commit a change whose event was lost to a broker hiccup. With the outbox, the event and the change
commit or fail together, and the guarantee is **at-least-once delivery of exactly the events whose
transactions committed**. Consumers must therefore be idempotent, through their own state (a job
row's status, a version fence, a cache key that is simply dropped again): no consumer dedupes on the
`x-event-id` header.

The drain (`shared.messaging.outbox.drain_outbox`, scheduled every second by `serve.py` and by every
other service that writes outbox rows) is one tick of the relay:

1. Reads the age of the oldest `pending` or `failed` row in the table (backing-off rows included) into the gauge
   `outbox_oldest_pending_age_seconds`, then selects up to 100 rows in `pending` or `failed` state whose
   `next_attempt_at` has passed, ordered by `created_at`, with `FOR UPDATE SKIP LOCKED`. The skip-locked clause is
   what makes concurrent drains safe: every replica of every producing service runs one, two drains never claim the
   same row, and neither blocks on the other.
2. Publishes each row persistently, each publish under a 10 s timeout, and marks it `published`,
   then commits the whole batch once. The batch stays locked until that commit, so no other drain can
   take a row this one already published; a crash between a publish and the commit replays the batch.
   The batch starts no publish after 20 s, and its first publish timeout ends it, so the commit lands within 30 s,
   inside pgBouncer's 60 s `idle_transaction_timeout`; rows it did not try stay `pending` for the next tick.
3. On a publish failure (a timeout included), marks the row `failed`, increments `attempts`, records
   `last_error` and sets `next_attempt_at` to now plus an exponential backoff of `2^(attempts-1)`
   seconds, capped at 300 s. The 20th failure marks the row `dead` instead: no drain takes it again,
   it stays in the table for inspection, and it counts in `outbox_dead_total` (alert
   `OutboxDeadEvents`) with an ERROR log.

Published rows are kept 7 days, then deleted by the daily `event_outbox_purge` (see
[Scheduled work](#scheduled-work)); `pending`, `failed` and `dead` rows are never purged.

**No single drain.** `event_outbox` is one global table with no per-service partition, and any drain
publishes any row. Since every producing service runs the drain, `tournament-svc` is no longer a hard
dependency for other services' events: while it is down, the other drains keep publishing.

## Role ontology and team formats

Tournament creation accepts `discipline` (default `overwatch`), validated against the workspace's
`disciplines_enabled`. The tournament owns a copy of the workspace default or module preset, not
a live inherited slot map. Read or replace it through
`GET|PUT /api/v1/admin/tournaments/{tournament_id}/team-format`; workspace templates use
`GET|PUT /api/v1/workspaces/{workspace_id}/team-formats/{discipline}`. Both use
`TeamFormatRead` / `TeamFormatWrite`; tournament create/update/read no longer carry `roster_slots_json`.

Players and registration APIs carry leaf `RoleRef {dimension, role, parent}` values. The parent is
derived, never trusted on input. Workspace sub-role codes are `<parent>_<slug>`; the retained
`/api/v1/admin/player-sub-roles` API exposes the suffix as `slug` and refuses parent changes.
Public form answers deliberately keep `{role, subrole?, is_primary, top_heroes?}` with suffixes.
The `owt-1` player-pool export uses leaf refs in `owt.primary_role` and `owt.roles[].role`;
its frozen solver `stats.classes` remains unchanged.
See the [P2 release guide](../../docs/multi-game-p2-roles-release.md) for errors and cutover steps.

## Discipline grids and identity providers

Every grid has `discipline`; its tiers use `native_rank_min/max` for optional native-ladder
bounds and `rank_min/max` for organizer ranks. Grid creation takes an enabled discipline
(omission selects the workspace's first enabled one) and an optional `slug` (derived
`{discipline}-grid`, `-2`, `-3`… when omitted). A game with a module ladder seeds a new grid's
published v1 with it (Overwatch 45 tiers, LoL 31, Deadlock 66); `from_version_id` seeds it instead
with a published copy of a version of this workspace or a system grid of the same game (422
`division_grid_discipline_mismatch` otherwise, 409 for a draft). Creation never activates. An event
without a usable grid of its own falls back to that ladder; a ladder-less game needs organizer-entered
tiers, and creating its tournament without a usable version fails with 422 `division_grid_required`
before persistence. A same-discipline event pin is sufficient without activating a workspace default.

Every workspace has its own grid of each enabled game with a ladder (`{discipline}-default`, named
after the game, v1 = the ladder): `shared.services.division_grid.provisioning` creates it when a
workspace is created or enables the game, and `defgrid01` backfilled existing workspaces. A game the
workspace already has a grid of (archived included) is skipped. v1 becomes the game's default unless
one is set already or a system grid of the game is in force; off a system grid moves only a game new
to the workspace (its creation, the game just enabled) with no tournaments of it, so nothing already
read is renumbered. The workspace grid list carries each grid's
`tournament_count` (tournaments pinned to any of its versions).

`workspace_division_grid_default` assigns versions independently by `(workspace_id, discipline)`.
Activation/deletion affects only the matching assignment, never another game or a valid event pin.
Workspace reads distinguish `default_division_grid_versions` (explicit IDs) from
`effective_division_grid_versions` (persisted version/tier payloads, including same-game system
fallback). Missing versions are omitted. Old scalar fields and writable-map workspace payloads
are rejected; use grid activation. The old physical workspace pointer is gone (`legacy01`).

Portable imports read `division-grid/v1` as Overwatch, translating `ow_rank_min/max` to native
bounds; a v1 document declaring a discipline is invalid. Exports write `division-grid/v2` with
`discipline` only. Historical marketplace fingerprint keys/digests remain unchanged; this is not
an old-wire alias.

`TournamentRead.identity_provider` is computed from its module: `battlenet` for OW, `riot` for
LoL. Backend `default_schema(provider)` requires the provider. The default form identity,
roster/chat display handle and parser matching follow it; Riot IDs preserve inner name spaces,
normalize spacing around `#`, and match case-insensitively. Names are 3–16 non-`#` characters,
tags 3–5 alphanumeric characters. A known-owner form cannot generate/save a Battle.net default
while owner metadata is pending or failed; a loaded existing form remains intact.

Native registration enrichment and autofill's `ow` stage (persisted key unchanged) run only for disciplines
declaring a native layer: a Battle.net game reads OverFast snapshots (week composite, peak, smurf
selection), any other game its module's `native_ranks` (LoL: Solo/Duo, one value for every source).
Profile visibility remains OW-specific and reads only Battle.net accounts. Optional manual registration
identities remain optional. Fresh writers initialize identity collections before flush; persisted
readers retain eager loading. P7 owns primary-identity reconciliation, provider-explicit workspace
upsert and generic identity wire/UI renaming (including retained `battle_tag`/`smurf_tags`);
P8 consumes them. See the [P3 release guide](../../docs/multi-game-p3-ranks-release.md) for storage,
cutover and known limitations.

## Data owned

One PostgreSQL database, one SQLAlchemy metadata in [`../shared/`](../shared/README.md). Domain
boundaries are Postgres schemas; this service has no migrations of its own — there is one Alembic
project at [`../migrations/`](../migrations/).

**Writes:**

- **`tournament`** — the structure: `tournament`, `tournament_phase_schedule`, `stage`, `stage_item`,
  `stage_item_input`, `stage_round_best_of`, `team`, `player`, `player_role`,
  `bracket_encounter` (an encounter's stage, stage item and round), `encounter_link`,
  `encounter_report_form`, the `pick_ban_config*` template tables, `standing`, `recalculation_state`,
  `computation_job`, the four `challonge_*` mapping/log tables, `scrim_room`,
  `tournament_preview_access`, `tournament_link`, `slug_redirect`, `encounter_saved_view`.
- **`encounter`** — the match layer, written through the single writers in
  [`shared/services/encounter/`](../shared/services/encounter/): `encounter`, `team` (participations)
  with `team_member` / `team_member_role (team_member_id, dimension_id, role_id)`, `game` and `game_team`, `game_claim` /
  `game_claim_result`, `team_report` / `team_report_result`, `scoring_rule`, `result_audit`,
  `readiness`, `room_event`, and the `pick_ban_session` / `pick_ban_entry` / `pick_ban_submission`
  tables of the pre-game room. Seats change only through `participants.py`, results only through
  `result.py`.
- **`catalog.role`** — workspace sub-role administration; module roles are projected at app startup.
- **`roster`** — tournament-owned `team_format`, `team_format_dimension` and `format_role_rule`.
- **`registration`** — the registration side of the tournament domain: `registration`, `role`,
  `role_entity`, `form`, `form_version`, `form_template`, `status`, `team`, `team_invite`,
  `identity`, `google_sheet_feed` / `_binding`. Balancing itself (`balancer`, `mix`, `draft`)
  belongs to `balancer-service`.
- **`subscriptions`** — `provider_config` and `requirement` through the admin RPCs, plus the
  `entitlement` and `check_log` rows the admission gate writes as it resolves verdicts.
- **`public`** — division grids and their versions/mappings/import jobs, plus `event_outbox` (written
  and drained by every producer; only this service purges its published rows).
- **`realtime`** — `workspace_event` rows for the topics listed above, and the daily purge of stale
  bracket events.

**Reads only:** `players` (player identity behind rosters and registrations), `auth` (actor columns
on audit rows), `public.workspace` / `public.workspace_member` (tenancy anchors), `catalog.entity`
(characters and maps for pick/ban), `catalog.discipline` / `catalog.role_dimension` (the owner's
ontology), `matches` (parsed match rows surfaced by the admin match reads), and for the organizer
dashboard `achievements.evaluation_run` / `achievements.rule`, `stats.match` (log coverage),
`balancer.balance` and `draft.session`. Legacy
`tournament.player_sub_role` and role columns have no runtime readers or writers.

Entity diagrams: [tournament](../../docs/database_erd.md#tournament--tournament-casual),
[encounter](../../docs/database_erd.md#encounter--encounter),
[registration](../../docs/database_erd.md#registration--registration),
[division_grid](../../docs/database_erd.md#division_grid--public),
[subscriptions](../../docs/database_erd.md#subscriptions--subscriptions),
[platform](../../docs/database_erd.md#platform--public-realtime).

## Dependencies

- **PostgreSQL** — the shared ORM; all of the above.
- **RabbitMQ** — RPC transport, the three durable compute queues, the recalculation-event queues, and
  the outbox's publish target.
- **Redis** — realtime pub/sub for the gateway's WebSocket fan-out, the shared cache generations, and
  the `cashews` response cache (`api_cache_url` = db 5, `backend_cache_url` = db 6) keyed by them.
- **S3** — team logos, tournament covers/logos, registered-team crests.
- **Challonge API** — bracket import/export and the auto-sync pull, via the outbound `proxy` container.
- **Google Sheets** — registration feeds fetched as CSV exports over HTTPS.
- **discord-service** (RabbitMQ RPC) — Discord roles for Boosty entitlements and team guild
  membership; this service holds no bot token. An outage refuses (`provider_unavailable`).
- **Twitch API** — Twitch entitlement verification, via the outbound `proxy` container.

## Configuration

[`../env/tournament.env`](../env/), inheriting [`../env/common.env`](../env/). The settings that
actually change behaviour:

| Setting | Effect |
| --- | --- |
| `CHALLONGE_API_KEY`, `CHALLONGE_USERNAME` | HTTP Basic credentials. Missing → Challonge answers 401, surfaced as `challonge_error`; the auto-sync job no-ops with a single warning |
| `CHALLONGE_AUTO_SYNC_ENABLED` | Kill switch for the background Challonge pull |
| `CHALLONGE_AUTO_SYNC_INTERVAL_MINUTES` | Interval of that pull (default 5) |
| `TWITCH_CLIENT_ID` | Twitch entitlement provider. **Missing does not fail loudly**: Twitch resolves `unknown` (`twitch_client_not_configured`), which fails open, and a Twitch-gated tournament admits everybody |
| `WORKER_METRICS_PORT` | Prometheus scrape port (9103 in both environments) |
| `RPC_PREFETCH_COUNT` | How many gateway RPC handlers run at once in the process (default 16; also each RPC consumer's AMQP prefetch). Compute jobs have their own fixed cap of 4 |
| `REDIS_URL`, `RABBITMQ_URL` | Transport endpoints |

## Running

Local, from `backend/tournament-service/` with the shared package importable:

```bash
faststream run serve:app
```

In compose the dev container adds `--reload --reload-dir /app/tournament-service --reload-dir
/app/shared` with forced polling (`WATCHFILES_FORCE_POLLING=true`), and bind-mounts both the service
and `backend/shared`. Both environments' healthcheck probes `http://localhost:9103/health`, so
`make prod-up` (`up --wait`) waits for the consumers, and `stop_grace_period: 30s` covers the broker's 20 s
drain. No profile: the service starts with the default stack. Resource ceilings are 0.5 CPU /
512 MB in dev and 1.0 CPU / 768 MB per replica in production, 2 replicas at `PROD_SIZE=small|medium`
and 4 at `large` (`Makefile`).

## Operational notes

- **Replicas.** The shared mutable state — the outbox drain, the auto-transition tick and the
  pick-ban sweeps — is claimed with `SKIP LOCKED`, so a second replica cannot double-publish,
  double-transition or double-heal. The APScheduler jobs are not leader-locked, though: every replica
  runs every job, and the locking makes that correct rather than free. The daily purges are batched
  deletes, harmless to run twice.
- **Shutdown abandons in-flight scheduled jobs** (`scheduler.shutdown(wait=False)`; the asyncio
  executor cancels them). This is deliberate and safe: an abandoned outbox batch rolls back and is
  republished on the next tick (at-least-once, as always), and each sheet feed or Challonge
  tournament commits once at its end (a Challonge import's per-match savepoints only isolate a
  failing match), so an interrupted one rolls back whole and the next tick re-runs it. In-flight RPC
  and compute handlers get the broker's 20 s to finish.
- **Dead-letter queues** exist for every consumed queue and are declared at startup. There is no
  automatic DLQ replay; stuck jobs and dead-lettered Challonge pushes need manual inspection (the
  organizer's manual "push result" re-sends one).
- **Outbox retries stop at 20.** A permanently unroutable event backs off to one attempt every 300 s,
  then turns `dead` and leaves the drain's working set; dead rows stay in `event_outbox` for
  inspection. Alerts: `OutboxBacklogOld` (oldest pending row over 5 minutes), `OutboxDeadEvents`.
- **Stale import-job recovery** runs at startup and every 5 minutes, so a restart mid-import does not
  strand a marketplace grid import for more than 15 minutes.
- **Cache invalidation.** A write's commit bumps the shared cache generation of every resource it
  staled (Redis `cachegen:*`) before `commit()` returns, so neither the reply nor a client's refetch
  can read the old entry; the realtime publish after it is fire-and-forget, on background tasks
  anchored in a module set. That bump is one attempt. Its durable copy is the `cache.invalidated`
  outbox row: this service's consumer (`cache_invalidation_tournament_service`), like every caching
  service's, re-bumps a generation only when it was not bumped since the event (values are
  `<hex>.<bump_ms>`), so a lost bump is redone without orphaning entries cached after it. TTLs
  (5 min for most reads, 30 s for match detail) bound the reads no generation keys.
- **Cached reads.** The generation-keyed reads cache the response's wire dict, never a pickled
  model, so a wire change bumps the key's version and the cache starts cold once after that deploy.
  `entities` enter a key whitelisted per read and sorted. The encounter list, overview and insights
  entries are shared across viewers (only `scope=my_team` keys the viewer; the overview's `my_team`
  count is added per viewer), and a cold list or overview is built once per burst (`single_flight`).
- **Recalculation cost.** Every confirmed encounter result enqueues a standings job for its
  tournament. Scrim containers are excluded at the enqueue site, not in the worker, precisely because
  a job that is created, delivered and discarded is a permanent per-report cost that looks healthy.
  An admin encounter edit enqueues one only when status, bracket position or `best_of` changed, and
  a Challonge tick only for a match Challonge changed. A job whose table did not change writes no
  standings rows and publishes no invalidation.

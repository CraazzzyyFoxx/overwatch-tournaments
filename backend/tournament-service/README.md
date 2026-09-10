# Tournament Service (`tournament-svc`)

The tournament domain: the lifecycle of a tournament from registration through check-in, bracket
generation, played encounters and final standings. It exists as its own process because it is the
only writer of the tournament tree and because it carries the system's long-running compute — bracket
and standings recomputation — which must not share a scheduling budget with the hot read paths in
`app-svc`. It also hosts the single transactional-outbox sweeper for the whole backend (see
[Operational notes](#operational-notes)).

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
- **Metrics:** Prometheus on `WORKER_METRICS_PORT` (dev 9103, prod 9103)

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
- **Encounters and results.** Captain reports per team per map, the result state machine
  (confirm / reopen / auto-confirm / dispute / import / cascade reset) with a full audit row per
  transition, and downstream bracket advancement.
- **Pick/ban.** The generic pick-ban engine over map and hero pools: configs, sessions, opener
  election, acting, undo, and admin overrides.
- **Standings.** Standing computation jobs and the recalculation triggered by results.
- **Integrations.** Challonge (fetch, import, export, push result, auto-sync) and Google Sheets
  registration feeds (mapping catalog, suggestion, preview, sync, export).
- **Division grids.** Rank-to-division grid versions, publishing/activation, portable import/export
  and marketplace import jobs.
- **Scrim rooms.** Ad-hoc rooms provisioned outside the tournament tree, then played through the same
  pre-game subjects.
- **Transactional outbox sweeper.** The backend's only `event_outbox` drain.

## Interface

The worker subscribes to two namespaces on RabbitMQ:

| Namespace | What it carries |
| --- | --- |
| `rpc.tournament.*` | ~180 typed methods, one subscriber per subject |
| `rpc.tournament.admin.*` | Generic admin CRUD (`create` / `update` / `get` / `list`) dispatched by entity through the shared admin engine |

Method groups:

| Group | Subject prefix | Purpose |
| --- | --- | --- |
| Public reads | `get_*`, `list_*`, `lookup_*`, `statistics_*`, `owal_*`, `encounters_overview`, `tournaments_facets`, `saved_view*` | Tournaments, teams, encounters, matches, stages, standings, statistics and saved encounter views |
| Computation jobs | `job_*`, `standing_recalculate` | Job status reads and manual standings recomputation |
| Registration (admin) | `reg_*`, `regstatus_*` | The registration queue, bulk operations, rank autofill, exports, status catalog |
| Registration (public) | `reg_pub_*`, `sub_me`, `sub_redeem_code` | Self-service registration, check-in, subscription status |
| Registered teams | `regteam_*` | Captain team formation, invites and invite caps, roster changes, crest images |
| Subscription config | `sub_config_*`, `sub_requirement_*` | Per-workspace provider credentials and the entitlement rule |
| Stages and brackets | `stage_*` | Activation, generation, merge, wiring, seeding, best-of, planned rounds, progress, preview |
| Encounters and results | `encounter_*`, `admin_encounter_reports_*`, `admin_match*`, `report_form_*` | Admin result writes, the result audit trail, the captain-report form, parsed-match reads |
| Captain surfaces | `captain_*` | A captain's own role, readiness, map reports, report submission, pick-ban state and actions |
| Pick/ban | `get_pick_ban_configs`, `admin_pick_ban_*` | Config CRUD, admin acting, opener election, session reset |
| Lifecycle | `tournament_status`, `tournament_finish`, `tournament_schedule_set` | Status transitions and the phase schedule |
| Images | `teams.image_*`, `tournaments.image_*`, `regteam_image_*` | Binary upload/delete (base64 on the wire) to S3 |
| Scrims | `scrim_*` | Ad-hoc room provisioning, claiming and closing |
| Preview access | `preview_access_*` | Pre-publication access grants |
| Challonge | `challonge_*` | Fetch, import, export, push result, team preview/apply, sync log |
| Google Sheets | `sheet_*` | Feed config, mapping catalog/suggestion/preview, sync, player export |
| Division grids | `grid_*` | Grid and version CRUD, publish/activate, portable and marketplace import |

The full method list with request/response schemas is published at `/api/docs`, generated from
`src/openapi_schemas.py` (`OPERATIONS`) and `src/openapi_docs.py` (`DOCS`).

### Durable queues consumed

| Queue | Exchange | Payload |
| --- | --- | --- |
| `tournament_bracket_jobs` | `tournament.compute` | Bracket generation / regeneration job |
| `tournament_standings_jobs` | `tournament.compute` | Standings computation job |
| `division_grid_import_jobs` | `tournament.compute` | Marketplace grid import job |
| `tournament_changed_tournament_service` | `tournament.changed` | Cache invalidation + realtime fan-out (5 min message TTL) |
| `tournament_standings_invalidated` | `tournament.events` | Enqueues a standings recomputation |

The three compute queues run on a dedicated AMQP channel with `prefetch_count=4`, so a burst of
recomputes cannot occupy the RPC channel's QoS slots. Each has a dead-letter queue, declared on
startup.

### Domain events published

All of these go through the outbox, never directly from the request transaction:

| Routing key | Exchange | Emitted when |
| --- | --- | --- |
| `tournament.changed.{tournament_id}` | `tournament.changed` | Any structure / results / registration change |
| `tournament.state.changed` | `tournament.events` | Status transition (manual or automatic) |
| `tournament.registration.approved` | `tournament.events` | Registration approved |
| `tournament.registration.rejected` | `tournament.events` | Registration rejected |
| `tournament.encounter.completed` | `tournament.events` | Encounter result confirmed |
| `tournament.compute.division-grid-import` | `tournament.compute` | Grid import job dispatched |

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

### Scheduled work

| Job | Interval | What it does |
| --- | --- | --- |
| `event_outbox_drain` | 1 s | Drains `public.event_outbox` (batch of 100) |
| `auto_transition_tournaments` | 30 s | Applies due phase transitions |
| `registration_google_sheet_sync` | 5 min | Pulls due Google Sheets registration feeds |
| `challonge_active_sync` | `CHALLONGE_AUTO_SYNC_INTERVAL_MINUTES` (default 5) | Pulls Challonge → local for active tournaments |
| `division_grid_import_recovery` | 5 min (plus once at startup) | Re-dispatches import jobs stranded by a restart |
| `realtime_workspace_event_purge` | 1 day | Deletes `realtime.workspace_event` rows on `tournament:%:bracket` and `%:invalidation` older than 7 days |

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
transactions committed**. Consumers must therefore be idempotent — the `x-event-id` header carries the
event id for deduplication.

The sweeper (`drain_outbox` in `serve.py`) runs every second and:

1. Selects up to 100 rows in `pending` or `failed` state whose `next_attempt_at` has passed, ordered
   by `created_at`, with `FOR UPDATE SKIP LOCKED`. The skip-locked clause is what makes the sweeper
   safe to run in more than one replica: two sweepers never claim the same row, and neither blocks on
   the other.
2. Publishes each row persistently, then marks it `published` and commits **per row** — so a crash
   mid-batch loses at most a re-publish, never a whole batch.
3. On a publish failure, marks the row `failed`, increments `attempts`, records `last_error` and sets
   `next_attempt_at` to now plus an exponential backoff of `2^(attempts-1)` seconds, capped at 300 s.
   Failed rows are retried forever; there is no poison-message limit.

**Why it lives here.** `event_outbox` is a single global table with no per-service partition, and
`tournament-svc` runs the only sweeper in the backend. Producers elsewhere — `parser-service`'s match
log flows, and the shared encounter/computation event helpers used by several services — write rows
that this worker drains. That makes the tournament worker a hard dependency for cross-service event
delivery: while it is down, outbox rows accumulate and *no* service's domain events are published.
They are not lost — the sweeper catches up on the next tick — but they are delayed.

## Data owned

One PostgreSQL database, one SQLAlchemy metadata in [`../shared/`](../shared/README.md). Domain
boundaries are Postgres schemas; this service has no migrations of its own — there is one Alembic
project at [`../migrations/`](../migrations/).

**Writes:**

- **`tournament`** — the whole tree: `tournament`, `tournament_phase_schedule`, `stage`, `stage_item`,
  `stage_item_input`, `team`, `player`, `player_sub_role`, `encounter`, `encounter_link`,
  `encounter_captain_report`, `encounter_map_report`, `encounter_map_code`, `encounter_report_form`,
  `encounter_readiness`, `encounter_result_audit`, `encounter_pick_ban_ledger`, the `pick_ban_config*`
  / `pick_ban_session` / `pick_ban_entry` engine tables, `standing`, `recalculation_state`,
  `computation_job`, the four `challonge_*` mapping/log tables, `scrim_room`,
  `tournament_preview_access`, `tournament_link`, `slug_redirect`, `encounter_saved_view`.
- **`balancer`** — the registration side of that schema: `registration`, `registration_role`,
  `registration_role_hero`, `registration_form`, `registration_status`, `registration_team`,
  `registration_team_invite`, `registration_google_sheet_feed` / `_binding`. Balancing itself
  (`balancer.*` team-building tables) belongs to `balancer-service`.
- **`subscriptions`** — `provider_config` and `requirement` through the admin RPCs, plus the
  `entitlement` and `check_log` rows the admission gate writes as it resolves verdicts.
- **`public`** — division grids and their versions/mappings/import jobs, plus `event_outbox` (written
  by every producer, drained only here).
- **`realtime`** — `workspace_event` rows for the topics listed above, and the daily purge of stale
  bracket events.

**Reads only:** `players` (player identity behind rosters and registrations), `auth` (actor columns
on audit rows), `public.workspace` / `public.workspace_member` (tenancy anchors), `overwatch` (hero
and map catalog for pick/ban), `matches` (parsed match rows surfaced by the admin match reads).

Entity diagrams: [tournament](../../docs/database_erd.md#tournament--tournament-casual),
[registration](../../docs/database_erd.md#registration--balancer),
[division_grid](../../docs/database_erd.md#division_grid--public),
[subscriptions](../../docs/database_erd.md#subscriptions--subscriptions),
[platform](../../docs/database_erd.md#platform--public-realtime).

## Dependencies

- **PostgreSQL** — the shared ORM; all of the above.
- **RabbitMQ** — RPC transport, the three durable compute queues, the recalculation-event queues, and
  the outbox's publish target.
- **Redis** — realtime pub/sub for the gateway's WebSocket fan-out, and the `cashews` response cache
  (`api_cache_url` = db 5, `backend_cache_url` = db 6) invalidated after commit.
- **S3** — team logos, tournament covers/logos, registered-team crests.
- **Challonge API** — bracket import/export and the auto-sync pull, via the outbound `proxy` container.
- **Google Sheets** — registration feeds fetched as CSV exports over HTTPS.
- **Discord API / Twitch API** — subscription-entitlement verification in the admission gate, via the
  outbound `proxy` container.

## Configuration

[`../env/tournament.env`](../env/), inheriting [`../env/common.env`](../env/). The settings that
actually change behaviour:

| Setting | Effect |
| --- | --- |
| `CHALLONGE_API_KEY`, `CHALLONGE_USERNAME` | HTTP Basic credentials. Missing → Challonge answers 401, surfaced as `challonge_error`; the auto-sync job no-ops with a single warning |
| `CHALLONGE_AUTO_SYNC_ENABLED` | Kill switch for the background Challonge pull |
| `CHALLONGE_AUTO_SYNC_INTERVAL_MINUTES` | Interval of that pull (default 5) |
| `DISCORD_TOKEN`, `TWITCH_CLIENT_ID` | Subscription-entitlement providers. **Missing does not fail loudly**: the provider resolves `unknown`, `unknown` fails open, and a subscription-gated tournament admits everybody |
| `WORKER_METRICS_PORT` | Prometheus scrape port (9103 in both environments) |
| `RPC_PREFETCH_COUNT` | QoS on the RPC channel; the compute channel is fixed at 4 |
| `REDIS_URL`, `RABBITMQ_URL` | Transport endpoints |

`PORT=8004` in the env example is vestigial — nothing binds it.

## Running

Local, from `backend/tournament-service/` with the shared package importable:

```bash
faststream run serve:app
```

In compose the dev container adds `--reload --reload-dir /app/tournament-service --reload-dir
/app/shared` with forced polling (`WATCHFILES_FORCE_POLLING=true`), and bind-mounts both the service
and `backend/shared`. Production runs the bare command with a healthcheck that only proves the Python
interpreter starts (`python -c "import sys; sys.exit(0)"`) — it does not verify broker connectivity or
subscriber readiness. No profile: the service starts with the default stack. Resource ceilings are
0.5 CPU / 512 MB in dev and 1.0 CPU / 768 MB in production, single replica.

## Operational notes

- **Scaling is safe but untested.** The two pieces of shared mutable state — the outbox sweeper and
  the auto-transition tick — both claim rows `FOR UPDATE SKIP LOCKED`, so a second replica cannot
  double-publish or double-transition. The APScheduler jobs are not leader-locked, though: every
  replica runs every job, and the locking makes that correct rather than free.
- **Shutdown abandons in-flight scheduled jobs** (`scheduler.shutdown(wait=False)`). This is
  deliberate and safe: the outbox drain commits per row and the sync flows commit incrementally and
  are idempotent, so an interrupted job resumes on the next tick instead of blocking shutdown for
  minutes.
- **Dead-letter queues** exist for all three compute queues and are declared at startup. There is no
  automatic DLQ replay; stuck jobs need manual inspection.
- **Outbox retries are unbounded.** A permanently unroutable event retries every 300 s forever and
  keeps its row in the sweeper's working set. Watch `Outbox publish failed` warnings.
- **Stale import-job recovery** runs at startup and every 5 minutes, so a restart mid-import does not
  strand a marketplace grid import.
- **Cache invalidation is fire-and-forget** after commit, on background tasks anchored in a module
  set (an unanchored `create_task` can be collected mid-flight). A failed invalidation logs and is
  not retried; TTLs (5 min for most reads, 30 s for match detail) are the backstop.
- **Recalculation cost.** Every confirmed encounter result enqueues a standings job for its
  tournament. Scrim containers are excluded at the enqueue site, not in the worker, precisely because
  a job that is created, delivered and discarded is a permanent per-report cost that looks healthy.

# Balancer Service (`balancer-svc`)

Builds teams, two ways. A multi-objective genetic solver takes a whole roster and returns ranked
team variants; a live snake draft lets captains pick under a server-authoritative clock. Both need
the same workspace-scoped material — the member roster and its rank layers — and the same engine
also powers workspace custom games ("mixes"). The work lives in its own process because a solve is
minutes of pinned CPU inside a native extension: it cannot run inside a request handler, and it
would starve anything colocated with it.

The service is a headless FastStream worker on RabbitMQ. It serves no HTTP and listens on no API
port. The Go gateway owns every `/api/balancer/*` route and translates it into request/reply RPC on
`rpc.balancer.<group>.<method>` with an `x-deadline-ms` budget; this worker answers with the
`{ok, data, error}` envelope. Tournament balancing is not answered inline — the RPC returns a job id
and the solve is consumed asynchronously off the durable `balancer_jobs` queue by this same process.

- **Compose service:** `balancer-svc` (default profile)
- **Entry point:** `serve.py`
- **Run command:** `faststream run serve:app`
- **Transport:** RabbitMQ request/reply (`rpc.balancer.*`); no HTTP
- **Metrics:** Prometheus on `WORKER_METRICS_PORT` (dev 9100, prod 9100)

See [`../../docs/architecture.md`](../../docs/architecture.md) for the platform overview and
[`../ARCHITECTURE.md`](../ARCHITECTURE.md) for the `rpc → services → domain → repository → models`
layering this service follows.

## Responsibilities

- **Genetic team balancing.** Owns the balancing run end to end: input validation and limits, the
  effective roster shape, the native solve, the ranked variants, and the saved balance that becomes
  tournament truth once exported.
- **Balancer configuration.** Runtime defaults, allowed limits and presets, plus the two persisted
  override scopes (workspace default, tournament override).
- **The live draft.** Session lifecycle (create, seed, start, pause, resume, rollback, cancel,
  export), pick legality, autopick, feasibility and suggestions, and the server-authoritative clock
  that decides when a pick expires.
- **Custom games (mixes).** Workspace pickup games: lineup, per-player role constraints, team shape,
  balance, seat swaps, recorded outcomes and rotation fairness.
- **Workspace roster and ranks.** The workspace member list the balancer reads from, and the two
  rank layers behind it (see [Data owned](#data-owned)).

The heavy solve itself is the native crate's; everything above is this service's.

### Native solver

`tournament_balancer` is the default backend, an in-house Rust crate of the same name
(`native/tournament_balancer`, PyO3 + maturin, `rayon` for parallel evaluation). Python imports it
as a plain module (`importlib.import_module("tournament_balancer")`), serializes the request to JSON, and calls
it through `asyncio.to_thread` so the GIL-releasing solve never blocks the event loop
(`src/domain/balancer/moo_backend.py`).

*Multi-objective* here means literally two objectives, NSGA-II style: **balance** (how close the
teams are in strength) and **comfort** (how well players sit on roles they want). The crate returns
a Pareto front rather than one answer — no variant on it is better than another on both axes — and
`rank_comfort_tilt` weighs the normalized objectives into the `composite_score` that orders the
front and picks the primary variant. Every returned variant is a legitimate trade-off, which is why
the API surfaces variants and not a single team set.

`mix_balancer` is the second backend, a vendored C++ engine pinned to the two-team pickup-mix flow
and documented in [`native/mix_balancer/README.md`](native/mix_balancer/README.md). It brute-forces
every player/role split, so it returns the true optimum instead of a GA approximation, but only for
exactly two equal teams. Both extensions are Linux-only compiled artifacts; `mix_balancer` degrades
to the `tournament_balancer` backend with a warning when it is absent; `tournament_balancer` does not degrade at all
(`RuntimeError: Rust MOO backend requires tournament_balancer to be installed`).

## Interface

The worker subscribes to `rpc.balancer.*` and consumes one durable job queue. Method groups:

| Namespace | Covers |
|---|---|
| `rpc.balancer.config` | Public read: runtime defaults, allowed limits, presets that drive the client's balancer form |
| `rpc.balancer.admin.*` | Tournament and workspace balancer config, the saved balance (read/save/export), rank export, tournament summary |
| `rpc.balancer.teams.*` / `admin.teams_import` | Team roster import from an uploaded file, and export of a tournament's registered teams |
| `rpc.balancer.jobs.*` | Async balancing: `create` (uploaded roster), `create_for_tournament` (the tournament's own pool, nothing uploaded), `status`, `result` |
| `rpc.balancer.draft.*` | Board and session reads, feasibility/suggestions/pick options, admin lifecycle, pick actions, export |
| `rpc.balancer.custom.*` | Mix lifecycle, lineup, host/co-host grants, role mask, balance, seat swaps, outcomes, rotation |
| `rpc.balancer.players.*` | Workspace roster page, rank writes per layer, ranking-author list |

The full method list with request/response schemas is published at `/api/docs`, generated from
`src/openapi_schemas.py` (`OPERATIONS`) and `src/openapi_docs.py` (`DOCS`). Neither table currently
carries the `custom.*`, `players.*` or `teams.*` subjects, so those groups are absent from the
generated documentation; the subject list above is the complete one.

**Queues consumed.** `balancer_jobs` (durable, `x-message-ttl` 15 min, dead-lettered to `dlx` →
`balancer_jobs.dlq`), on its own channel with `prefetch_count=2` so a multi-minute solve cannot
stall the RPC channel.

**Events published to the broker.** Only `BalancerJobEvent` onto `balancer_jobs`, which this same
worker consumes — job creation and job execution are one process, split by a queue rather than by a
service. There is no outbox here and no cross-service domain event.

**Realtime topics** (published to Redis, relayed to clients by the gateway):

| Topic | Events | Durability |
|---|---|---|
| `tournament:{id}:draft` | `draft.pick_started`, `draft.autopicked`, `draft.blocked`, `draft.completed`, … | Durable. Published inside the mutation transaction, so the persisted event id orders with the pick and a reconnecting client replays from its cursor |
| `tournament:{id}:balancer` | `balancer_job.{queued,running,succeeded,failed}` | Durable, awaited so transitions keep their order |
| `tournament:{id}:balancer` | `balancer_job.progress` | Ephemeral (`event_id=0`, Redis only) — high-frequency ticks that would pollute the replay cursor |
| `tournament:{id}:balancer` | `balancer.balance_saved`, `balancer.teams_changed`, `balancer.config_changed` | Durable, but fire-and-forget: the mutation response does not wait on the publish |
| `workspace:{id}:pickup_mix` | `pickup_mix.updated` | Non-durable, carries no row data — the signal only says "refetch" |

Job realtime is skipped entirely for jobs created without a `tournament_id` (API-key and public
jobs): there is no page to broadcast to.

**Periodic work.** The draft clock supervisor, started with the app and running for the process
lifetime. It polls for `LIVE` sessions every 2 s (10 s while none are live, cut short by a
`draft:clock:supervisor` nudge on start/resume) and spawns one lock-guarded clock loop per session.

### Async balancing jobs

`jobs.create` / `jobs.create_for_tournament` validate the input, resolve the tournament's roster
shape, write the job to Redis and publish to `balancer_jobs`, then return `{job_id, status:
"queued"}` immediately. Nothing about the job lives in Postgres: metadata, the input payload, the
event log and the result are four Redis keys under `balancer:job:{job_id}:*`, all expiring together
after `BALANCER_JOB_TTL_SECONDS`. A caller polls `jobs.status` for `queued | running | succeeded |
failed` plus the current stage and progress, then reads `jobs.result` once the status is terminal —
or watches the realtime topic above and skips most of the polling.

### Draft clock

Pick deadlines are the server's, not the client's. Each `LIVE` session gets a clock loop that holds
a Redis lock (`draft:{id}:clock_owner`, 10 s TTL renewed every 3 s), sleeps until the current pick's
`clock_expires_at`, and fires an autopick when the deadline passes. Manual picks and pauses publish
a nudge on `draft:{id}:control` so the loop re-reads state instead of waking on a stale deadline.

Every finalizing write is an optimistic compare-and-set: the update is conditional on both
`status = 'on_clock'` and the caller's `expected_version`, so exactly one writer's `rowcount` is 1
and everyone else gets a 409 (`pick_already_resolved`). This is what makes the clock safe to race
against a human — an expired autopick that loses to a manual pick landing in the same instant is a
no-op, not a double pick.

A reconnecting client re-reads the board snapshot and replays durable draft events from its cursor;
nothing about the clock is client state, so a client that was offline across a deadline sees the
autopick as an ordinary event.

### Custom games: two id spaces

A mix's **host and co-hosts are `auth.user` ids**; its **lineup is `workspace_member` ids**. Hosting
is an act performed by an account, playing is a property of a workspace membership, and the two do
not share a key. The consequences are load-bearing:

- A workspace member who has never signed in has no `auth_user_id` and therefore cannot be made host
  or co-host — the roster payload exposes `auth_user_id` precisely so the picker can exclude them.
- Write access is not the workspace `custom_game` permission. Only `create` is gated that way (a new
  mix has no per-game grant to check); every other mutation re-loads the game and re-checks
  host-or-co-host itself, so a co-host holding only the plain `member` role can still write.
- Reads stop at workspace membership. Watching a mix requires no grant.

### Rank layers

A member's rank exists in two layers that are **never merged**: the **workspace canon** everyone
inherits, and each **ranking author's own book**, which overrides canon for that author alone. The
nullable `author_user_id` is the discriminator; there is deliberately no `scope` column that could
disagree with it. `players.set_ranks` picks the layer from the request's `scope`, and the author
layer is always the caller's own — a foreign book is readable by every workspace member and writable
by nobody else. Deleting a role from a layer is how inheritance is restored. Reads return both
dictionaries side by side so a client can tell an inherited number from an overridden one.

## Data owned

One PostgreSQL database, one SQLAlchemy metadata in `backend/shared/`; this service ships no
migrations of its own — there is a single Alembic project at `backend/migrations/`.

Writes, all in the `balancer` schema unless noted:

- `balance`, `balance_variant`, `team`, `team_slot` — the saved balancing run and its normalized
  result. `exported_team_id` is the boundary where balancer output becomes tournament truth.
- `draft_session`, `draft_team`, `draft_player`, `draft_pick`, `draft_audit_event` — the live draft.
- `workspace_config`, `tournament_config` — the two balancer config scopes.
- `custom_game`, `custom_game_co_host`, `custom_game_player`, `custom_game_player_role`,
  `custom_game_team_name`, `custom_game_role_slot` — mixes.
- `member_rank` — both rank layers.
- `casual.match`, `casual.team`, `casual.player` — the frozen per-match record a mix writes on
  `record_outcome`; the only durable trace of a played mix game.

Reads only: `balancer.registration*` (tournament-service owns those writes — a draft pool entry *is*
a registration, which is why roles, ranks and top heroes are never copied into draft-local tables),
the `tournament` schema, `public.workspace` / `public.workspace_member`, and `auth.user`.

Entity diagrams: [`../../docs/database_erd.md`](../../docs/database_erd.md) —
[`balancer`](../../docs/database_erd.md#balancer--balancer),
[`custom_game`](../../docs/database_erd.md#custom_game--balancer),
[`member_rank`](../../docs/database_erd.md#member_rank--balancer),
[`casual`](../../docs/database_erd.md#casual--casual).

## Dependencies

- **PostgreSQL** — everything durable listed above.
- **RabbitMQ** — the `rpc.balancer.*` request/reply surface and the `balancer_jobs` work queue.
- **Redis** — three distinct roles: job store (metadata, payload, event log, result), draft clock
  locks and control pub/sub, and realtime event fan-out.
- **Identity** — not called. The gateway injects the resolved identity into the RPC message and the
  worker rehydrates an `AuthUser` from it; permission checks are local.

No external APIs, no S3, no outbound `proxy` egress.

## Configuration

`backend/env/balancer.env`, layered on `backend/env/common.env`. What actually changes behaviour:

- `BALANCER_JOB_TTL_SECONDS` (default 86400, clamped to 900…604800) — lifetime of every
  `balancer:job:*` key. It also arms the active-jobs set used for per-principal concurrency, so it
  must stay well above the longest possible job.
- `RPC_PREFETCH_COUNT` (default 16) — QoS on the RPC channel. The job channel is fixed at 2.
- `WORKER_METRICS_PORT` — Prometheus scrape port.
- `REDIS_URL`, `RABBITMQ_URL`, `POSTGRES_*` — inherited from `common.env`.
- `AUTH_SERVICE_URL` — overridden in production to route token validation through the gateway.

Balancer algorithm parameters are *not* environment configuration. Defaults, limits and presets live
in `src/services/balancer/config/` and are served by `rpc.balancer.config`; persisted overrides live
in `balancer.workspace_config` / `balancer.tournament_config`. `PORT=8003` in `balancer.env` is
vestigial — nothing binds it.

## Running

```bash
# from backend/balancer-service
faststream run serve:app
```

Under Compose the service is `balancer-svc` in the default profile, built from `./backend` with
`APP_PATH=balancer`. Dev adds `--reload --reload-dir /app/balancer-service --reload-dir /app/shared`
with forced polling; production runs the bare command with a no-op healthcheck
(`python -c "import sys; sys.exit(0)"`) — there is no port to probe. It waits on healthy `redis` and
`rabbitmq` only; Postgres is external. Resource limits are 2 CPU / 512 MB in dev and 4 CPU / 768 MB
in production, sized for the solver rather than for request handling.

The native extensions are built during the image build (maturin for `tournament_balancer`, scikit-build-core +
CMake for `mix_balancer`) and are Linux-only, so a non-Linux host runs the Python side without them:
mix balancing falls back, tournament balancing fails, and the tests that need `tournament_balancer` skip.

## Operational notes

- **Two solver deadlines.** The native optimizer honours its own `time_limit_ms` (max 600 s);
  `_SOLVER_WATCHDOG_SECONDS` (660 s) is a coarse outer `asyncio.wait_for` that fails the job rather
  than waiting forever should the solver ignore its budget. `BALANCER_JOB_TTL_SECONDS` must exceed
  both — its floor of 900 s exists for exactly this reason, because the active-jobs set is only
  re-armed on new reservations and would otherwise expire out from under a running job.
- **Job redelivery is safe.** `execute_balance_job` returns immediately if the payload is gone or the
  job already reached a terminal status, so a redelivered message is a no-op rather than a second
  solve. A genuinely failed job re-raises, so the message is not acked and RabbitMQ applies the
  queue's dead-letter policy.
- **Late RPC calls are dropped.** The shared broker installs a deadline middleware: a request whose
  `x-deadline-ms` budget has already elapsed is discarded before the handler runs.
- **The clock is replica-safe but single-owner.** Per-session Redis locks mean multiple replicas can
  run the supervisor without double-firing autopicks, but only one owner drives a given session; if
  it dies, the 10 s lock TTL bounds the gap before another instance takes over.
- **Custom-game balancing is synchronous.** `custom.balance` calls the engine inside the RPC
  deadline, unlike tournament balancing. It stays tractable because `mix_balancer` declares
  `max_teams = 2`, so the runtime caps a mix at two teams and benches the surplus rather than
  growing the search. A lineup that genuinely needs more than two teams must go
  through `tournament_balancer` and the job queue.
- **Large payloads bypass the event loop.** Uploads reach ~25 MB and results tens of MB, so both
  JSON serializations run in `asyncio.to_thread` before touching Redis.

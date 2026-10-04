# Parser Service (parser-svc)

Parser owns everything that turns raw Overwatch artefacts into domain data: match-log files
uploaded from the tournament admin or dropped into a Discord channel, Overwatch rank telemetry
polled from OverFast, the declarative achievement engine evaluated on top of parsed results, and
the MVP impact scoring derived from match statistics. It is a separate process because that work
is minutes-long, IO-bound and bursty — one log parse holds a database session and one unacked
delivery for as long as the file takes — and must never share a channel or a request path with
interactive reads.

It is a headless FastStream worker on RabbitMQ: no HTTP server, no listening port, no uvicorn.
Requests reach it as request/reply RPC on `rpc.parser.<method>`, published by the Go gateway (the
only process speaking HTTP to the outside) under `/api/v1` with an `x-deadline-ms` budget; the
worker replies with an `{ok, data, error}` envelope. Everything else arrives as a durable queue
job or a domain event.

- **Compose service:** `parser-svc`
- **Entry point:** `serve.py`
- **Run command:** `faststream run serve:app`
- **Transport:** RabbitMQ request/reply (`rpc.parser.*`); no HTTP
- **Metrics:** Prometheus on `WORKER_METRICS_PORT` (dev 9100, prod 9100)

System overview: [`../../docs/architecture.md`](../../docs/architecture.md). Code layering:
[`../ARCHITECTURE.md`](../ARCHITECTURE.md). Shared kernel: [`../shared/README.md`](../shared/README.md).

## Responsibilities

- **Match-log ingestion** — the authority for the `log_processing.record` lifecycle and for every
  row parsed out of a log: matches (one per played map), per-round statistics, the kill feed and
  the assist/ultimate/hero-swap event stream.
- **Catalog name resolution** — logs carry map/gamemode/hero names in the reporting client's
  locale, so names resolve through the `aliases` column on `overwatch.{hero,map,gamemode}`, never
  through code. Anything resolving to neither the canonical name nor an alias lands in
  `overwatch.catalog_alias_miss` — the "add an alias" queue behind `/admin/aliases`, keyed on
  `(entity_type, raw_name)` with an occurrence counter. A map/gamemode miss is written in its own
  transaction so the 404 that fails the log cannot roll it away; hero misses are batched per log
  because they are soft (an unknown hero drops that stat/kill row and the log still completes).
- **Player resolution from logs** — creates virtual players for battle tags with no account and
  upserts the battlenet `social_account` when a known player renames mid-log.
- **Overwatch rank collection** — selects due battle tags, fetches career summaries from OverFast
  and keeps the per-tag collection state, snapshot series and fetch log.
- **Achievement evaluation** — owns the condition-tree engine, the rules admin surface, the
  evaluation runs and the manual grant/revoke overlay.
- **MVP impact scoring** — derived stats (`PerformancePoints`, `Performance`, `ImpactPoints`,
  `ImpactRank`, `OverperformanceScore`), the versioned baselines they are scored against, and the
  idempotent historical backfill.
- **Subscription entitlement collection** — periodic and on-demand re-checks of Discord/Twitch
  subscription entitlements used as a registration admission condition.
- **Global settings and the per-tournament Discord channel binding.**

## Interface

RPC namespace: `rpc.parser.*` (single namespace, registered in `src/rpc/`).

| Method group | Surface |
| --- | --- |
| `rpc.parser.logs.*` | Match-log admin: queue depths, processing history and stats, upload, retry, whole-tournament reprocess |
| `rpc.parser.rank.*` | Public rank reads (user/battle-tag history, current ranks) plus collection admin: health stats, fetch log, trigger collection, re-enable auto-disabled tags |
| `rpc.parser.ach.*` | Achievement rules CRUD, condition-type catalog and tree validation, seed/reset, export/import and cross-workspace library import, evaluation trigger and runs, rule test/dry-run, qualifying-user list, manual overrides |
| `rpc.parser.subscription.*` | Subscription collection admin: health stats, check log, per-user entitlement, trigger a re-check or a sweep |
| `rpc.parser.impact.*` | Superuser recompute of the impact-scoring baselines |
| `rpc.parser.metadata.*` | Superuser OverFast catalog sync for heroes, maps and gamemodes |
| `rpc.parser.settings.*` | Superuser global settings CRUD (`public.settings`) |
| `rpc.parser.discord_channel.*` | Per-tournament Discord channel binding, plus an on-demand channel-history backfill |

The full method list with request/response schemas is published at `/api/docs`, generated from
`src/openapi_schemas.py` (`OPERATIONS`) and `src/openapi_docs.py` (`DOCS`).

### Queues consumed

| Queue | Event | Effect |
| --- | --- | --- |
| `upload_match_log` | `UploadMatchLogEvent` | Store a bot-uploaded log (base64 over RabbitMQ) to S3, upsert its record, enqueue processing |
| `process_match_log` | `ProcessMatchLogEvent` | Parse one log file; own channel, prefetch 2 |
| `process_tournament_logs` | `ProcessTournamentLogsEvent` | List a tournament's stored logs in S3 and fan out one `ProcessMatchLogEvent` per file |
| `achievement_evaluate` | `AchievementEvaluateEvent` | Run the achievement engine for a workspace |
| `achievement_evaluate.deferred` | `AchievementEvaluateEvent` | Resumes a `queued` run an unverified workspace's manual/`rule_version_bump` recompute was parked as; own channel, prefetch 1 |
| `tournament_encounter_completed` | `EncounterCompletedEvent` | Bound to the `tournament.events` exchange; enqueues an achievement evaluation |
| `tournament_registration_approved` | — | Bound to the same exchange; prioritises and enqueues a rank check for the approved player |
| `rank_fetch`, `rank_fetch_priority` | `FetchRankEvent` | One OverFast call per battle tag; shared channel with prefetch `RANK_FETCH_WORKER_PREFETCH` |

Every one of those queues carries `x-dead-letter-exchange=dlx` and an `x-message-ttl`; the worker
declares and binds its own DLQs at startup, so an expired or rejected job is visible in
`<queue>.dlq` instead of being dropped by an unbound routing key.

`process_match_log` gets a channel of its own because it is the one minutes-long handler here: a
delivery that outlives RabbitMQ's `consumer_timeout` closes its whole channel, and that must not
take `upload_match_log`, `process_tournament_logs` and `achievement_evaluate` down with it.

### Ingestion path

1. **Arrival.** Either the gateway relays a multipart upload as base64 to `rpc.parser.logs.upload`
   (`log.create` on the tournament's workspace), or the Discord bot publishes an
   `UploadMatchLogEvent` on `upload_match_log`. On the bot path the uploader's Discord name is
   resolved to a `social_account` → player, and the record source is `discord`; otherwise `manual`.
2. **Store.** `services/match_logs/uploads.py` rejects a filename containing `/`, `\` or `..`,
   rejects non-UTF-8 bytes, PUTs the object to S3 and upserts a `log_processing.record`. An
   existing `pending`/`failed` row for the same `(tournament_id, filename)` is reused and reset to
   `pending` with `attempts = 0` — a fresh upload of a filename may carry different content, so it
   gets a fresh retry budget.
3. **Enqueue.** A `ProcessMatchLogEvent(tournament_id, filename)` goes to `process_match_log`.
   `rpc.parser.logs.process_tournament` reaches the same point by fanning out one event per stored
   file rather than parsing a whole tournament inline.
4. **Parse.** `flows.process_match_log` fetches the object from S3. A missing/empty object or one
   over `MAX_MATCH_LOG_BYTES` fails the record terminally (`fail_unstarted`) and raises 404/413 —
   terminal on purpose, because a row left on `pending` would be requeued by the reaper forever.
   Otherwise the record moves to `processing` and `MatchLogProcessor` walks the log lines into
   `matches.match` (one row per played map, linked to its encounter and back to the log record),
   `matches.statistics` (long format: one row per match/round/team/player/hero/stat, raw stats plus
   derived KD/KDA/Assists/DamageDelta and the MVP-impact stats), `matches.kill_feed` and
   `matches.event` (offensive/defensive assists, ultimate charge/start/end, hero swaps). Existing
   stats, events and kills for that match are cleared first, so a reparse replaces rather than
   duplicates. Completing an encounter enqueues `TournamentChangedEvent`,
   `TournamentStandingsInvalidatedEvent` and `EncounterCompletedEvent` through the outbox.
5. **Result.** Exactly once per attempt, and based solely on whether the parse succeeded, the
   worker publishes a `MatchLogProcessedEvent{tournament_id, filename, status}` to the **fanout**
   exchange `match_log.result`.
6. **Follow-up.** On success the record is marked `done`, a `logs.updated` realtime signal is
   published, and an `AchievementEvaluateEvent` is enqueued for the tournament's workspace. That
   evaluation is deliberately downstream of the result publish: a failing evaluation retries the
   message but must not flip the reported ingestion outcome.

**Correlation.** The bot that uploaded a log blocks on the answer, but there is no reply-to on this
path — the result is a broadcast. `MATCH_LOG_RESULT_EXCHANGE` is a fanout, so *every*
discord-service replica receives every result; each replica hands it to its in-process
`ResultWaiter`, which holds pending futures keyed on `(tournament_id, filename)`. Only the replica
that actually has a future under that key resolves it; the others no-op. That is the whole
correlation: the tuple is the correlation id, and the fanout exists because a work-queue would
round-robin the result to a replica that is not waiting for it. A waiter that hears nothing within
its timeout gives up on its own. This replaced Postgres `LISTEN`/`NOTIFY`, which pgBouncer
transaction pooling breaks.

**Idempotency.** Before parsing, the raw bytes are hashed (SHA-256). If a `done` record already
exists for the same `(tournament_id, filename, content_hash)`, the log is not reparsed: the latest
incomplete record is finalised as `done` against that hash and the flow returns. This is what makes
requeueing safe. `attempts` on the record is the retry budget, bumped on every transition to
`processing` and bounded by `LOG_REAPER_MAX_ATTEMPTS`: a log that kills the worker before it can
mark itself failed is retried a few times and then marked `failed` with an explicit message instead
of cycling forever. A requeue that is never picked up costs no attempt, so a slow backlog drains
rather than burning its budget. `failed` records are never auto-retried — the parser rejected them,
so retrying is a loop on bad data; operators retry those from the admin console
(`rpc.parser.logs.retry`, which resets the budget).

### Achievement engine

Rules are data, not code. An `achievements.rule` row carries a JSON condition tree of `AND` / `OR` /
`NOT` nodes over leaf conditions; each leaf is `{"type": ..., "params": {...}}` dispatched through a
decorator-populated registry in `src/services/achievement/engine/conditions/`, so adding a condition
type means adding one registered executor, and authoring an achievement means editing JSON through
the admin API. Evaluation returns sets of tuples whose shape follows the rule's grain — `(user_id)`,
`(user_id, tournament_id)` or `(user_id, tournament_id, match_id)`.

A run is a reconcile, not an append: the differ loads the stored results for the rule (optionally
sliced to one tournament or match), computes insert/delete sets against the fresh evaluation, and
applies them with `INSERT ... ON CONFLICT DO NOTHING`, so two concurrent runs for the same workspace
converge instead of colliding on the dedup index. Re-running an unchanged rule is therefore a no-op.
Incremental runs narrow the rule set by `depends_on` against the event's `changed_tables`.

Manual admin decisions live in a **separate overlay**, `achievements.override` (grant or revoke,
with reason and granting actor). The engine never reads or writes that table, so no re-evaluation
can erase an admin decision; the two are merged only at read time, by
`shared.services.achievement_effective` — grants union into the effective set, revokes filter out of
it.

### Rank synchronisation

Collection is bound to a linked `social_account` (a battlenet account owned by a player), never to a
bare BattleTag string: `overwatch_rank.battle_tag_state` is keyed on `social_account_id`, and the
snapshots it produces are attributed to that account's user. An unlinked tag is not collected.

Per-tag state carries `next_eligible_at`, `consecutive_failures` and `status`. On success the tag is
rescheduled at the admin-configured `interval_seconds` with jitter and the failure counter resets.
A **private** profile is not a failure: the status becomes `private`, failures reset, and the tag is
rescheduled at 4× the base interval — the account still exists and may be opened later. `not_found`
gets 8×. A permanent failure backs off exponentially (`backoff_base_seconds * 2^n`, clamped to six
hours) and, once `max_consecutive_failures` is reached, disables the tag. Transient upstream failures
(OverFast 5xx/timeouts, 429) back off the same way but never disable, because an outage would
otherwise permanently disable healthy accounts with no recovery path;
`rpc.parser.rank.reenable_disabled` is the operator escape hatch for tags disabled in the past.
Redis carries the rest of the protection: per-account enqueue and in-flight dedup keys, a fixed
per-minute window (over it a tag is deferred past the window rather than fetched — the only rate
control the priority queue has, since registration approvals bypass the scheduler's pacing) and a
global cooldown key set on a 429.

### Events published

- `match_log.result` (fanout) — `MatchLogProcessedEvent`, consumed by discord-service.
- `process_match_log` — fanned out by the tournament-wide job and by the stall reaper.
- `achievement_evaluate` — enqueued after a successful parse and on `EncounterCompletedEvent`.
- `achievement_evaluate.deferred` — a manual or `rule_version_bump` run for a workspace whose
  `verification_status` is `unverified`: the run row is created `queued` and the message carries its
  id, so the consumer finishes that row instead of opening a second one. `parse_complete` is never
  deferred.
- `rank_fetch` / `rank_fetch_priority` — from the collection tick, the admin collect RPC and
  registration approval.
- `discord_commands` — `DiscordCommandEvent` for the on-demand channel-history backfill.
- Through the transactional outbox (`public.outbox`): `TournamentChangedEvent`,
  `TournamentStandingsInvalidatedEvent`, `EncounterCompletedEvent` when a parsed log completes an
  encounter.

### Realtime

`logs.updated` on the workspace-scoped topic `workspace:{id}:logs`, published straight to Redis for
the gateway to relay to the admin log monitor. Non-durable and payload-free: no journal row, no
replay cursor — the monitor refetches `/admin/logs/history` on the signal and does an initial fetch
on subscribe, so a missed signal self-heals, and the actual log data stays gated by `log.read`.

### Scheduled work

All four are APScheduler interval jobs guarded by a Redis leader lock, so only one replica acts per
tick.

| Job | Cadence | What it does |
| --- | --- | --- |
| OverFast rank collection | 60s tick | Selects and *claims* due battle tags and publishes one `FetchRankEvent` each — it never calls OverFast itself. Per-tag cadence comes from `next_eligible_at`, so changing the admin interval needs no restart. No-ops while collection is disabled in settings. |
| Match-log stall reaper | `LOG_REAPER_TICK_SECONDS` (300s) | Requeues records the queue dropped: `pending` older than `LOG_REAPER_PENDING_AFTER_SECONDS` (kept above the 5-minute queue TTL so a message still waiting on a busy consumer is not double-parsed) and `processing` older than `LOG_REAPER_PROCESSING_AFTER_SECONDS`. Records past `LOG_REAPER_MAX_ATTEMPTS` are retired as `failed`. |
| Failed match-log retention | 1h tick | Deletes the S3 object and the record of `failed` logs finished more than `FAILED_LOG_RETENTION_DAYS` (14) ago. Records a match still points at are kept; the object stays while another live record or a match uses the same key. Unfinished logs (no `MatchEnd`) are not retained at all — `validate` deletes them on the spot. |
| Subscription collection | 60s heartbeat | Decides inside the tick whether the admin-configured `interval_seconds` has elapsed (read from the append-only check log), then re-checks entitlements for active tournament participants. |

## Data owned

Writes:

- `matches` — `match`, `statistics`, `event`, `kill_feed`, `stat_baselines`.
- `log_processing` — `record` (shared with discord-service, which uploads through this worker),
  `discord_channel`.
- `overwatch_rank` — `battle_tag_state`, `rank_snapshot`, `fetch_log`.
- `achievements` — `rule`, `evaluation_result`, `evaluation_run`, `override`.
- `overwatch` — `catalog_alias_miss`, plus the `aliases` column and catalog rows written by the
  OverFast metadata sync; app-service owns the public reads of that catalog.
- `subscriptions` — `entitlement`, `check_log` (shared with tournament-service, which owns
  requirements).
- `public.settings` — global key-namespaced settings.
- As a side effect of ingestion: `players.user` and `players.social_account` (virtual players and
  battlenet renames), and tournament roster rows for substitutes discovered in a log.

Reads only: `tournament.*` (tournaments, encounters, teams, players), `public.workspace` and
`public.workspace_member`, the division grid, `auth.user` for actor stamping.

No service ships its own migrations — there is one Alembic project at
[`../migrations/`](../migrations/). Entity diagrams for these tables:
[`../../docs/database_erd.md`](../../docs/database_erd.md), sections *matches*, *ingestion*,
*ranks*, *achievements*, *catalog* and *subscriptions*.

## Dependencies

- **PostgreSQL** — the shared SQLAlchemy metadata from `backend/shared/`; one database for all
  services.
- **RabbitMQ** — RPC transport, durable job queues, the tournament event exchange, the match-log
  result fanout and the DLQs.
- **Redis** — scheduler leader locks, rank-collection dedup/rate-limit/cooldown keys, the cashews
  cache for impact baselines, and the realtime publish channel.
- **S3** — match-log file storage (`logs/{tournament_id}/{filename}`) and the catalog images
  (`assets/overwatch/{heroes,maps,gamemodes}/{slug}.{ext}`).
- **OverFast API** (self-hosted) — player career summaries for rank collection and the
  hero/map/gamemode catalog; the hero sync pulls all 13 Blizzard locales, one request per locale,
  and only ever adds aliases. OverFast exposes no `locale` parameter for `/maps` or `/gamemodes`,
  so map and gamemode aliases are admin-supplied. Every sync copies portraits, screenshots and
  icons into S3 and stores the S3 URL (`src/services/catalog_images.py`): the site cannot load
  images from OverFast's host. A row already on the bucket is not re-uploaded, so a hand-replaced
  image survives the sync.
- **Discord and Twitch APIs** — subscription entitlement verification.
- All external calls egress through the outbound **`proxy`** container.

Adding a map, hero or locale needs no deploy: run the OverFast hero sync, or add the alias in
`/admin/{heroes,maps,gamemodes}` — or straight from the miss queue in `/admin/aliases`, which
attaches the alias and closes the miss in one request.

## Configuration

`backend/env/parser.env`, layered on `backend/env/common.env` (see
[`parser.env.example`](../env/parser.env.example)). Settings that actually change behaviour:

- **Ingestion caps** — `MAX_MATCH_LOG_BYTES` (25 MiB), `MAX_MATCH_LOG_LINES` (500k).
- **Stall reaper** — `LOG_REAPER_ENABLED`, `LOG_REAPER_TICK_SECONDS`,
  `LOG_REAPER_PENDING_AFTER_SECONDS`, `LOG_REAPER_PROCESSING_AFTER_SECONDS`,
  `LOG_REAPER_MAX_ATTEMPTS`, `LOG_REAPER_BATCH_SIZE`.
- **Failed-log retention** — `FAILED_LOG_RETENTION_DAYS` (14).
- **OverFast** — `OVERFAST_BASE_URL`, `OVERFAST_TIMEOUT`, `OVERFAST_MAX_RETRIES`,
  `OVERFAST_PROXY_URL` (production: `socks5://proxy:1080`), `RANK_FETCH_WORKER_PREFETCH` (kept
  low to protect the upstream). The operational
  collection parameters — interval, scope, per-minute limit, backoff base, max consecutive
  failures, rank mapping — live in `public.settings`, editable at runtime, not in the env file.
- **Outbound proxy** — `PROXY_TYPE`, `PROXY_IP`, `PROXY_PORT`, `PROXY_USERNAME`, `PROXY_PASSWORD`.
- **Subscription verification** — `DISCORD_TOKEN`, `TWITCH_CLIENT_ID`. Unset means every live check
  resolves `unknown` and fails open: the sweep runs and proves nothing.
- **Transport and infrastructure** — `RABBITMQ_URL`, `RPC_PREFETCH_COUNT`, `REDIS_URL`,
  `RABBITMQ_MANAGEMENT_URL` / `_USER` / `_PASSWORD` (queue-depth reads for the admin monitor).
- **Observability** — `WORKER_METRICS_PORT`, `LOG_LEVEL`, `JSON_LOGGING`, `SENTRY_DSN`,
  `TRACING_ENABLED`, `OTLP_ENDPOINT`, `OTEL_TRACES_SAMPLER*`.

`PORT` is still present in `parser.env.example` and in `AppConfig`; nothing binds it — it is a
leftover from the decommissioned HTTP service.

## Running

Locally, from `backend/parser-service/`:

```
uv run faststream run serve:app
```

The MVP-impact backfill is a separate CLI (idempotent, safe to rerun):

```
uv run python backfill_impact.py [--tournament-id N]
```

In compose, `parser-svc` is built from `backend/` with `APP_PATH=parser` and depends on healthy
`redis`, `rabbitmq` and `proxy`. Dev runs `faststream run serve:app --reload` with the service and
`shared/` bind-mounted and polling watchers (`WATCHFILES_FORCE_POLLING`); production runs the plain
command with `restart: always`. Production declares a placeholder healthcheck
(`python -c "import sys; sys.exit(0)"`) — it proves the interpreter starts, not that the worker is
consuming; liveness is judged from metrics and queue depth instead.

## Operational notes

- **Shutdown order.** Stop schedulers in `on_shutdown`, but close HTTP, S3 and Redis clients in
  `after_shutdown`. FastStream drains consumers between those hooks; closing clients before
  that drain makes active rank-fetch jobs fail with `Client not started` and sends them to the DLQ.
- **Channel isolation is load-bearing.** RPC, background jobs, match-log parsing and rank fetching
  each get their own channel/prefetch. Collapsing them means one long parse can close the channel
  every other consumer shares.
- **DLQs.** `upload_match_log.dlq`, `process_match_log.dlq`, `process_tournament_logs.dlq`,
  `achievement_evaluate.dlq`, `achievement_evaluate.deferred.dlq`, `rank_fetch.dlq`,
  `rank_fetch_priority.dlq`,
  `tournament_encounter_completed.dlq`, `tournament_registration_approved.dlq`. An achievement
  evaluation that raises is rejected without requeue straight into its DLQ.
- **A stuck "Queued" record is a reaper question, not a queue question.** The row, not the message,
  is the source of truth; check `attempts` and the reaper settings before republishing by hand.
- **Rank fetches are scheduler-retried, not broker-retried.** A transient OverFast failure is
  recorded with backoff and swallowed, so the message is not redelivered; the next tick picks the
  tag up when `next_eligible_at` says so.
- **Baseline cache.** Impact baselines are cashews-cached for 10 minutes under a single literal key
  scoped to `FORMULA_VERSION`; any process reading them (including `backfill_impact.py`) must call
  `configure_cache()` first, or every cache operation raises.
- **Replicas are safe.** All three schedulers are leader-locked in Redis, and rank enqueue plus
  match-log parsing are deduped (Redis keys and content hash respectively), so scaling the worker
  horizontally does not duplicate work.
- **`ortools` is declared in `pyproject.toml` but never imported** — there is no OR-Tools
  optimisation in this service.

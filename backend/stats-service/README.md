# Stats Service (stats-svc, stats-worker)

Stats owns everything that turns raw match artefacts into domain data — match-log files uploaded
from the tournament admin or dropped into a Discord channel, rank telemetry polled from each game's
upstream, the declarative achievement engine evaluated on top of parsed results, and the MVP impact
scoring derived from match statistics — and the public reads over that data: the statistics almanac,
character and map statistics, the `/users/*` player statistics and the achievement reads. It also
syncs discipline catalogs through their modules (OverFast for Overwatch, Data Dragon for LoL).

It is two headless FastStream processes from one image (`owt-stats`), on RabbitMQ: no HTTP server,
no uvicorn. The **RPC process** (`stats-svc`) answers request/reply RPC on `rpc.stats.<method>`,
published by the Go gateway (the only process speaking HTTP to the outside) under `/api/v1` with an
`x-deadline-ms` budget, with an `{ok, data, error}` envelope. The **worker** (`stats-worker`) runs
every durable queue consumer and every schedule and answers no RPC. Ingest work is minutes-long,
IO-bound and bursty — one log parse holds a database session and one unacked delivery for as long as
the file takes — so it lives only in the worker: a decode never delays an RPC reply, the interactive
reads never share a channel with it, and exactly one process family owns the schedules.

| | `stats-svc` | `stats-worker` |
| --- | --- | --- |
| Compose service | `stats-svc` | `stats-worker` |
| Entry point | `serve_rpc.py` | `serve_worker.py` |
| Run command | `faststream run serve_rpc:app` | `faststream run serve_worker:app` |
| Registers | typed `rpc.stats.*` handlers only; the public reads on a channel of their own | `stats.ingest.<discipline>` (selected) + upload/tournament fanout, achievements, `tournament_encounter_completed`, `discord_member_changed`, the `cache.invalidated` consumer, the selected disciplines' own jobs (rank fetch + both registration rank checks: OverFast for Overwatch, Riot API for LoL, deadlock-api for Deadlock) |
| Schedules | outbox drain | rank collection, stall reaper (selected disciplines), failed-log retention, match fetch (selected disciplines), subscription collection, outbox drain; the debounced `stats.mv_entity_global_stats` refresh |
| Health | `GET :9100/health` | `GET :9100/health` |

Both share `src/core/lifecycle.py` (broker/cache/realtime/quota wiring, observability, client
close order). `GET /health` on the metrics listener (`WORKER_METRICS_PORT`, 9100 in dev and prod)
returns 200 only once the process finished starting, its broker connection answers and every one
of its consumers is running; otherwise 503 with the reason. `/metrics` stays Prometheus.

- **Selecting disciplines:** `STATS_DISCIPLINES` (comma-separated installed discipline codes, e.g.
  `overwatch,lol`). Omitted = every installed discipline. A configured empty value, an empty entry,
  a duplicate or an unknown code stops both processes at startup: there is no fallback.
- **Transport:** RabbitMQ request/reply (`rpc.stats.*`); no HTTP
- **Metrics:** Prometheus on `WORKER_METRICS_PORT` (dev 9100, prod 9100 in each container)

System overview: [`../../docs/architecture.md`](../../docs/architecture.md). Code layering:
[`../ARCHITECTURE.md`](../ARCHITECTURE.md). Shared kernel: [`../shared/README.md`](../shared/README.md).

## Responsibilities

- **Match-log ingestion** — owns the `stats.ingest_job` lifecycle and native observations in
  `stats.match`, `stats.match_team`, `stats.match_player`, `stats.segment`, `stats.fact` and
  `stats.event`. One match belongs to one existing live encounter game.
- **Catalog name resolution** — Overwatch map/gamemode/hero names resolve through canonical names
  or `catalog.entity.aliases`, scoped to the discipline and kind, never through code. Unknown names
  fail the attempt rather than silently dropping observations. After rollback, their
  `catalog.alias_miss` breadcrumbs are committed separately with the actual `stats.ingest_job` id;
  adding the missing alias and explicitly retrying preserves the original raw bytes.
- **Player resolution from logs** — resolves real workspace members and historical game
  participations, including substitutes and event-only players. Roster snapshot repairs and
  battlenet renames share the observation transaction; ingestion does not grant workspace access.
- **Native rank collection** — each game's module collector selects due accounts in `rank.account_state`
  (its `discipline`), fetches them upstream (Overwatch: OverFast career summaries per BattleTag; LoL:
  Riot API Solo/Duo and Flex per Riot ID; Deadlock: deadlock-api `/v1/players/rank`, up to 1000 Steam
  accounts per request) and keeps the per-account collection state, snapshot series and fetch log.
- **Achievement evaluation** — owns the condition-tree engine, the rules admin surface, the
  evaluation runs and the manual grant/revoke overlay.
- **MVP impact scoring** — derived stats (`PerformancePoints`, `Performance`, `ImpactPoints`,
  `ImpactRank`, `OverperformanceScore`), the versioned baselines they are scored against, and the
  idempotent historical backfill. The Workshop decoder and these formulas are the Overwatch module's (`shared/disciplines/overwatch/`: `ingest`, `impact`, `baselines`, `backfill`); stats-service reaches them through `shared.disciplines`.
- **Subscription entitlement collection** — periodic and on-demand re-checks of Boosty (Discord
  roles, asked of discord-service over RabbitMQ) and Twitch subscription entitlements used as a
  registration admission condition.
- **Public reads** — the statistics almanac (champion/winrate boards, players table, all-time
  records), one game's character playtime, leaderboard and maps, the `/users/*` player statistics
  (overview grid, profile, draft card, tournament/encounter/map/character/teammate/match histories,
  comparisons) and the achievement reads, with their Redis read caches, the `cache.invalidated`
  consumer that keeps them fresh and the global character-stats materialized view.
- **Global settings.** The per-tournament Discord channel binding (`stats.discord_channel`) is
  discord-service's (`rpc.discord.channel.*`).

## Interface

RPC namespace: `rpc.stats.*` (single namespace, registered in `src/rpc/`).

| Method group | Surface |
| --- | --- |
| `rpc.stats.logs.*` | Match-log admin: queue depths, processing history and stats (with each job's structured error, observation revision, current-provenance flag and, while awaiting link, its document teams), upload, retry (`reparse` + `expected_revision` for a done log), whole-tournament reprocess |
| `rpc.stats.ingest.*` | Canonical ingest: `submit`/`get` (workspace API key with `stats.ingest`) and the admin `bind` of an awaiting-link job to a game with the operator's team map |
| `rpc.stats.rank.*` | Public rank reads (user and game-account history, current ranks) plus collection admin: health stats, fetch log, trigger collection, re-enable auto-disabled accounts. `?discipline=` (default `overwatch`) picks the game's collector; a game without one answers 404 `rank_collection_unsupported` |
| `rpc.stats.ach.*` | Achievement rules CRUD, condition-type catalog and tree validation, seed/reset, export/import and cross-workspace library import, evaluation trigger and runs, rule test/dry-run, qualifying-user list, manual overrides |
| `rpc.stats.subscription.*` | Subscription collection admin: health stats, check log, per-user entitlement, trigger a re-check or a sweep |
| `rpc.stats.impact.*` | Superuser recompute of the impact-scoring baselines |
| `rpc.stats.catalog.sync`, `rpc.stats.catalog.sync_status` | Superuser `POST`/`GET /api/v1/admin/catalog-sync/{discipline}`: POST starts a background sync through `shared.disciplines` from that module's source (OverFast, Data Dragon or deadlock-api) and returns its first snapshot, 409 `catalog_sync_running` while one runs; GET reads the snapshot from Redis (`catalog_sync:{discipline}`, `null` when none). Stage changes are published to the starter's `user:{id}:catalog-sync` topic (`src/services/catalog_sync.py`) |
| `rpc.stats.settings.*` | Superuser global settings CRUD (`public.settings`) |
| `rpc.stats.statistics.*` | Public statistics: `character_playtime`, `character_leaderboard`, `maps`, `champion`, `winrate`, `players`, `records` (see [Public reads](#public-reads)) |
| `rpc.stats.users.*` | Public `/users/*` player statistics: `overview`, `overview_stats`, `overview_catalog`, `compare`, `compare_characters`, `get_profile`, `draft_card`, `tournaments`, `tournament`, `tournament_encounters`, `tournament_leaderboard`, `maps`, `maps_summary`, `encounters`, `matches_summary`, `characters`, `teammates`. The player directory, search and name lookup stay app-service's (`rpc.app.users.{list,search,by_name}`) |
| `rpc.stats.achievements.*` | Public achievement reads: `list`, `get`, `user` (a user's earned/locked achievements), `users` (the earner list of one achievement). Not to be confused with the `rpc.stats.ach.*` rules admin |

The full method list with request/response schemas is published at `/api/docs`, generated from
`src/openapi_schemas.py` (`OPERATIONS`) and `src/openapi_docs.py` (`DOCS`).

### Public reads

| HTTP (`GET /api/v1/…`) | Subject |
| --- | --- |
| `statistics/{discipline}/characters/playtime`, `statistics/{discipline}/characters/{entity_id}/leaderboard`, `statistics/{discipline}/maps` | `rpc.stats.statistics.{character_playtime,character_leaderboard,maps}` |
| `statistics/champion`, `statistics/winrate`, `statistics/players`, `statistics/records` | `rpc.stats.statistics.{champion,winrate,players,records}` |
| `users/overview`, `users/overview/stats`, `users/overview/catalog` | `rpc.stats.users.{overview,overview_stats,overview_catalog}` |
| `users/{id}/profile`, `users/{id}/draft-card` | `rpc.stats.users.{get_profile,draft_card}` |
| `users/{id}/compare`, `users/{id}/compare/characters` | `rpc.stats.users.{compare,compare_characters}` |
| `users/{id}/tournaments`, `users/{id}/tournaments/{tournament_id}`, `…/encounters`, `…/leaderboard` | `rpc.stats.users.{tournaments,tournament,tournament_encounters,tournament_leaderboard}` |
| `users/{id}/maps`, `users/{id}/maps/summary`, `users/{id}/encounters`, `users/{id}/matches/summary`, `users/{id}/characters`, `users/{id}/teammates` | `rpc.stats.users.{maps,maps_summary,encounters,matches_summary,characters,teammates}` |
| `achievements`, `achievements/{id}`, `achievements/{id}/users`, `achievements/user/{user_id}` | `rpc.stats.achievements.{list,get,users,user}` |

Gateway route tables: `gateway/internal/stats/routes.go` (`PublicReadRoutes`, `AchievementsSubtreeRoutes`); the
anonymous response-cache allowlist is `PublicCacheableReads` (`cacheable.go`). Handlers: `src/rpc/statistics.py`,
`src/rpc/users.py`, `src/rpc/achievement_reads.py`, over `src/services/{statistics,hero,map,user,achievement_reads}`
(layering enforced by the `read-services-layers` contract in `.importlinter`).

**Disciplines.** Every game-shaped statistics read names its `discipline` (422 absent, 404 `discipline_not_installed`),
except the champion/winrate boards, the players table and the records, where it is optional (absent or `all`: every
game; the parsed-log records then are left out). Every `/users/*` statistics read takes a required `discipline`, except
the tournaments and encounters tabs, where it is optional (absent or `all`: every game, each row naming its own
`discipline`; `mvp1` then is a 422); the per-tournament reads use their tournament's own game. Readers use native
`stats.fact`/`stats.stat_def` queries bound to the request's explicit discipline (`UserService.of(code)`,
`HeroQueries.of(code)`) and workspace-member ownership; historical observations survive membership removal. The
per-user maps read filters by `mode_id` and expands `parent` / `character_stats`. GET role filters carry JSON
`RoleRef`s: on overview, overview stats and overview catalog reads omission means no filter, while explicit
`role=null` selects no rated-role assignment (the UI's Flex chip); compare controls do not offer Flex.

**Semantics.** Profile and achievement match expansions bulk-load bound games and their historical participant slots:
home/away means slots 1/2, never ingestion source order or today's active seats. `map_index` is the game's position.
Hidden-tournament policies, strict >60-second character qualification, the 600-second leaderboard threshold, rank
ties and null handling are preserved. Profile/comparison per-10 denominators are match duration; character
leaderboards use character playtime. MVP placement prefers ImpactRank over Performance. See
[player statistics semantics](../../docs/users-identity.md#93-public-player-app-service-identity-stats-service-statistics).
Native floating-point reductions have a fixed observation order: match and historical workspace member, then
character/stat identity when a group spans them; rolled-up character totals use character identity order. A last-bit
difference against the legacy executor can move a displayed total by 0.01 at a rounding boundary; the P4 parity
policy proves these changes bit-for-bit from the frozen operands.

**Channel.** `serve_rpc.py` registers the three read modules on `_PUBLIC_READS_CHANNEL`, a channel of their own with
`RPC_PREFETCH_COUNT`. That prefetch applies per consumer (FastStream `global_qos=False`), not to the channel, so it does
not ration a burst of cold 20–30 s compare reads against the admin/ingest RPC handlers: all of them draw on the
process's one pool of `RPC_PREFETCH_COUNT` handler permits (`shared.rpc.deadline.configure_rpc_concurrency`).

**Read caches.** The `/users/*`, map and achievement-rarity reads are cashews caches declared with
`shared.services.cache_generations.versioned` on Redis `/4` (prefix `backend:`; `lock:`, `LOCK` and `PING` are
registered there too for stampede protection, `src/core/caching.py`). Their keys carry the
`shared.services.user_cache` generations: `TOURNAMENT_DATA` (every tournament write `emit`s it), the subject user's
generation (bumped by app-service profile/identity edits) and, for the compare reads, any user's. Nothing is
invalidated by pattern; the TTLs (`USERS_CACHE_TTL`, `USER_PROFILE_CACHE_TTL`, `ACHIEVEMENTS_CACHE_TTL`) are the
safety net. The RPC process FLUSHDBs `/4` at startup, so a redeploy never serves entries written by the previous
image's serializers (app-svc's startup flushes the same database).

**Invalidation consumer (worker).** `cache_invalidation_stats_service` (`CACHE_INVALIDATION_STATS_QUEUE`), bound to
the `cache.invalidation` exchange (`cache.invalidated.#`), on its own channel (prefetch 4). A service whose write
stales a tournament resource enqueues a `CacheInvalidatedEvent` through the transactional outbox
(`shared.services.realtime.enqueue_invalidation_outbox`). On each event (`shared/services/realtime/consumer.py`) the
worker re-bumps the event's generations — the writer's commit already bumped them; this is the durable retry — and,
on `tournament.standings`, requests the materialized-view refresh below. Worker replicas share the queue; no other
service may consume it.

**`stats.mv_entity_global_stats` refresh (worker).** `src/services/hero_stats_refresh.py`, requested at worker startup
and on every `tournament.standings` invalidation. Debounced to one run per hour by the Redis key
`backend:hero_global_stats:refresh_cooldown` (`SET NX EX`, shared by every replica), guarded by a Postgres advisory
lock, executed with `statement_timeout` disabled and `work_mem` raised, as a background task that never blocks the
consumer. `stats01` populates the view during migration; runtime refreshes use `CONCURRENTLY`, an explicitly
unpopulated rebuild a first plain refresh. Unpopulated reads and refresh failures are errors, not empty statistics.
The refresher role must own this MV and have SELECT on its native sources; ordinary readers need only SELECT on it.

### Queues consumed (worker)

| Queue | Event | Effect |
| --- | --- | --- |
| `upload_match_log` | `UploadMatchLogEvent` | Persist the original decoded bytes to a content-addressed S3 key, create/find the native ingest job and commit its ingest request (carrying the upload's `correlation_id`/`channel_id`/`message_id`) in the same transaction |
| `stats.ingest.<discipline>` | `ProcessIngestJobEvent` | Process one authorized `ingest_job_id` of that discipline (a job of another discipline is rejected to the DLQ untouched); one queue per selected discipline, each on its own channel, prefetch 2 |
| `stats.ingest.<discipline>.replay` | `ProcessIngestJobEvent` + `reparse_expected_revision` | Revision-fenced reparse of one DONE job asked for by a tournament-wide reprocess; **no message TTL** (a DONE job is not reaper-recoverable), own `.replay.dlq`, one at a time; declared/consumed only by workers selecting the discipline |
| `process_tournament_logs` | `ProcessTournamentLogsEvent` | Re-pend the tournament's actual native jobs, each committed with its ingest request in the outbox, including imported raw references |
| `achievement_evaluate` | `AchievementEvaluateEvent` | Run the achievement engine for a workspace |
| `achievement_evaluate.deferred` | `AchievementEvaluateEvent` | Resumes a `queued` run an unverified workspace's manual/`rule_version_bump` recompute was parked as; own channel, prefetch 1 |
| `tournament_encounter_completed` | `EncounterCompletedEvent` | Bound to the `tournament.events` exchange; fills in the encounter's Push/Clash map scores (`match_logs/objectiveless.py`), then enqueues an achievement evaluation |
| `tournament_registration_approved` | — | Bound to the same exchange; prioritises and enqueues a rank check for the approved player |
| `tournament_registration_rank_check` | `RegistrationRankCheckRequestedEvent` | Same rank check, asked for by the registrant from their own card |
| `rank_fetch`, `rank_fetch_priority` | `FetchRankEvent` | One OverFast call per battle tag; shared channel with prefetch `RANK_FETCH_WORKER_PREFETCH` |
| `lol_rank_fetch`, `lol_rank_fetch_priority` | LoL fetch request | One Riot API fetch per Riot account; shared channel with prefetch `LOL_RANK_FETCH_WORKER_PREFETCH` (3) |
| `lol_rank_registration_approved`, `lol_rank_registration_rank_check` | — | Bound to the same exchange (routing keys `tournament.registration.approved` / `.rank_check_requested`); priority-fetch the Riot accounts of an approved LoL registrant, or of one asking for a re-check |
| `deadlock_rank_fetch`, `deadlock_rank_fetch_priority` | `DeadlockFetchRequest` (up to 1000 Steam accounts) | One deadlock-api `/v1/players/rank` request per batch; shared channel with prefetch 1 |
| `deadlock_rank_registration_approved`, `deadlock_rank_registration_rank_check` | — | Bound to the same exchange (routing keys `tournament.registration.approved` / `.rank_check_requested`); priority-fetch the Steam accounts of an approved Deadlock registrant, or of one asking for a re-check |
| `discord_member_changed` | `DiscordMemberChangedEvent` | Re-resolves the member's Boosty entitlement in every workspace bound to the guild (`subscription_collection/member_events.py`); own channel, prefetch 2; the scheduled sweep stays the slow reconciliation |
| `cache_invalidation_stats_service` | `CacheInvalidatedEvent` | Bound to the `cache.invalidation` exchange; re-bumps the event's cache generations and, on `tournament.standings`, requests the debounced MV refresh (see [Public reads](#public-reads)); own channel, prefetch 4 |

Every one of those queues carries `x-dead-letter-exchange=dlx` and an `x-message-ttl`; the worker
declares and binds its own DLQs at startup, so an expired or rejected job is visible in
`<queue>.dlq` instead of being dropped by an unbound routing key.

Each `stats.ingest.<discipline>` queue gets a channel of its own because ingest is the one minutes-long
handler here: a delivery that outlives RabbitMQ's `consumer_timeout` closes its whole channel, and that
must not take another game's ingest, `upload_match_log`, `process_tournament_logs` or
`achievement_evaluate` down with it. Every producer (outbox, reaper, retry, tournament fanout) routes by
the job's discipline through `shared.messaging.config.ingest_queue`; the admin queue-depth monitor
lists the selected disciplines' ingest queues.

### Ingestion path

1. **Arrival.** The gateway relays a multipart upload as base64 to `rpc.stats.logs.upload`
   (`log.create` on the tournament's workspace), or Discord publishes `UploadMatchLogEvent`.
   Discord resolves the uploader through their linked social account; source is `discord` or
   `upload`. Filenames are display metadata, not job identity.
2. **Store.** `uploads.py` validates size, UTF-8, a finished log, and a filename of at most
   500 characters without path separators, `..` or NUL. It hashes the actual bytes (SHA-256),
   stores those same bytes at `logs/{tournament_id}/{content_hash}`, then records the job.
   A failed PUT never creates a dangling job; a failed DB insert may leave an unreferenced object.
   Imported `raw_ref` values are preserved and remain readable by their job ids.
3. **Deduplicate.** New uploads use `external_id = NULL` and a workspace/content-hash unique key.
   Concurrent uploads of identical bytes return the same job without resetting its status,
   attempts, filename, uploader or hints. Same filename with different bytes creates distinct
   jobs and objects. A same-workspace hash with conflicting discipline/tournament intent returns
   `stats_upload_scope_conflict` (409); invalid owner/game hints return
   `stats_upload_hint_conflict` (422). Different workspaces never deduplicate together.
4. **Enqueue and claim.** `ProcessIngestJobEvent` carries only `ingest_job_id` plus common event
   metadata. Processing uses that row's authorized `raw_ref`, checks the stored hash, and commits
   the `processing` claim/attempt before parsing. Ownership is the exact saved
   `(attempts, started_at)` pair, checked before observations, completion and failure writes;
   an explicit retry may reset the attempt budget but cannot revive an old worker's claim.
   A delivery finding an active claim acknowledges without parsing or publishing a terminal
   result. Duplicate terminal delivery returns the persisted state. Bulk processing enumerates
   native jobs, never guessed S3 filenames.
5. **Bind before replacement.** `ingest/process.py` loads the job's stored document envelope
   (`{document, producer}`); a raw job without one is decoded by the discipline module's
   `INGESTORS[(discipline, source_kind)]` (unknown pair: `unsupported_ingestor`) and gets a
   `decoded` envelope. The document is validated against the workspace vocabulary, then
   `ingest/identity.py` looks its participants up **read-only** (provider-constrained exact handle;
   a decoded Workshop name also matches the part before `#`; several players behind one identity
   narrow to the workspace's own, else `identity_conflict`) and `ingest/binding.py` searches
   non-cancelled games of the workspace/discipline on the document's map (a hinted or linked document
   may also take a game that names no map yet; a mode only has to agree when game and document both
   have one). A document team is
   tied to a seat only by identity: every known participant rostered on that one seat and no
   other, at least one, and the teams map one-to-one onto the game's participating teams (inactive
   historical seats count). A unique fitting game is the binding whether or not it already has an
   observation; several fitting games, or none, persist `awaiting_link` with the document, a
   structured explanation and **zero** writes (no virtual identity, anchor, observation or success
   event). Without a hint (and not pinned to a linked game by a reparse) the one fitting game must
   also hold **every** participant on the line-up of the seat their team maps to; a participant
   outside it (unknown, rostered after the line-up was taken, another team's member) leaves the
   document `awaiting_link`. A hint only narrows candidates: a hinted game the participants contradict (or that
   plays another map or mode) fails with `binding_mismatch`, never a binding. Stage-generated seats carry their
   team's roster line-up (tournament-service, P8); stage encounters generated before that have none.
6. **Write atomically.** Final lock order is encounter, game, job, existing `stats.match`; the
   claim token, roster evidence, map, mode and the tournament/stage/round pool are checked again under
   them: the pool's map items refuse another map (`map_not_in_pool`), its mode items another mode
   (`mode_not_in_pool`); a pool of only maps or only modes leaves the other free. Only then are virtual
   players (`auth_user_id` NULL, no visibility row) and observation anchors created
   (`insert_observation_members`: `workspace_member.observed_only = true`, `removed_at` stays NULL;
   token memberships, hidden-workspace visibility and link-time role autofill skip such anchors, a
   real admission through `get_or_create_workspace_member` clears the flag, a genuinely removed
   member is never touched), the discipline's `derive_match`
   runs (decoded input only, fed P4's tournament-player registration rank; a canonical document
   persists exactly what it supplied, and Push/Clash score normalization only touches decoded
   observations) and `writer.write_observations` replaces children via `replace_observations` and increments the
   revision once. Match team rows keep the document's array order as `source_position`. The
   `match.ingested` outbox event (`match.ingested:{match_id}:{revision}`: placements, the observed map
   and mode — an accepted result fills a game that names neither — and the
   participants the bound roster lacks, observed roles as dimension/role codes), the tournament
   invalidations, the `done` transition and the two disjoint evidence records
   (`stats.reparse` for the match, `stats.job_transition` for the job) share one commit. The
   header (id, workspace, discipline, game) is never rebound; its map and mode are the latest observation's.
7. **Failure and result.** Decode, validation or write failures roll back the observation
   transaction, then mark the matching claim `failed` in a separate fenced transition with a
   structured `{code, message, issues}` error (`error_message` holds that JSON; historical text
   reads as code `historical`), preserving the previous revision. A superseded claim changes
   nothing. After commit the worker sends the actual state in `MatchLogProcessedEvent` (only
   for jobs somebody waits on: a tournament hint or a correlation id).
8. **Admin bind and reparse.** `POST /api/v1/admin/logs/{id}/bind` (`rpc.stats.ingest.bind`,
   workspace `log.update`) takes the operator's complete team map
   (`document team key -> encounter.team id`) and an optional `expected_revision` (`0` none,
   `n` that revision; required when the target is occupied). It never carries the document: the
   job's stored document is validated, bound and published by the same writer in **one**
   transaction that also claims the job, so no broker delivery competes and a refusal
   (`stale_revision`, `binding_mismatch`, `identity_conflict`, `invalid_team_map`, `ingest_busy`)
   leaves the parked job exactly as it was. The operator's map is checked against the line-ups
   (`check_forced_teams`) and, for the participants no line-up places, against the encounter's
   tournament rosters (`check_roster_owners`): one rostered on another team of the tournament (a
   reversed map over seats without a line-up, a third team's member) is `binding_mismatch` — the
   match layer's `extra_member_other_team` rule applied before anything is written (mix encounters
   skip it). Retry of a `done` log is refused
   (`reparse_required`); `retry` with `reparse=true` and the `expected_revision` the operator saw
   replays it directly with its original team mapping (document keys joined to the match's
   `source_position`): a canonical job reloads its document, a decoded one decodes its raw bytes
   anew. A job no longer the game's current provenance answers `stale_binding`.
   Tournament-wide processing never re-pends a `done` job: current ones replay through this branch
   with the revision seen at selection (stale/busy outcomes are logged per job); only
   pending/failed/awaiting jobs use the queue. `GET /api/v1/admin/logs/games/{encounter_game_id}/observation`
   (`rpc.stats.ingest.game_observation`, workspace `log.read`) answers the target game's current observation
   (`match_id`, `revision`, `ingest_job_id`, `is_historical`) or `null`: the authoritative `expected_revision`
   for a bind.

**Result routing.** A Discord upload's `channel_id`/`message_id` (and `correlation_id`) ride the
job's `ProcessIngestJobEvent` and come back on its `MatchLogProcessedEvent`, published to the
`match_log_result` work queue; whichever bot replica consumes it reacts on that message, so no
replica keeps an in-memory waiter. A failure before any job exists answers with the same ids.
Filename/tournament are display fields only. A pending or failed job is never inferred from a
latest-by-filename database query.

**Follow-up and recovery.** Successful observation writes enqueue `AchievementEvaluateEvent`
with `stats.match`, `stats.fact` and `stats.event`; a job reaching `done`/`failed`/`awaiting_link`
(and a new upload) uses `stats.ingest_job`. Their `event_id` is
`achievement:<workspace>:<tournament or 0>:<source>:<key>`, unique per emission (`event_outbox.event_id`
is UNIQUE). Every transition to `pending` stages its ingest request. These durable outbox rows and
their creation evidence share the writing transaction; both stats processes drain the outbox every
second. The reaper
claims stalled `pending`/`processing` jobs with `FOR UPDATE SKIP LOCKED`; only entering processing
costs an attempt. Exhausted claims become `failed`. Neither `failed` nor `awaiting_link` is
automatically retried. Explicit admin retry resets the budget after ownership/hint validation.

**Maintenance cutover.** Drain the retired `process_match_log` queue (and its `.dlq`) before deploying
the per-discipline queues: no consumer reads it afterwards and there is no compatibility adapter.
The outbox event type is `process_ingest_job`.

### Achievement engine

Rules are data, not code. An `achievements.rule` row carries a JSON condition tree of `AND` / `OR` /
`NOT` nodes over leaf conditions; each leaf is `{"type": ..., "params": {...}}` dispatched through a
decorator-populated registry (`shared/domain/achievements/registry.py`, one table per discipline), so
adding a condition type means adding one executor registered by the discipline's module (Overwatch:
`shared/disciplines/overwatch/achievements/conditions/`), and authoring an achievement means editing
JSON through the admin API. A discipline with no `achievement_conditions` hook (LoL) has no
conditions, and `NOT` needs its `achievement_eligible_keys` hook: unsupported games are rejected,
never evaluated against an empty universe. Evaluation returns sets of tuples whose shape follows the rule's grain — `(user_id)`,
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

**Every rule belongs to one discipline, and nothing writes or evaluates across that line.** The discipline is
explicit on create, seed/reset, condition metadata, validation, manual evaluation, export/library requests and every
portable rule (there is no default; `achievements.rule.discipline` has none since `achievement06`), is immutable once
set, and must be enabled for the workspace. A rule's `entity_id` is a `character` of its own discipline; a missing,
foreign or wrong-kind one is a 422, never a cleared link. `UNIQUE(workspace_id, slug)` stays the identity, so a slug
held by another discipline's rule is a 409 that leaves that rule alone. Seeding needs the discipline's
`achievement_catalog` (no hook: 422 before any deletion) and replaces, resets and clears results for that
discipline only. Portable format v2 (`schema_version: 2`, `discipline`, `entity_id`) is the only accepted shape —
v1 and `hero_id` are validation errors, not aliases — and a batch is validated whole before the first rule or image
write.

The runner resolves the trigger's owner (tournament and/or match, verified against the workspace) *before* selecting
rules: a tournament or match trigger evaluates only its discipline's rules, a workspace-wide trigger partitions the
stored rules by discipline, and each discipline gets its own grid, normalizer and leaf cache. `rule_ids=None` is
the unrestricted selection (enabled rules), `[]` selects nothing, and a deferred run persists the concrete ids it
resolved so a later seed or import cannot widen it. A rule whose discipline has no conditions, or no required grid,
is reported on the run and its stored results are left untouched.

**Verified live (opt-in, `RUN_P5_LIVE_SMOKE=1`, P5's real-process stack).** `test_ingest_live_smoke.py` seeds one rule per
Overwatch case plus a LoL *sentinel* rule and award, then asserts on native rows: an Overwatch ingest reaches `done`, the
writer's `AchievementEvaluateEvent` (through the outbox) makes the worker award exactly the three qualifying members once
(evidence carries the rule slug, run `parse_complete`); the standings invalidation still reaches its original
tournament-service consumer (a computation job exists); completing the best-of-3 encounter evaluates again and converges;
redelivering the same event twice creates and removes nothing; awaiting-link and failed ingests award and observe
nothing; a LoL ingest reaches `done` and its run only reports that LoL has no conditions — the sentinel survives and no
Overwatch award, run or event touches the LoL tournament. Analytics is a separate process and is covered by
`analytics-service/tests/test_discipline_runtime_smoke.py`.

**Verified live for both games (opt-in, `RUN_P8_LIVE_SMOKE=1`, the same stack plus app-service and balancer-service).**
`test_two_game_live_scenarios.py` runs the Overwatch and LoL ingest lifecycle (concurrent identical uploads → one job;
changed content or another game's document under the same key → `409 idempotency_conflict`; a new-id correction →
same match, revision 2, exact native reads), hinted binding by seeded stage line-ups, awaiting-link → admin bind
(stale and reversed maps refused, the right map `done`), the `logs_official` matrix (disabled, accepted, duplicate,
late `result_locked`, admin-locked), five single-field diagnostics (`unknown_code`, alias-miss row, no observation)
and LoL's empty condition registry (`condition-types` 200 `[]`, no LoL award). 10 passed / 1 skipped (the source flag)
at `8588e360e`; recipe in the P5 release note, section 15.1.

### Rank synchronisation

Collection is bound to a linked `social_account` (a battlenet account owned by a player), never to a
bare BattleTag string: `rank.account_state` is keyed on `social_account_id`, and the
snapshots it produces are attributed to that account's user. An unlinked tag is not collected.

Per-tag state carries `next_eligible_at`, `consecutive_failures` and `status`. On success the tag is
rescheduled at the admin-configured `interval_seconds` with jitter and the failure counter resets.
A **private** profile is not a failure: the status becomes `private`, failures reset, and the tag is
rescheduled at 4× the base interval — the account still exists and may be opened later. `not_found`
gets 8×. A permanent failure backs off exponentially (`backoff_base_seconds * 2^n`, clamped to six
hours) and, once `max_consecutive_failures` is reached, disables the tag. Transient upstream failures
(OverFast 5xx/timeouts, 429) back off the same way but never disable, because an outage would
otherwise permanently disable healthy accounts with no recovery path;
`rpc.stats.rank.reenable_disabled` is the operator escape hatch for tags disabled in the past.
Redis carries the rest of the protection: per-account enqueue and in-flight dedup keys, a fixed
per-minute window (over it a tag is deferred past the window rather than fetched — the only rate
control the priority queue has, since registration approvals bypass the scheduler's pacing) and a
global cooldown key set on a 429.

League's collector (`shared/disciplines/lol/collector.py`) follows the same rules for `riot`
accounts, keyed `lol_rank:*`. It has no `private` status, and a Riot 401/403 (missing or expired key)
is transient. A 400 on a stored PUUID means it was minted under another Riot project's key: the fetch
re-resolves the PUUID once by Riot ID, and if that also fails it clears `external_id` and `region`.
Only a verified Riot account's RSO subject is trusted as its PUUID.

Deadlock's collector (`shared/disciplines/deadlock/collector.py`) follows the same rules for `steam`
accounts, keyed `deadlock_rank:*`, with a batched upstream: the tick claims up to `batch_size` (≤ 1000)
due accounts and publishes **one** fetch; the consumer asks `GET /v1/players/rank?account_ids=…` once,
with no transaction open, then writes every account's outcome in one transaction. A badge
(`tier * 10 + subrank`) appends a snapshot only when it changed; badge 0 is ok and unranked; an
account missing from the answer is `not_found`; a handle that is not a Steam account id is never sent
and is `disabled` after `max_consecutive_failures`. A failed batch (5xx, timeout, open circuit, 429)
defers every claimed account by `backoff_base_seconds` without counting a failure and logs one summary
row; a 429 also sets `deadlock_rank:cooldown`. `rate_limit_per_minute` counts requests (20 without
`DEADLOCK_API_KEY`, 100 with it). There is no per-account pending/in-flight dedup.

### Events published

- `match_log_result` (work queue) — `MatchLogProcessedEvent` with the upload's `channel_id`/`message_id`, consumed by discord-service.
- `stats.ingest.<discipline>` — the ingest request, staged on the outbox with the job, and by every transition to `pending` (tournament-wide requeue, retry, the stall reaper; `stats.ingest.reclaimed` counts reaper outcomes).
- `process_tournament_logs` — through the outbox, with the admin audit row.
- `achievement_evaluate` — transactionally enqueued for native observations, new uploads, terminal job statuses and `EncounterCompletedEvent`.
- `achievement_evaluate.deferred` — through the outbox, with the run row: a manual or `rule_version_bump` run for a workspace whose
  `verification_status` is `unverified`: the run row is created `queued` and the message carries its
  id, so the consumer finishes that row instead of opening a second one. `parse_complete` is never
  deferred.
- `rank_fetch` / `rank_fetch_priority` (Overwatch), `lol_rank_fetch` / `lol_rank_fetch_priority`
  (LoL) and `deadlock_rank_fetch` / `deadlock_rank_fetch_priority` (Deadlock) — from the collection
  tick, the admin collect RPC and registration approval.
- Through the transactional outbox (`public.event_outbox`): achievement evaluation and tournament
  score/cache invalidations; `EncounterCompletedEvent` is emitted when the encounter is already
  completed, without accepting a live-game result on the log's authority.

### Realtime

`logs.updated` on the workspace-scoped topic `workspace:{id}:logs`, published straight to Redis for
the gateway to relay to the admin log monitor. Non-durable and payload-free: no journal row, no
replay cursor — the monitor refetches `/admin/logs/history` on the signal and does an initial fetch
on subscribe, so a missed signal self-heals, and the actual log data stays gated by `log.read`.

### Scheduled work

The jobs below are APScheduler interval jobs guarded by a Redis leader lock, so only one replica acts
per tick. Each rank collector also runs a fetch-log purge without a lock, because its delete is
idempotent (`ow_rank_fetch_log_purge`; `lol_rank_fetch_log_purge` and `deadlock_rank_fetch_log_purge`, daily,
7-day retention).

| Job | Cadence | What it does |
| --- | --- | --- |
| OverFast rank collection | 60s tick | Selects and *claims* due battle tags and publishes one `FetchRankEvent` each — it never calls OverFast itself. Per-tag cadence comes from `next_eligible_at`, so changing the admin interval needs no restart. No-ops while collection is disabled in settings. |
| LoL rank collection | 60s tick | The same for League (`lol_rank:*` keys, `lol.rank_collection` settings): claims due Riot accounts and publishes one fetch each. Off by default. |
| Deadlock rank collection | 60s tick | The same for Deadlock (`deadlock_rank:*` keys, `deadlock.rank_collection` settings): claims up to 1000 due Steam accounts and publishes them as one batched fetch. On by default (seeded by `deadlock01`). |
| Match-log stall reaper | `LOG_REAPER_TICK_SECONDS` (300s) | Requeues native jobs dropped by the queue: `pending` older than `LOG_REAPER_PENDING_AFTER_SECONDS` and `processing` older than `LOG_REAPER_PROCESSING_AFTER_SECONDS`. Exhausted attempts become `failed`; awaiting-link is never claimed. Keep the pending threshold above the queue TTL. |
| Failed match-log retention | 1h tick | Deletes only expired failed jobs whose raw reference is unused by another job or match. A linked match keeps both its job row and raw object, not an orphaned object with no usable reference. Storage deletion failure keeps the row; an upload's raw-key lock prevents concurrent deletion. Alias breadcrumb SET NULL and deleted-owner evidence share the deletion transaction. Invalid/uncompleted uploads are rejected before persistence; processing never deletes raw bytes as validation cleanup. |
| Match fetch | 60s tick (selected disciplines with a `match_fetchers` entry) | Import by external id (`stats.match_fetch`, `src/services/ingest/fetch.py`): per discipline, under that discipline's own Redis lease (`stats:match_fetch:leader:<code>`, shared by every worker selecting it, renewed before each attempt), calls the module's fetcher for up to 20 due `pending` rows. `MatchFetchNotReady` backs off 1, 2, 5, 10, 20, 40 min then hourly, until 24 h after the request (`failed`, `last_error`); `MatchFetchFailed` fails at once. Fetched bytes are stored and queued exactly like an upload (`logs/{tournament}/{sha256}`, the normal ingest job with the game hint). Requests come from tournament-service over the internal `rpc.stats.ingest.fetch` / `fetch_list`; one workspace's match id is reserved for one game (a transaction advisory lock serializes concurrent submissions, the loser gets 409 `match_already_imported`); organizer warnings (`fetch_failed`, `participants_dropped`, `banned_character_played`) are derived on the list read. |
| Subscription collection | 60s heartbeat | Decides inside the tick whether the admin-configured `interval_seconds` has elapsed (read from the append-only check log), then re-checks entitlements for active tournament participants. |

## Data owned

Writes:

- `stats` — `ingest_job`, `match_fetch`, `match`, `match_team`, `match_player`, `segment`, `fact`, `event` and
  `stat_baseline`. `stats.discord_channel` sits in this schema but discord-service writes it.
- `rank` — `account_state`, `rank_snapshot`, `fetch_log` (every game; `discipline` names it).
- `achievements` — `rule`, `evaluation_result`, `evaluation_run`, `override`.
- `catalog` — `alias_miss` for unresolved Overwatch log names, plus `entity` aliases and rows
  written by each discipline module's sync; app-service owns the public catalog reads and generic admin CRUD.
  No runtime access to the legacy `overwatch` schema remains.
- `subscriptions` — `entitlement`, `check_log` (shared with tournament-service, which owns
  requirements).
- `public.settings` — global key-namespaced settings.
- As a side effect of ingestion: `players.social_account` for battlenet renames and
  `encounter.team_member` snapshots for real workspace members observed as substitutes.
- `public.audit_log` and `public.event_outbox` for transactional evidence and follow-up delivery.
- `stats.mv_entity_global_stats` — refreshed by the worker (see [Public reads](#public-reads)).

Reads: native `encounter.*` encounters, participations and games; `tournament.*` bracket/team/player
data; `public.workspace`, `public.workspace_member`, the division grid and actor identities; for the public reads
also `players.user` and its social accounts, `achievements.*` effective sets (`shared.services.achievement_effective`)
and the MV.
No runtime reads or writes of the retired `matches` or `log_processing` schemas are needed.

No service ships its own migrations — there is one Alembic project at
[`../migrations/`](../migrations/). Entity diagrams for these tables:
[`../../docs/database_erd.md`](../../docs/database_erd.md), sections *stats*, *tournament*,
*ranks*, *achievements*, *catalog* and *subscriptions*.

## Dependencies

- **PostgreSQL** — the shared SQLAlchemy metadata from `backend/shared/`; one database for all
  services.
- **RabbitMQ** — RPC transport, durable job queues, the tournament event exchange, the match-log
  result queue and the DLQs.
- **Redis** — scheduler leader locks, rank-collection dedup/rate-limit/cooldown keys, the cashews
  cache on `/4` (public read caches and their stampede locks, impact baselines, the MV refresh cooldown),
  and the realtime publish channel and cache generations.
- **S3** — new raw logs at `logs/{tournament_id}/{content_hash}` (imported keys remain unchanged)
  and catalog images at `assets/{discipline}/{kind}/{slug}.{ext}`; an image already stored survives sync.
- **OverFast API** (self-hosted on the production host, called directly) — player career
  summaries for rank collection and the Overwatch module's hero/map/gamemode catalog; the
  hero sync pulls all 13 Blizzard locales and only ever adds aliases. OverFast exposes no
  `locale` parameter for `/maps` or `/gamemodes`, so their aliases are admin-supplied.
- **Riot API** (called directly, `X-Riot-Token`) — the LoL rank collector: account-v1 on
  `RIOT_ACCOUNT_CLUSTER` (Riot ID ↔ PUUID, region) and league-v4 on the account's platform host.
  PUUIDs are encrypted per Riot project, so a key change re-resolves every account once.
- **Data Dragon** — the League of Legends module's champion and map catalog, using the
  latest published version.
- **deadlock-api** (`https://api.deadlock-api.com`, called directly; `X-API-KEY` when
  `DEADLOCK_API_KEY` is set) — the Deadlock module's catalog (`/v1/assets/heroes`, `/v1/assets/map`),
  rank collector (`/v1/players/rank`) and match fetcher (`/v1/matches/{id}/metadata`).
- **valorant-api.com** (`https://valorant-api.com`, public, no key) — the VALORANT module's catalog
  (`/v1/agents`, `/v1/maps`: bomb-site maps only). All four catalog sources mirror images through
  `shared.catalog_sync`.
- **discord-service** (RabbitMQ RPC `discord_member_roles`) — Boosty entitlement verification; this
  service holds no Discord bot token.
- **Twitch API** — Twitch subscription verification, egressing through the outbound **`proxy`**
  container.

Sync adds missing rows and aliases without overwriting an existing row's name or `attrs`, including
admin-edited classes and map flags. New Overwatch maps start with `attrs.in_competitive = true`.
An existing parent is never replaced: a source parent fills `parent_id` only when it is null.
Images already on the bucket survive, and rows absent from a later source response are not deleted
or deactivated.

Adding a catalog row or alias needs no deploy: sync the whole discipline or use
`/api/v1/admin/catalog/{discipline}/{kind}[/{id}]`. The existing Overwatch pages
`/admin/{heroes,maps,gamemodes}` adapt to that API; `/admin/aliases` attaches `{entity_id, alias}`
to a matching discipline and kind and closes the miss in one request.

## Configuration

`backend/env/stats.env`, layered on `backend/env/common.env` (see
[`stats.env.example`](../env/stats.env.example)); both processes read it. Settings that actually change behaviour:

- **Public read caches** — `USERS_CACHE_TTL` (300 s, the tournament-derived `/users/*` caches),
  `USER_PROFILE_CACHE_TTL` (60 s) and `ACHIEVEMENTS_CACHE_TTL` (300 s, the per-workspace rarity
  aggregate). The profile TTL is short on purpose: identity-service avatar/name edits have no
  cross-service invalidation hook, so that TTL is the only bound on their staleness.
- **Disciplines** — `STATS_DISCIPLINES` (see above).
- **Ingestion caps** — `MAX_MATCH_LOG_BYTES` (25 MiB); `MAX_MATCH_LOG_LINES` (500k) is read by the Overwatch decoder (`shared/disciplines/overwatch/ingest.py`).
- **Stall reaper** — `LOG_REAPER_ENABLED`, `LOG_REAPER_TICK_SECONDS`,
  `LOG_REAPER_PENDING_AFTER_SECONDS`, `LOG_REAPER_PROCESSING_AFTER_SECONDS`,
  `LOG_REAPER_MAX_ATTEMPTS`, `LOG_REAPER_BATCH_SIZE`.
- **Failed-log retention** — `FAILED_LOG_RETENTION_DAYS` (14).
- **OverFast** — `OVERFAST_BASE_URL`, `OVERFAST_TIMEOUT`, `OVERFAST_MAX_RETRIES`,
  `RANK_FETCH_WORKER_PREFETCH` (kept low to protect the upstream). They belong to the Overwatch
  module's rank collector (`shared/disciplines/overwatch/collector/settings.py`), not to the
  the service's config. The operational collection parameters — interval, scope, per-minute limit,
  backoff base, max consecutive failures — live in `public.settings`, editable at
  runtime, not in the env file.
- **Riot API** — `RIOT_API_KEY` (a development key expires every 24 h), `RIOT_ACCOUNT_CLUSTER`
  (`europe`), `RIOT_TIMEOUT`, `RIOT_MAX_RETRIES`, `LOL_RANK_FETCH_WORKER_PREFETCH`. They belong to the
  LoL module's collector (`shared/disciplines/lol/riot.py`); its runtime parameters live in
  `public.settings` under `lol.rank_collection`.
- **deadlock-api** — `DEADLOCK_API_KEY` (optional; unset means the public per-IP limits). It belongs
  to the Deadlock module (`shared/disciplines/deadlock/client.py`); the collector's runtime
  parameters live in `public.settings` under `deadlock.rank_collection`.
- **Outbound proxy** — `PROXY_TYPE`, `PROXY_IP`, `PROXY_PORT`, `PROXY_USERNAME`, `PROXY_PASSWORD`.
- **Subscription verification** — `TWITCH_CLIENT_ID`. Unset means every live Twitch check resolves
  `unknown` and fails open: the sweep runs and proves nothing.
- **Transport and infrastructure** — `RABBITMQ_URL`, `RPC_PREFETCH_COUNT`, `REDIS_URL`,
  `RABBITMQ_MANAGEMENT_URL` / `_USER` / `_PASSWORD` (queue-depth reads for the admin monitor).
- **Observability** — `WORKER_METRICS_PORT`, `LOG_LEVEL`, `JSON_LOGGING`, `SENTRY_DSN`,
  `TRACING_ENABLED`, `OTLP_ENDPOINT`, `OTEL_TRACES_SAMPLER*`.

## Running

Locally, from `backend/stats-service/`:

```
uv run faststream run serve_rpc:app      # RPC handlers only
uv run faststream run serve_worker:app   # consumers and schedules only
```

The MVP-impact backfill is a separate CLI (idempotent, safe to rerun):

```
uv run python backfill_impact.py [--tournament-id N]
```

The backfill enumerates Overwatch matches through game → encounter ownership, replaces only the
seven derived non-character fact codes across all segments, and preserves character/raw facts.
Fight metadata is reassigned as complete JSON values. Each match has its own flush/evidence/commit
boundary. Objectiveless resolution adjusts native score facts, not accepted live-game results.

In compose, `stats-svc` and `stats-worker` are built from `backend/` with `APP_PATH=stats` (image
`owt-stats`) and depend on healthy `redis`, `rabbitmq` and `proxy`. Dev runs
`faststream run serve_rpc:app --reload` / `serve_worker:app --reload` with the service and `shared/`
bind-mounted and polling watchers (`WATCHFILES_FORCE_POLLING`); production runs the plain commands with
`restart: always`. Both declare a healthcheck on `GET :9100/health` (broker connection and consumers),
so an orchestrator restarts a process that is up but not consuming. Run one `stats-worker` per
deployment slice: its schedules are Redis leader-locked, so extra replicas are safe but idle.

## Operational notes

- **Shutdown order.** Stop schedulers in `on_shutdown`, but close HTTP, S3 and Redis clients in
  `after_shutdown`. FastStream drains consumers between those hooks; closing clients before
  that drain makes active rank-fetch jobs fail with `Client not started` and sends them to the DLQ.
- **Channel isolation is load-bearing.** RPC, background jobs, match-log parsing and rank fetching
  each get their own channel/prefetch. Collapsing them means one long parse can close the channel
  every other consumer shares.
- **DLQs.** The worker declares `upload_match_log.dlq`, `stats.ingest.<discipline>.dlq` and
  `stats.ingest.<discipline>.replay.dlq` (selected disciplines), `process_tournament_logs.dlq`, `achievement_evaluate.dlq`,
  `achievement_evaluate.deferred.dlq`, `tournament_encounter_completed.dlq`, `discord_member_changed.dlq` and
  `cache_invalidation_stats_service.dlq`; the Overwatch module
  declares its own (`rank_fetch.dlq`, `rank_fetch_priority.dlq`, `tournament_registration_approved.dlq`,
  `tournament_registration_rank_check.dlq`) from its `start_jobs` hook, and so does the LoL module
  (`lol_rank_fetch.dlq`, `lol_rank_fetch_priority.dlq`, `lol_rank_registration_approved.dlq`,
  `lol_rank_registration_rank_check.dlq`). An achievement
  evaluation that raises is rejected without requeue straight into its DLQ. An invalidation lost to
  `cache_invalidation_stats_service.dlq` is only repaired by the next event or by the cache TTL.
- **A stuck "Queued" record is a reaper question, not a queue question.** The row, not the message,
  is the source of truth; check `attempts` and the reaper settings before republishing by hand.
- **Rank fetches are scheduler-retried, not broker-retried.** A transient OverFast failure is
  recorded with backoff and swallowed, so the message is not redelivered; the next tick picks the
  tag up when `next_eligible_at` says so.
- **Baseline cache.** Impact baselines are cashews-cached for 10 minutes under
  `backend:parser:impact_baselines:{discipline}:{FORMULA_VERSION}` (the key keeps its historical prefix). Every reader, including the
  backfill CLI, must call `configure_cache()` before cache operations.
- **Baseline input order.** The loader orders rows by `(match_id ASC, global user_id ASC)`
  before the unchanged pandas reductions. Stable identity ordering prevents query-planner row
  order from changing floating-point accumulation; formulas, rank handling and cache policy are unchanged.
- **Replicas are safe.** All three schedulers are leader-locked in Redis, and rank enqueue plus
  match-log parsing are deduped (Redis keys and content hash respectively), so scaling the worker
  horizontally does not duplicate work.
- **Cache invalidation is broad on purpose.** A `cache.invalidated` event carries no user list, so every
  `/users/*` and rarity key misses after any tournament write. Expect a cold-cache burst of heavy
  aggregation queries on stats-svc right after tournament ingestion.
- **`ortools` is declared in `pyproject.toml` but never imported** — there is no OR-Tools
  optimisation in this service.

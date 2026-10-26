# App Service (`app-svc`)

App-service administers everything that is neither a tournament nor a statistic: the game catalog,
player identities, workspaces (the tenant), notifications, platform audit and binary assets. The
public statistics, `/users/*` player-statistics and achievement reads, with their read caches and
invalidation consumer, belong to [stats-service](../stats-service/README.md) since 2026-10-23
([release note](../../docs/releases/2026-10-23-stats-owns-statistics-reads.md)); app-service keeps
the player directory, search and name lookup. The organizer dashboard and tournament readiness belong
to [tournament-service](../tournament-service/README.md) since the same day
([release note](../../docs/releases/2026-10-23-tournament-owns-organizer-dashboard.md)).

It is a headless FastStream worker. It opens no HTTP port and serves no routes. The Go gateway is the
only process speaking HTTP; it maps REST routes under `/api/v1/*` onto request/reply RPC on
`rpc.app.*` with an `x-deadline-ms` budget, and this worker answers with an `{ok, data, error}`
envelope (`src/rpc/_common.py` → `shared.rpc.common`).

- **Compose service:** `app-svc`
- **Entry point:** `serve.py`
- **Run command:** `faststream run serve:app`
- **Transport:** RabbitMQ request/reply (`rpc.app.<method>`); no HTTP
- **Metrics:** Prometheus on `WORKER_METRICS_PORT` (dev 9109, prod 9109)

See [`../../docs/architecture.md`](../../docs/architecture.md) for the system overview and
[`../ARCHITECTURE.md`](../ARCHITECTURE.md) for the `rpc → services → domain → repository → models`
layering every backend service follows.

## Responsibilities

- **Game catalog** — native per-discipline character/map/mode reads over `catalog.entity`, discipline
  descriptors and metadata, generic discipline-and-kind admin CRUD, and the alias-miss worklist that
  closes the loop when the parser meets a name it cannot resolve.
- **Player identity** — the domain player, social accounts and their visibility, favourites, the
  destructive profile merge that collapses two players into one, and the public player directory,
  search and name lookup (`rpc.app.users.{list,search,by_name}`). Profile and identity edits made
  here bump the `shared.services.user_cache` generations that stats-service's `/users/*` and
  achievement read caches are keyed by, so those caches miss as soon as the edit commits.
- **Tenancy** — workspaces, membership and roles, custom domains, and Discord guild claim. Granting
  the workspace `owner` role, or taking it from a member (role update or removal), takes `owner` in
  that workspace or a superuser on top of the `workspace_member.*` permission; otherwise 403 "Only a
  workspace owner can grant or revoke the owner role". Ownership transfer keeps its own rule.
- **Notifications** — the inbox and announcements, the operator view of a workspace's
  notifications, and Discord delivery of notification rows off the `notification_delivery` queue.
- **Audit** — the read-only platform audit feed and per-entity trail.
- **Binary assets** — workspace icons, platform assets and match-log download, exchanged as base64
  inside the RPC envelope and stored in S3.

## Interface

The worker subscribes to literal subjects in the `rpc.app.*` namespace under `src/rpc/`,
including one catalog-admin handler per verb rather than per discipline or kind. The full method
list with request/response schemas is published at `/api/docs`, generated from
`src/openapi_schemas.py` (`OPERATIONS`) and `src/openapi_docs.py` (`DOCS`).

### Method groups

| Group | Subject shape | What it covers | Module |
| --- | --- | --- | --- |
| Catalog reads | `rpc.app.catalog.{list,get}`, `rpc.app.disciplines.{list,metadata}` | Native `/api/v1/catalog/{discipline}/{kind}[/{id}]` reads over `catalog.entity`, installed disciplines and their metadata | `catalog`, `disciplines` |
| Users | `rpc.app.users.{list,search,by_name}` | The player directory (`/api/v1/users`), name search (`/api/v1/users/search`) and the bare-name lookup (`/api/v1/users/{name}`). The overview grid and every `/users/{id}/…` statistics read are stats-service's (`rpc.stats.users.*`) | `users` |
| Workspaces | `rpc.app.workspaces.*`, `rpc.app.admin.{update,delete}` | Workspace read plus self-service create (any active user, capped at one owned workspace, reserved slugs rejected), member roster and roles, custom domain lifecycle, Discord guild claim, and the superuser-only `verification_set` trust tier; update/delete via the shared engine | `workspaces`, `admin_crud` |
| Binary assets | `rpc.app.{workspaces.icon_*,assets.*,matches.log}` | Workspace icon and platform-asset upload/delete to S3, match-log download; base64 in the envelope | `binary` |
| User & identity admin | `rpc.app.users.{admin_*,merge_*,social_*,avatar_*,me_*}` | Player CRUD, destructive profile merge, social-account management and visibility, avatar, and the `account.social` self-service subset | `users_admin` |
| Catalog admin | `rpc.app.catalog.admin_*` | Superuser CRUD on `/api/v1/admin/catalog/{discipline}/{kind}[/{id}]`; one handler per verb, discipline and kind from the path | `metadata_admin` |
| Catalog aliases | `rpc.app.catalog_aliases.*` | `catalog.alias_miss` worklist scoped by discipline and kind (`character\|map\|mode` entity names; `stat\|event\|role` codes are dismiss-only): list, attach `{entity_id, alias}`, dismiss | `catalog_aliases` |
| Audit | `rpc.app.audit_list` | Read-only platform audit feed and per-entity trail, gated on `audit.read` | `audit` |

### The shared CRUD engine, and why some subjects carry `#<entity>`

Workspace `update`/`delete` is not a handler pair of its own. It is one pair —
`rpc.app.admin.update` / `rpc.app.admin.delete` — dispatched by an `entity` field the gateway puts in
the request body, against the `EntityConfig` table in `src/services/workspace/registry.py`
(`CrudDispatcher`). Everything else is a bespoke subject with its own handler.

Because one subject can serve many entities, a subject alone cannot key the OpenAPI tables: they use
`"<subject>#<entity>"` instead — `rpc.app.admin.update#workspace`. The convention is defined in
`shared/rpc/openapi.py` and must match the gateway's lookup. A `#` in an `OPERATIONS`/`DOCS` key
therefore means "generic engine, this entity"; a bare subject means a bespoke handler.

The public catalog is native: `GET /api/v1/catalog/{discipline}/{kind}[/{id}]` (kinds `character`,
`map`, `mode`) returns `CatalogEntityRead` rows of that one discipline, active rows by default; a kind
the game does not declare is `404 catalog_kind_not_declared`. The old `/api/v1/{heroes,maps,gamemodes}`
list/detail/lookup routes and the `/api/v1/heroes/…` statistics routes are gone; character statistics
live under `/api/v1/statistics/{discipline}/characters/…` and `/api/v1/users/{id}/characters`, both
served by stats-service. All ids are `catalog.entity` ids.

Catalog admin uses `CatalogEntityCreate`, `CatalogEntityUpdate` and `CatalogEntityRead` rather
than those Overwatch-shaped models. PATCH shallow-merges `attrs` (present keys replace, absent
keys keep); a name-only edit keeps the stored slug. Explicit null for `name`, `slug`, `attrs` or
`active` is rejected with 422, and the effective slug must fit 64 characters without truncation.
Parent and character-class validation comes from the discipline module. The existing Overwatch
admin pages adapt to this generic wire; discipline-driven public and admin pages are a later phase.

### Role ontology and workspace formats

At startup the app projects module-declared dimensions and roles into `catalog.role_dimension` /
`catalog.role`; exactly one dimension per discipline is rated. Removed module roles are deactivated,
not deleted. `CatalogRoleRepository` resolves module roles and the owner's workspace sub-roles;
their codes are `<parent>_<slug>` (for example `support_main`), with immutable parents.

Workspace reads expose `disciplines_enabled` (priority order, `[0]` is the default game), writable by
anyone with `workspace.update` on that workspace; disabling a game only refuses new tournaments and mixes in it. Workspace default
formats are read/written through
`GET|PUT /api/v1/workspaces/{workspace_id}/team-formats/{discipline}` using
`TeamFormatRead` / `TeamFormatWrite`; `default_roster_slots_json` is no longer on the wire.
Tournaments own editable copies; mixes freeze copies at creation, so editing a template does not
rewrite existing events.

User/player role fields use leaf `RoleRef {dimension, role, parent}` values; inputs ignore `parent`.
See the [P2 release guide](../../docs/multi-game-p2-roles-release.md) for all wire breaks.

### Consumed queue

`notification_delivery`, bound to the `notifications` exchange (`notification.*`) on its own AMQP
channel (`prefetch_count=4`), with its `.dlq` declared at startup: Discord delivery of the rows
`notify()` writes and the posts `broadcast()` queues (`src/services/notification_delivery/consumer.py`).

App-service consumes no `cache.invalidated` queue: the public read caches are stats-service's
(`cache_invalidation_stats_service`). The gateway's own anonymous response cache is invalidated
separately, off the realtime invalidation topics the writer publishes after its commit
(`gateway/internal/respcache`).

### Published events

`WorkspaceMemberChangedEvent`, through the transactional outbox straight onto the
`workspace_member_changed` queue (default exchange): staged by every `WorkspaceService` operation
that changes who holds a workspace role (create, member add/update/remove, owner transfer,
workspace delete — every member and role holder, staged before the delete), by the admin player
delete (the linked account) and by the profile merge, in the write's own transaction. The shared
writers stage it too (`shared.rbac.bootstrap.stage_rbac_change`): member admission, role grants,
the bulk role autofill and system-role permission reconciliation. identity-service consumes it and
drops the cached RBAC payload of the listed users. The `WorkspaceService` operations also send the
same event to identity as the RPC `rpc.identity.workspace_member_changed` right after committing
and wait for it (identity then has the gateway evict those users' cached principals), so the
creator's first settings save or a removed member's next call already sees the change; a failed
call only loses that head start. App-service publishes no Redis realtime topics.

### Scheduled work

An `event_outbox_drain` tick every second (`shared.messaging.outbox.drain_outbox`), relaying the
outbox rows this service writes (notifications, Discord messages, workspace membership changes).
The `stats.mv_entity_global_stats` refresh runs in stats-worker.

### Outbound RPC

`rpc.identity.oauth_discord_guilds` (identity-service), to confirm the caller administers the Discord
guild they are claiming for a workspace. `discord_guild_channels` (discord-service, via the RPC-only
`shared.services.discord_client.DiscordClient`), to check a workspace's notification channel belongs
to its own guild.

## Data owned

There are no per-service migrations. All models live in one SQLAlchemy metadata under
[`../shared/`](../shared/README.md) and all migrations in one Alembic project at
[`../migrations/`](../migrations). Per-domain entity diagrams are in
[`../../docs/database_erd.md`](../../docs/database_erd.md).

**Writes:**

- `players` — `user`, `social_account`, `social_account_visibility`, `favorite_player`,
  `user_merge_audit` ([identity](../../docs/database_erd.md#identity--auth-players)).
- `public` — `workspace`, `workspace_member`, `audit_log`
  ([tenancy](../../docs/database_erd.md#tenancy--public),
  [platform](../../docs/database_erd.md#platform--public-realtime)).
- `catalog` — `entity`, `alias_miss`, plus the startup `role_dimension` / module `role` projection
  ([catalog](../../docs/database_erd.md#catalog--catalog)).
- `roster` — workspace defaults in `team_format`, `team_format_dimension`, `format_role_rule`
  ([roster](../../docs/database_erd.md#roster--roster)).
- `achievements` — `override` and `evaluation_result`, only to repoint `workspace_member_id` during a
  merge ([achievements](../../docs/database_erd.md#achievements--achievements)).

Profile merge also repoints `tournament.team.captain_id` and `stats.ingest_job.uploader_user_id`.
Member-anchored tournament, registration and achievement references follow their resolved member.
Native `stats.match_player`, `stats.fact` and both actor/target identities in `stats.event` move via
`StatsMatchRepository.merge_member_history`, within one workspace. Any same-match overlap is a
409 `stats_member_history_conflict`, never a sum or deduplication. With no target membership, the
source membership id is retained and its player identity changes; no member is fabricated.
The original `UserMergeAudit` preview JSON retains complete global/member mappings and stable
native statistics audit ids.

User/workspace deletion captures native evidence, flushes the deletion and stages its audit in
the same transaction. Played-member deletion remains refused. Match-log downloads resolve
`StatsMatch` → `IngestJob.raw_ref` and game → encounter tournament, authorize visibility before
fetching that actual S3 key, and use the filename only for display.

**Other reads:** `tournament`, native `stats`, `balancer`, `registration`, `mix`, `draft`, and `auth` (for the acting
identity and its roles). No runtime access to legacy `matches`, `log_processing` or `overwatch` tables remains.

## Dependencies

- **PostgreSQL** — the shared database; every read and write above.
- **Redis** — two logical databases via cashews: `/3` behind the `fastapi:` key prefix and `/4`
  behind `backend:` (the notification workspace-id lookup), plus the realtime Redis holding the
  cache generations `shared.services.user_cache` bumps. Both prefixes must be registered before any
  subscriber runs; cashews has no default backend and raises `NotConfiguredError` for an unroutable
  key (`src/core/caching.py`).
- **RabbitMQ** — RPC transport and the `notification_delivery` consumer.
- **S3 / MinIO** — workspace icons, platform assets, match-log objects.
- **identity-service** — over RPC, for Discord guild verification.
- **discord-service** — over RPC, for the notification-channel check.

No outbound calls to third-party APIs, so no `proxy` egress. (The compose block still declares
`depends_on: proxy` — startup ordering only.)

## Configuration

`backend/env/common.env` then `backend/env/app.env`, in that order. Settings are typed in
`src/core/config.py` on top of `shared.core.config.BaseServiceSettings`.

Behaviour-changing settings:

- `RABBITMQ_URL` — required, no default. `RPC_PREFETCH_COUNT` (default 16) caps how many gateway RPC
  handlers run at once in the process (a permit pool, `shared.rpc.deadline.configure_rpc_concurrency`);
  it is also each RPC consumer's AMQP prefetch, which RabbitMQ applies per consumer, not per channel.
- `REDIS_URL` — the base URL; the service derives `/3` and `/4` from it.
- `POSTGRES_*` and the `DB_POOL_*` knobs. Set `DB_PGBOUNCER=true` **before** scaling replicas — each
  process opens up to `DB_POOL_SIZE + DB_MAX_OVERFLOW` server connections.
- `S3_ACCESS_KEY` / `S3_SECRET_KEY` / `S3_ENDPOINT_URL` / `S3_BUCKET_NAME` / `S3_PUBLIC_URL`.
- The public read-cache TTLs (`users_cache_ttl`, `user_profile_cache_ttl`, `achievements_cache_ttl`)
  are stats-service settings.
- `WORKER_METRICS_PORT`, `TRACING_ENABLED`, `OTLP_ENDPOINT`, `OTEL_TRACES_SAMPLER*`, `SENTRY_*`,
  `LOG_LEVEL`, `JSON_LOGGING`.

## Running

Locally, from `backend/app-service/` with the shared env loaded:

```bash
faststream run serve:app
```

In compose (`app-svc` in both files, default profile — always started):

- Dev mounts `backend/app-service` and `backend/shared` and runs with `--reload --reload-dir` for
  both, with `WATCHFILES_FORCE_POLLING=true`. No healthcheck.
- Production runs the bare command, sets a CPU ceiling of 2.00 and `restart: always`, and declares a
  healthcheck of `python -c "import sys; sys.exit(0)"`.
- Both wait on `redis`, `rabbitmq` and `proxy` being healthy.

Layering check — `services.user` and `services.workspace` stay independent of each other, and the
transport never reaches `user.queries`; both are enforced by `.importlinter`. From `backend/`:

```bash
uv run lint-imports --config app-service/.importlinter
```

The contracts are explained in
[`../docs/architecture/layering.md`](../docs/architecture/layering.md).

## Operational notes

- **Startup cache purge.** `serve.py` FLUSHDBs Redis `/3` and `/4` on boot, so a redeploy never
  serves entries produced by the previous image's serializers. `/4` is also stats-service's
  read-cache database: an app-svc restart cold-starts those caches too.
- **Replicas.** Safe: RPC and `notification_delivery` are competing consumers, and the outbox drain
  takes its batch `FOR UPDATE SKIP LOCKED`.
- **The production healthcheck proves only that Python starts.** It does not test the broker
  connection, the database, or subscriber registration; a worker with a dead broker still reports
  healthy.

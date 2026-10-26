# Identity Service (identity-svc)

Authentication and authorization for OWT. It exists as its own process because every
authenticated request in the platform passes through it: the gateway calls `validate_token` on
the hot path, so identity is sized, cached and deployed independently of the domain services.
It is a **headless FastStream (RabbitMQ) RPC worker** — there is no HTTP server and no listening
API port. All requests arrive as typed request/reply RPC (`rpc.identity.*`) published by the
[Go gateway](../../docs/architecture.md), which terminates HTTP and exposes this worker's
surface under `/api/auth`.

- **Compose service:** `identity-svc` (dev: every RPC; production: `IDENTITY_RPC_ROLE=core`) and,
  in production only, `identity-auth-svc` (same image, `IDENTITY_RPC_ROLE=credentials`) — see
  [Process split](#process-split)
- **Entry point:** `serve.py` (headless FastStream RPC worker)
- **Run command:** `faststream run serve:app`
- **Transport:** RabbitMQ request/reply (`rpc.identity.<method>`); no HTTP
- **Metrics:** Prometheus on `WORKER_METRICS_PORT` (dev 9100 — the compose block sets no
  override, so it inherits `common.env`; prod 9107, `identity-auth-svc` 9112)

See [`../../docs/architecture.md`](../../docs/architecture.md) for the system overview and
request flow, [`../ARCHITECTURE.md`](../ARCHITECTURE.md) for the `rpc → services → domain →
repository → models` layering, and [`../shared/README.md`](../shared/README.md) for the
ORM/kernel this service builds on.

## Responsibilities

- **JWT auth** — issues and validates access + refresh tokens. Access and service tokens are
  Ed25519 (EdDSA) JWTs signed with a key derived from `JWT_SECRET_KEY` (HKDF info
  `anak-identity:jwt-signing:v1`); the gateway verifies them locally with the public half
  (`JWT_PUBLIC_KEY`, printed by `make jwt-public-key` and logged here at startup) and cannot mint
  any. An access token carries `sub`, `sid`, `type="access"`, `iat`, `exp`, `iss="owt-identity"`,
  `aud="owt"` and a random `jti` — no profile or RBAC. Tokens of the previous HS256 release still
  verify for one access-token lifetime after the process starts, then only EdDSA does.
  `validate_token` is the gateway's authority for RBAC-gated routes and rehydrates the
  `AuthUser`, permission set and workspace memberships from the request.
- **Sessions** — list, revoke a single session, logout, and logout-all (revoke every session
  for the user). Refresh tokens are persisted in Postgres and revocable; revoking a session
  also blacklists its `sid` in Redis for the remaining access-token lifetime. Session lists
  collapse rotation rows to one per session, order and page in SQL.
- **Account security** — deleting the account or setting the first password re-authenticates:
  the current password for a password account, else a session that signed in within the last
  10 minutes (403 `reauth_required` otherwise; `get_me` reports `has_password`). Setting or
  changing a password signs out every other session.
- **OAuth** — Discord, Twitch, Battle.net, Riot (Riot Sign-On) and Steam (OpenID 2.0; a provider
  is advertised only when its enable flag is on and every credential it needs is present; Steam
  needs none besides `OAUTH_REDIRECT`): authorization URL, callback exchange, account
  link/unlink, and listing connected providers. A Riot sign-in stores the PUUID as the verified
  `riot` social account's `provider_user_id` and the Riot ID as its handle. Steam returns no
  `code`: the callback page forwards its `openid.*` parameters as the code, which is checked
  (claimed id, signed fields, `op_endpoint`, a `return_to` equal to the callback URL carrying this
  flow's own `state`, a signed `response_nonce` at most 5 minutes old) and verified with Steam's
  `check_authentication`; the verified `steam` social account's subject and handle are both the
  decimal SteamID3 account id, the persona name and avatar (from deadlock-api, best effort) only
  display. State is signed and its nonce single-use; with Redis down the callback answers 503
  `unavailable` rather than skip that check. Discord flows add PKCE (S256), its verifier derived
  from the state nonce (`oauth_pkce_key`), never stored. Only Discord and Twitch tokens are kept,
  sealed with AES-256-GCM under `OAUTH_TOKEN_ENCRYPTION_KEY` (`shared.core.secretbox`; identity
  refuses to start without it while either is enabled, and a startup job seals rows still in
  clear and drops every other provider's token). Unlinking the last sign-in method locks the
  account row first, so concurrent unlinks cannot both pass the guard. The OAuth handoff to custom
  domains is completed via single-use, browser-bound Redis tickets.
- **SSO exchange** — redeems a one-time SSO ticket so a custom-domain OAuth callback can hand
  the session back to the tenant origin without exposing tokens in the redirect.
- **RBAC** — permissions, roles, role↔permission grants, user↔role assignments, and a
  workspace-scoped `user_permission_deny` overlay (grant-only catalog + deny overrides),
  administered through the `rpc.identity.rbac.*` method group.
- **Workspace membership authz** — resolves and authorizes a user's membership within a
  workspace (tenant), feeding the gateway's ACL decisions.
- **Multitenancy** — custom-domain / subdomain tenancy: signed OAuth `state`, single-use Redis
  SSO and link tickets, and tenant-aware callbacks so white-label hosts share one identity
  backend.
- **API keys** — create, list, update, and revoke per-user, workspace-scoped API keys;
  `validate_token` accepts an API key in place of a bearer access token.
- **Player linking** — attach in-game player profiles to an auth user, unlink, list linked
  players, and set the primary player. A self-service link needs a connected identity whose unique
  handle matches the player's: Discord `username`, BattleTag, Riot ID or Steam account id (display
  names and emails prove nothing). Every link/unlink drops the account's RBAC cache.
- **Avatar** — set/delete the current user's avatar, stored in S3.
- **Service tokens** — client-credentials tokens (`service_token` / `validate_service_token`)
  used by other services (e.g. the Discord bot) to call the platform machine-to-machine.

## Interface

The worker subscribes to a single namespace, `rpc.identity.*`; the gateway publishes a request
per subject and the worker replies with an `{ ok, data, error }` envelope. Requests carry the
gateway's `x-deadline-ms` budget — a request whose deadline has already passed when it reaches
the consumer is acked and dropped without executing. Authenticated methods carry the caller's
bearer `access_token` (injected by the gateway) and resolve the active user before executing.

| Method group | Subjects | What it covers |
|---|---|---|
| Token / service validation | `rpc.identity.validate_token`, `…service_token`, `…validate_service_token`, `…invalidate_session` | Bearer/API-key validation for the gateway, client-credentials tokens, and dropping a user's cached RBAC |
| Auth core & sessions | `rpc.identity.<register\|login\|refresh\|logout…>` | Registration, login, refresh rotation, logout/logout-all, session list and revoke |
| Current user | `rpc.identity.<get_me\|update_me\|…>`, `rpc.identity.me.*` | Profile read/update, self-delete, password set, avatar set/delete |
| OAuth & cross-domain handoff | `rpc.identity.oauth_*`, `rpc.identity.sso_exchange`, `rpc.identity.link_complete` | Provider list, authorization URL, callback, link/unlink, connections, Discord guilds, ticket redemption |
| RBAC admin | `rpc.identity.rbac.*` | Permissions, roles, assignments, deny overlay, auth-user administration, admin views of sessions and OAuth connections |
| Player linking | `rpc.identity.player.*` | Link, unlink, list linked players, set primary |
| API keys | `rpc.identity.<list\|create\|update\|revoke>_api_key`, `rpc.identity.api_key.self` | Per-key lifecycle and self-introspection |

The full method list with request/response schemas is published at `/api/docs`, generated from
`src/openapi_schemas.py` (`OPERATIONS`) and `src/openapi_docs.py` (`DOCS`).

Besides its own RPC queues it consumes two event queues:

- `workspace_member_changed` (`src/rpc/workspace_member_events.py`, DLQ `workspace_member_changed.dlq`):
  `WorkspaceMemberChangedEvent`, on which it drops the cached RBAC payload of every listed user. It is staged
  through the transactional outbox by every writer of memberships and workspace role grants outside this
  service: app-service's workspace operations (member add/update/remove, owner transfer, create, delete), player
  delete and profile merge, and the shared writers any service runs (`shared.rbac.bootstrap.stage_rbac_change`:
  member admission from registration, balancer admissions and stats achievements, role grants, the bulk role
  autofill, system-role permission reconciliation). That is what lets the RBAC cache live 600 s. app-service also
  sends the same event as the internal RPC `rpc.identity.workspace_member_changed` (no gateway route) right after
  committing and waits for it, so the actor's very next request already sees the change; the queued copy is the
  durable fallback.
- `steam_account_changed` (`src/rpc/steam_names.py`, DLQ `steam_account_changed.dlq`): `SteamAccountChangedEvent`,
  staged by `shared.services.social_identity` when any service creates a Steam `players.social_account` or changes its
  account id. It writes the account's persona name into `display_name` (`src/services/steam_profiles.py`). The same
  refresh runs over every Steam account at startup and then daily (`serve.py`, `steam_display_names`).

It publishes no domain events. The one outbox row it can write is that same `SteamAccountChangedEvent`, when an OAuth
sign-in creates a Steam account without a persona name; the other services' drains relay it. Its one Redis realtime
topic is
`user:{id}:rbac` (`rbac.changed`, ephemeral): every RBAC-cache drop — membership events, role,
permission and deny edits, account deletion, profile merge, `invalidate_session` — announces it
after the entry is gone, and the gateway evicts every token and workspace membership it cached
for that user and re-checks that user's live WebSocket subscriptions (`gateway/internal/principal`,
`gateway/internal/ws` `TopicRevoker`).

## Data owned

Writes the `auth` schema: `user`, `refresh_token`, `oauth_connections`, `api_key`,
`api_key_scope`, `permissions`, `roles`, `role_permissions`, `user_roles`, and
`user_permission_deny`. Two writers outside this service touch it on purpose: workspace role
grants (`user_roles`) come from every service that admits a member, through
`shared/rbac/bootstrap.py`, and the app-service profile merge moves and deletes account rows
through `shared/repository/auth_merge.py` before calling `rpc.identity.rbac.finalize_profile_merge`.

Also writes parts of `players`, always through their writer modules
(`backend/ARCHITECTURE.md`, "Cross-service data access"): a `players.user` row is provisioned at
sign-up (`UserRepository.ensure_for_auth_user`) and linked/unlinked with
`UserRepository.link_auth_user`; `players.user.avatar_url` is the account's avatar (self-service
upload, and the provider avatar fills it on OAuth sign-in while it is empty or still the provider's
previous one); `players.social_account` when an OAuth identity is claimed or released, and its
`display_name` (Steam persona names). Appends to `public.audit_log` for administrative mutations.

Reads `public.workspace` and `public.workspace_member` for tenancy and membership resolution.

Tables live in the shared ORM models and are created by the **central Alembic migrations** at
`backend/migrations/` — this service ships no migrations of its own. See
[`../../docs/database_erd.md`](../../docs/database_erd.md#identity--auth-players) for the entity
diagram.

## Dependencies

- **PostgreSQL** — the single shared database, via the one SQLAlchemy metadata in
  [`../shared/README.md`](../shared/README.md).
- **Redis** — RBAC cache, revoked-session blacklist, refresh idempotency, and the single-use
  SSO / pending-link tickets.
- **RabbitMQ** — the RPC transport (`rpc.identity.*`) and the shared broker topology.
- **S3** — avatar object storage.
- **External APIs** — Discord, Twitch, Battle.net and Riot (`auth.riotgames.com`, account-v1 on
  `https://{RIOT_ACCOUNT_CLUSTER}.api.riotgames.com`) OAuth token/userinfo endpoints, Steam OpenID
  (`steamcommunity.com/openid/login`) and Steam profiles: the Steam Web API
  (`api.steampowered.com/ISteamUser/GetPlayerSummaries/v2`) when `STEAM_WEB_API_KEY` is set, else
  deadlock-api (`api.deadlock-api.com/v1/players/steam`), reached
  through the outbound `proxy` container when the shared `PROXY_TYPE` / `PROXY_*` settings are
  configured; the production compose block `depends_on` it.

## Configuration

Environment-driven, layered from three files under `backend/env/`: `common.env` (`POSTGRES_*`,
`REDIS_URL`, `RABBITMQ_URL`, `WORKER_METRICS_PORT`, `RPC_PREFETCH_COUNT`), `auth.env`
(`JWT_SECRET_KEY`, access/refresh lifetimes, `SERVICE_CLIENTS` / `SERVICE_SCOPES`, the OAuth
client credentials and `OAUTH_REDIRECT`), and `identity.env` — see
[`../env/identity.env.example`](../env/identity.env.example), which carries only the
service-specific overrides:

- `WORKER_METRICS_PORT` — unset disables the metrics server entirely.
- `IDENTITY_RPC_ROLE` (`all` default | `core` | `credentials`) — which RPC modules the process
  serves; see [Process split](#process-split).
- `REFRESH_ROTATION_GRACE_SECONDS` (default 60) — how long the immediately-previous refresh
  token of a live session may be replayed once more instead of counting as a reuse attack; `0`
  restores hard single-use.

Settings that change behaviour elsewhere: `DISCORD_/TWITCH_/BATTLENET_/RIOT_/STEAM_OAUTH_ENABLED` gate which
providers are advertised; Riot also needs `RIOT_CLIENT_ID` / `RIOT_CLIENT_SECRET` and reads the
Riot ID from account-v1 on `RIOT_ACCOUNT_CLUSTER` (default `europe`); Steam needs no credentials (its
OpenID realm is the scheme and host of `OAUTH_REDIRECT`). `STEAM_WEB_API_KEY` (optional) switches Steam persona names
and avatars from deadlock-api's keyless copy to the Steam Web API. `SERVICE_CLIENTS` defines which
machine callers may mint service tokens; `SERVICE_SCOPES` grants them scopes, of which
`invalidate_session` requires `identity:invalidate` (403 without it). `RPC_PREFETCH_COUNT` bounds
in-flight requests per process.

## Running

```bash
# From backend/, with the workspace virtualenv active
cd backend/identity-service
faststream run serve:app
```

In Docker the service runs headless as the `identity-svc` compose service, in the default
profile (no `--profile` flag needed). Because it has no HTTP server, the image's HTTP
healthcheck does not apply: dev disables the healthcheck outright, production replaces it with
a `python -c "import sys; sys.exit(0)"` liveness probe. The dev command adds `--reload` over the
mounted `identity-service/` and `shared/` sources.

### Process split

`IDENTITY_RPC_ROLE` selects the RPC modules `serve.py` registers:

| Role | Modules | Schedulers and startup jobs |
|---|---|---|
| `credentials` | `auth`, `oauth` (register, login, refresh, sessions, account, OAuth) | no |
| `core` | every other module (`validate_token`, service tokens, API keys, RBAC, players, avatars, event consumers) | yes |
| `all` (default) | both | yes |

Production runs `identity-svc` as `core` and `identity-auth-svc` as `credentials` (same image and
limits), so bcrypt and OAuth provider round trips cannot queue the gateway's `validate_token`
calls; the gateway waits for both. Dev compose runs one `all` process. Startup jobs (the RBAC
cache flush, the refresh-token purge and the Steam display-name refresh) run once per `core`/`all`
process. Every role logs `JWT public key …` at startup — it must equal the gateway's
`JWT_PUBLIC_KEY`.

## Operational notes

- **RBAC cache.** Each user's resolved permissions, denies, workspace memberships and account
  fields (`email`, `username`, `is_active`, `is_superuser`) are cached in Redis under a versioned
  key (`rbac:v4:user:<id>`) with a 600-second TTL, and invalidated explicitly on every RBAC or
  account mutation, account deletion, and via `invalidate_session` from another service; every
  `core`/`all` process also flushes all entries at startup, covering drop events that expired in
  their queue while identity was down. The TTL is the backstop, not the staleness bound. The
  version prefix is what retires entries whose payload shape changed. Every drop also bumps
  `rbac:gen:<id>`; a fill reads that generation before it loads anything -- the account row
  included -- and writes the entry only while it is unchanged (one Lua compare-and-set), so a
  validation that read the database just before a membership or account commit (deactivation,
  deletion, profile edit) cannot put the old entry back after the drop. A build that read no
  generation before its row answers without caching. The cache is
  best-effort: a Redis outage costs extra database work, never a failed request
  (`identity_redis_degraded_total`; hits and misses in `identity_rbac_cache_total`).
- **Redis client.** 0.5 s socket and connect timeouts, a 30 s health check and at most 128
  pooled connections: a stalled Redis costs one timeout and the fallback, never a hung request.
- **Refresh-token rotation.** Rotation is single-use with reuse detection — replaying a
  revoked token revokes the whole session family. Two escape hatches keep honest clients out of
  that path: a 30-second Redis idempotency entry so concurrent refreshes of the same token
  share one result, and `REFRESH_ROTATION_GRACE_SECONDS` (60s) for a rotation whose response
  never reached the client, after which the successor minted by the lost rotation is retired.
  A rotation locks the owning `auth.user` row and consumes its token with
  `UPDATE … WHERE NOT is_revoked`; every revocation takes the same lock first. Only the
  transaction that flipped the token mints a successor; a loser rolls back and waits up to 1 s
  for the winner's idempotency entry, else answers 401 — so a logout racing a refresh never
  leaves a live token behind.
- **Password login.** bcrypt runs in worker threads, at most two at a time per process
  (`identity_password_hash_seconds`). An unknown email or a passwordless account still verifies
  against a dummy cost-12 hash, so timing does not reveal accounts. 10 failed logins for one
  email (counted under `auth:login:fail:<sha256(lower(email))>`, unknown emails included)
  within 15 minutes lock it for 15 minutes: 429 before the password is checked; success
  clears the count. A Redis outage disables the lock (logged, `identity_redis_degraded_total`),
  never sign-in. Outcomes: `identity_login_total`, `identity_refresh_total`.
- **Refresh-token purge.** Daily, tokens expired more than 30 days ago are deleted 5000 rows
  per transaction over the `expires_at` index.
- **Cross-domain tickets.** SSO tickets live 60s, pending-link tickets 120s, both in Redis,
  both single-use via `GETDEL`, and both bound to a hashed host-only guard cookie so a ticket
  can only be redeemed by the browser that started the flow.
- **Session revocation** blacklists the session id for the remaining access-token lifetime, so
  an already-issued access token stops working before its own expiry. Revoking many sessions
  writes them in one pipelined round trip. Every revocation (logout, logout-all, revoke,
  reuse detection, the password-change sign-out) then drops the user's RBAC entry, whose
  `user:{id}:rbac` announcement makes the gateway re-validate and close that user's revoked
  WebSockets.
- **Hot path.** Every authenticated request in the platform ends up here; production reserves
  0.5 CPU and caps at 1.0 for this reason. Under-provisioning it throttles all traffic.
  `validate_token` reads the RBAC entry, its generation and the sid blacklist flag in one `MGET`;
  a full hit answers with no SQL at all (an inactive cached account is a 401). A miss loads the
  account identity-only (never its ORM roles) and fills the entry in three statements:
  memberships, one role query for global + member-workspace RBAC, denies. An API key resolves its
  owner the same way, cache first (the key row no longer joins the owner), and narrows the owner's
  RBAC to its scopes.
- **Backpressure.** `RPC_PREFETCH_COUNT` (default 16) caps concurrent processing per process so
  the backlog stays in the queue, where the gateway's deadline can expire it, rather than in
  the consumer buffer.

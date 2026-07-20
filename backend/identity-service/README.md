# Identity Service (identity-svc)

Authentication and authorization for OWT. A **headless FastStream (RabbitMQ) RPC worker** —
there is no HTTP server and no listening API port.
All requests arrive as typed request/reply RPC (`rpc.identity.*`) published by the
[Go gateway](../../docs/architecture.md), which terminates HTTP and exposes this worker's
surface under `/api/auth`.

- **Compose service:** `identity-svc`
- **Entry point:** `serve.py` (headless FastStream RPC worker)
- **Run command:** `faststream run serve:app`
- **Transport:** RabbitMQ request/reply (`rpc.identity.<method>`); no HTTP, no uvicorn
- **Metrics:** Prometheus on `WORKER_METRICS_PORT` (`9107`) — a scrape endpoint, not an API

See [`../../docs/architecture.md`](../../docs/architecture.md) for the system overview and
request flow, and [`../shared/README.md`](../shared/README.md) for the ORM/kernel this
service builds on.

## Responsibilities

- **JWT auth** — issues and validates access + refresh tokens (python-jose, HS256, shared
  secret). `validate_token` is the gateway's authority for RBAC-gated routes and rehydrates
  the `AuthUser` / permission set from the request.
- **Sessions** — list, revoke a single session, logout, and logout-all (revoke every
  session for the user). Refresh tokens are persisted in Postgres and revocable.
- **Discord OAuth** — authorization URL, callback exchange, account link/unlink, and listing
  connected providers. State is signed and OAuth handoff to custom domains is completed via
  single-use, short-lived Redis SSO / pending-link tickets.
- **SSO exchange** — redeems a one-time SSO ticket so a custom-domain OAuth callback can hand
  the session back to the tenant origin without exposing tokens in the redirect.
- **RBAC** — permissions, roles, role↔permission grants, user↔role assignments, and a
  workspace-scoped `user_permission_deny` overlay (grant-only catalog + deny overrides),
  administered through the `rpc.identity.rbac.*` method group. RBAC results are cached in Redis
  and invalidated on mutation.
- **Workspace membership authz** — resolves and authorizes a user's membership within a
  workspace (tenant), feeding the gateway's ACL decisions.
- **Multitenancy** — custom-domain / subdomain tenancy: signed OAuth `state`, single-use Redis
  SSO and link tickets, and tenant-aware callbacks so white-label hosts share one identity
  backend.
- **API keys** — create, list, update, and revoke per-user API keys; `validate_token` accepts
  an API key in place of a bearer access token.
- **Player linking** — attach in-game player profiles to an auth user, unlink, list linked
  players, and set the primary player (`rpc.identity.player.*`).
- **Avatar** — set/delete the current user's avatar, stored in S3.
- **Service tokens** — client-credentials tokens (`service_token` / `validate_service_token`)
  used by other services (e.g. the Discord bot) to call the platform machine-to-machine.

## RPC surface

The gateway publishes to `rpc.identity.<method>`; the worker replies with an
`{ ok, data, error }` envelope. Authenticated methods carry the caller's bearer
`access_token` (injected by the gateway) and resolve the active user before executing.
Representative method groups:

| Group | Representative methods |
|---|---|
| Token / auth | `validate_token`, `register`, `login`, `refresh`, `logout`, `logout_all` |
| Current user | `get_me`, `update_me`, `set_password`, `me.avatar_set`, `me.avatar_delete` |
| Sessions | `list_sessions`, `revoke_session`, `invalidate_session` |
| OAuth (Discord) | `oauth_providers`, `oauth_url`, `oauth_callback`, `oauth_link`, `oauth_unlink`, `oauth_connections`, `sso_exchange`, `link_complete` |
| RBAC admin | `rbac.list_permissions`, `rbac.create_permission`, `rbac.list_roles`, `rbac.create_role`, `rbac.update_role`, `rbac.assign_role`, `rbac.remove_role`, `rbac.get_user_roles`, `rbac.list_user_denies`, `rbac.add_user_deny`, `rbac.remove_user_deny`, `rbac.list_auth_users`, `rbac.assign_linked_player`, … |
| Player linking | `player.link`, `player.unlink`, `player.linked`, `player.set_primary` |
| API keys | `api_key` group: `list_api_keys`, `create_api_key`, `update_api_key`, `revoke_api_key` |
| Service tokens | `service_token`, `validate_service_token` |

## Dependencies

- **PostgreSQL** — owns the `auth` schema (user, refresh_token, oauth_connections, api_key,
  roles, permissions, user_roles, role_permissions, user_permission_deny) and reads the
  `players` schema for player linking. Shared with the rest of the backend via the
  single SQLAlchemy metadata in [`../shared/README.md`](../shared/README.md).
- **Redis** — session/ticket storage (single-use SSO and pending-link tickets) and the RBAC
  permission cache.
- **S3** — avatar object storage.
- **RabbitMQ** — the RPC transport (`rpc.identity.*`) and the shared broker topology.

Database tables live in the shared ORM models and are created by the **central Alembic
migrations** — this service ships no migrations of its own.

## Configuration & running

Configuration is environment-driven (shared `JWT_SECRET_KEY`, `POSTGRES_*`, `REDIS_URL`,
`RABBITMQ_URL`, S3 credentials, Discord OAuth client, plus `WORKER_METRICS_PORT`); see the
env files under `backend/env/`.

```bash
# From backend/, with the workspace virtualenv active
cd backend/identity-service
faststream run serve:app
```

In Docker the service runs headless as the `identity-svc` compose service. It has no HTTP
server, so compose overrides the image's `/health` HTTPCHECK with a python exit-0 healthcheck.
To reach external APIs (Discord, S3) it `depends_on` the outbound `proxy` service.

## License

This service is part of the OWT project, licensed under the GNU AGPL v3.0 with additional
attribution terms. See the repository-root [LICENSE](../../LICENSE).

# Stream Service (stream-svc)

Live-stream discovery for tournaments: which Twitch channels — the organizer's official
broadcast and the participants' own POV streams — are on air right now. It is a separate
process because that answer comes from polling a third-party API on a clock, over the
outbound proxy, against a rate-limit bucket shared with identity-service's OAuth logins;
folding it into tournament-service would attach a scheduler and an outbound Twitch
dependency to the service that owns the bracket. See
[`../../docs/architecture.md`](../../docs/architecture.md) for how it fits into the wider
platform.

**The service owns no Postgres schema.** Live status is Redis-only, with a TTL;
everything it reads from `tournament.*`, `players.*` and `balancer.*` belongs to other
services and is read-only. The single durable row it ever writes is an audit entry for
the admin re-poll.

It ships as one headless FastStream worker on RabbitMQ — no HTTP server, no `main.py`, no
uvicorn port. External traffic arrives as `/api/streams/*` at the Go gateway, which turns
each route into a request/reply RPC call on `rpc.stream.*` under an `x-deadline-ms` budget
and reads back an `{ok, data, error}` envelope.

- **Compose service:** `stream-svc`
- **Entry point:** `serve.py`
- **Run command:** `faststream run serve:app`
- **Transport:** RabbitMQ request/reply (`rpc.stream.*`); no HTTP
- **Metrics:** Prometheus on `WORKER_METRICS_PORT` (dev 9111, prod 9111)

## Responsibilities

- Authority for **live-stream state of a tournament**: which of its channels are on air,
  with the title, viewer count and thumbnail Twitch reported for each.
- Deciding **which channels are pollable at all**. Official broadcasts come from
  `tournament.tournament_link` rows with `kind='stream'`. Participant channels come from
  exactly two consented sources — a self-declared `balancer.registration.twitch_nick`
  behind the per-tournament `stream_pov` checkbox, and an OAuth-verified
  `players.social_account` that is globally visible. Verified wins a login collision: it
  carries a `provider_user_id`, which survives a channel rename. A player's
  `players.user.stream_visible = false` veto outranks both opt-ins.
- Deciding **which tournaments are polled**: statuses `check_in`, `draft`, `live` and
  `playoffs`. `registration` is excluded (it can run for weeks against an empty hall);
  `completed` and `archived` are never polled.
- Running the **Twitch live-status poll tick** and announcing the result to spectators.

## Interface

One RPC namespace, `rpc.stream.*`, with four subjects:

| Subject | Route | Access |
|---|---|---|
| `rpc.stream.tournament_streams` | `GET /api/streams/tournament/{tournament_id}` | Public; hidden tournaments answer 404 |
| `rpc.stream.repoll` | `POST /api/streams/tournament/{tournament_id}/repoll` | `stream.update` on the owning workspace |
| `rpc.stream.health` | `GET /api/streams/health` | **Global** `stream.read` — the poller is platform-wide, so a workspace-scoped grant is not enough |
| `rpc.stream.ticks` | `GET /api/streams/health/ticks` | **Global** `stream.read`, same as health — the last 200 tick outcomes, newest first |

The full method list with request/response schemas is published at `/api/docs`, generated
from `src/openapi_schemas.py` (`OPERATIONS`) and `src/openapi_docs.py` (`DOCS`).

`repoll` does **not** poll inline — a tick walks every active tournament and talks to
Helix over the proxy, which would blow the gateway's RPC deadline. It clears the poll
cursor so the next scheduler heartbeat is due, which is what its 202 describes.

**Durable queues consumed:** none. The worker subscribes only to its own four RPC
subjects; it consumes no domain events and reads no outbox.

**Domain events published:** none. It writes no outbox row.

**Realtime topics published:** `tournament:{id}:streams`, one thin `stream.updated`
carrying only `tournament_id` and `live_count`. Published **per tournament, never per
channel** — a five-caster event on a page with hundreds of spectators would otherwise
become five herd refetches — and only when the *set* of live channels actually changed;
a viewer count ticking up wakes nobody. **Never published for a hidden tournament**: the
live set is still stored, but the topic has no viewer to authorize against, so announcing
there would disclose that a preview tournament exists. The topic is **non-durable** — no
`realtime.workspace_event` row, therefore no replay on reconnect; a reconnecting client
refetches the RPC, which is the authoritative read and the only place the visibility
rules are applied. Spectator-visible under the same "public unless hidden" gateway ACL
(`allowSpectateTournament`) as the bracket.

**Scheduled work:** one APScheduler job, `stream_poll`, on a fixed 30s heartbeat
(`SCHEDULER_TICK_SECONDS`). The heartbeat decides *inside* the tick whether the
admin-configured `interval_seconds` has elapsed, rather than being registered at that
interval — the interval is runtime-editable, and a scheduler pinned to its start-up value
would make the number the admin sees a lie.

## Data owned

**No Postgres schema, no tables, no migrations of its own.** All schema lives in the one
shared SQLAlchemy metadata under `backend/shared/`, and the single Alembic project at
`backend/migrations/` owns every migration on the platform.

Live state is **Redis-only**, five keys, all TTL'd:

| Key | Contents |
|---|---|
| `stream:live:{tournament_id}` | The current live set, one hash field per channel, replaced wholesale each tick (TTL 3 × `interval_seconds`) |
| `stream:token` | The cached Twitch app access token, shared by every replica |
| `stream:poll:last_run` | The tick's due-date cursor (24h TTL) |
| `stream:poll:last_status` | The last tick's outcome, for `rpc.stream.health` (7d TTL) |
| `stream:poll:history` | The last 200 tick outcomes, newest first, for `rpc.stream.ticks` (7d TTL) |

Postgres access is **read-only** apart from one write: `public.audit_log`, via
`shared.services.audit.record_audit`, journalling the admin re-poll. Read-only tables:
`tournament.tournament`, `tournament.tournament_link`, `tournament.team`,
`tournament.player`, `balancer.registration`, `players.user`, `players.social_account`,
`players.social_account_visibility`, `public.workspace_member`, and `public.settings` for
the `stream.collection` config. The boundary rule — read freely through `shared`, write only
what your service owns — is in [`../shared/README.md`](../shared/README.md);
those tables are documented in
[`../../docs/database_erd.md`](../../docs/database_erd.md) under **tournament**,
**identity**, **registration** and **tenancy**.

## Dependencies

- **PostgreSQL** — read-only, for the tables above. One shared database.
- **Redis** — the four keys above, the scheduler leader lock, and the
  `tournament:{id}:streams` realtime topic the gateway relays to WebSocket clients.
- **RabbitMQ** — `rpc.stream.*` request/reply transport.
- **Twitch Helix** — `GET /streams` under an **app** access token
  (`grant_type=client_credentials`): the poller asks who is live about channels it does
  not own, which needs no user consent. Egress goes through the outbound **`proxy`**
  container (`PROXY_*` in `common.env`). The 800-points/min app bucket is **shared with
  identity-service**, which uses the same Twitch application for OAuth login — hence the
  `Ratelimit-Remaining` floor of 100, below which the tick stops issuing batches and
  reports itself truncated rather than draining the bucket the login flow needs.

## Configuration

`backend/env/stream.env` (template: `stream.env.example`), layered over
`backend/env/common.env` (`POSTGRES_*`, `REDIS_URL`, `RABBITMQ_URL`, `PROXY_*`).
Settings that genuinely change behaviour:

- `TWITCH_CLIENT_ID` / `TWITCH_CLIENT_SECRET` — the app credentials, the same Twitch
  application identity-service uses for OAuth login. Either one unset is a supported
  state: the Helix client raises `HelixNotConfigured`, the tick no-ops, and no tournament
  shows live streams. The worker still starts.
- `WORKER_METRICS_PORT` — Prometheus metrics only, not an HTTP API.

Operational knobs are **not** env vars. `enabled`, `interval_seconds` (30–3600) and
`batch_size` (1–100, Helix's hard per-request cap) live in `public.settings` under the
`stream.collection` key so they can be changed without a redeploy. `enabled` defaults to
`false`, so a fresh deploy never touches Twitch until an operator turns it on — setting
the credentials alone does not start polling.

## Running

```bash
faststream run serve:app
```

Under Compose, dev adds `--reload --reload-dir /app/stream-service --reload-dir /app/shared`;
production runs the bare command with a no-op `python -c "import sys; sys.exit(0)"`
healthcheck, since there is no port to probe. No profile — the service is in the default
set.

## Operational notes

- **Do not scale past one replica for polling's sake.** The tick holds a Redis leader lock
  (`stream_poll:scheduler:leader`, TTL 60s, acquired with a zero timeout) for the whole
  run; a replica that loses the race logs and returns immediately. Extra replicas add
  RPC consumer capacity and nothing else.
- **The tick swallows every Helix failure on purpose** — a Twitch outage must not kill the
  scheduler. That is exactly why `rpc.stream.health` exists: from the outside, a poller
  whose credentials Twitch rejected looks identical to one that simply has nobody live.
  Each failure lands on its own recorded status and metric label: `not_configured`,
  `rate_limited`, `unauthorized`, `unavailable`.
- **Token expiry is self-healing.** The app token is cached in Redis with
  `expires_in − 60s`, so all replicas share one. A 401 drops the cached token, mints a new
  one and retries the batch once; a second 401 is wrong credentials, not a stale token,
  and surfaces as `unauthorized`.
- **Twitch unreachable** (5xx, timeout, transport error) yields `unavailable` and the tick
  writes nothing. That is deliberate: `GET /streams` returns only live channels, so
  absence means offline — writing a partial or empty answer would mark everyone offline
  and flicker every badge on the page. The previous live set stands until its TTL.
- **The poll cursor is set even when the tick fails.** It spaces *attempts*; skipping it
  on failure would turn the 30s heartbeat into a retry storm on the shared bucket.
- **One global Helix batch, deduped across tournaments.** A caster streaming two events in
  one evening is one channel, asked about once.
- `repoll` clears a **global** cursor, so it re-polls every active tournament, not just
  the one named. The rate-limit gate bounds the cost.

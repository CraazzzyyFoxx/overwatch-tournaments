# Discord Service (discord-worker)

The Discord side of the platform: a [discord.py](https://discordpy.readthedocs.io/) bot that watches
tournament channels for match-log attachments, hands them to the parser, and answers guild/member
lookups other services need. It exists as its own process because a Discord gateway session is
stateful and single-tenant — one persistent WebSocket per bot token, carrying the message-content and
members intents — and that connection cannot be shared with or restarted alongside a stateless RPC
worker.

**This is the one backend service that is not a FastStream RPC worker.** It has no `rpc.discord.*`
namespace, the Go gateway never routes an HTTP request to it, and no REST route resolves here. It is
reached in two ways only: by Discord itself over the gateway WebSocket, and by sibling services over
named RabbitMQ queues (`discord_commands`, `discord_member_roles`, `discord_guild_*`, `upload_match_log`,
`match_log.result`). It runs no HTTP server. See
[`../../docs/architecture.md`](../../docs/architecture.md) for how it sits in the wider platform.

- **Compose service:** `discord-worker` — dev profile `workers`, unconditional in production
- **Entry point:** `main.py` (`LogCollectorBot` in `src/bot.py`)
- **Run command:** `python main.py`
- **Transport:** Discord gateway WebSocket inbound; RabbitMQ named queues and one fanout exchange for
  service-to-service traffic; no HTTP, no `rpc.discord.*`
- **Metrics:** Prometheus on `WORKER_METRICS_PORT` (dev 9100, prod 9100)

## Responsibilities

- **Match-log intake from Discord.** Authority for turning a file dropped in a tournament's Discord
  channel into a parse request: which channels are watched, which attachments qualify, and whether a
  given `(tournament, filename)` was already ingested.
- **Upload feedback.** The uploader's verdict — reaction and reply on the originating message —
  including the failed-parse error text read back from `log_processing.record`.
- **Discord directory.** The only process holding a live guild cache, so it answers guild info, guild
  roles, guild channels, and per-member role sets on behalf of every other service.
- **Membership-driven subscription resync.** A member joining, leaving, or having roles changed
  triggers an immediate re-resolve of that user's Boosty subscription instead of waiting for the
  scheduled sweep.

## Interface

No RPC namespace. The gateway's route table contains no entry pointing here, and `/api/docs` does not
describe this service. Everything below is broker or gateway-event traffic.

### RabbitMQ

| Queue / exchange | Direction | Purpose |
| --- | --- | --- |
| `discord_commands` | consumes | `DiscordCommandEvent` — `process_all` (rescan every channel of a tournament), `process_message` (re-ingest one message), `post_message` (send content/embed/PNG to a channel) and `send_dm` (send content/embed to one user). `allow_mentions=false` makes the bot send with `AllowedMentions.none()`, so user-written names never ping; `send_dm` always suppresses mentions. Published by parser-service's `rpc.discord_channel.backfill`, balancer-service's mix posts, and app-service's notification delivery. |
| `discord_member_roles` | consumes, replies | Role ids held by a set of users in a guild. Called by the shared Discord-role subscription strategy (`shared/services/subscriptions/strategies.py`, 5 s timeout). |
| `discord_guild_roles` | consumes, replies | The guild's role list. |
| `discord_guild_channels` | consumes, replies | The guild's text channels. |
| `discord_guild_info` | consumes, replies | Guild name, icon, member count, connectivity. |
| `upload_match_log` | publishes | `UploadMatchLogEvent` carrying the log bytes base64-encoded, consumed by parser-service. |
| `match_log.result` (fanout exchange) | consumes | `MatchLogProcessedEvent`, the parse verdict for one uploaded file. |

The four `discord_*` request/reply queues are durable, dead-letter to `dlx` with a `<name>.dlq`
routing key, and carry a message TTL (60 s for the directory lookups, 5 min for `discord_commands`) —
a lookup no live bot answers expires rather than piling up. Every handler awaits
`bot.wait_until_ready()` first, so a request arriving during startup blocks until the gateway session
is up instead of answering from an empty cache. Directory lookups fall back to a REST call when the
gateway cache has not yet seen the guild.

### Match-log upload and the result rendezvous

`AttachmentProcessor` downloads the attachment through the egress proxy, publishes it to
`upload_match_log` as base64, then blocks on `ResultWaiter.wait(tournament_id, filename)` for up to
120 s. The parser replies by publishing `MatchLogProcessedEvent` to the **fanout** exchange
`match_log.result`; each bot replica binds its **own server-named, exclusive, auto-deleted** queue to
it.

The shape is deliberate. A single durable shared queue would round-robin results across replicas, so a
result would usually land on a replica that holds no pending future for it and the replica that is
actually waiting would time out. Fanout plus a per-replica exclusive queue makes every replica see
every result; the one holding the matching future in `ResultWaiter._pending` resolves it and the rest
no-op. This mirrors the broadcast semantics of the pg `LISTEN`/`NOTIFY` channel it replaces — pgBouncer
transaction pooling silently drops `LISTEN` registrations, so under pooling every upload waited out the
full timeout. The queue is exclusive and auto-deleted so a dead replica leaves nothing behind.

### Discord gateway events

`LogIngestionCog` — `on_ready` (load channels, rescan history, start the reload loop), `on_message`
and `on_message_edit` in monitored channels. `MembershipEventsCog` — `on_guild_join`/`on_guild_remove`
(logging only) and `on_member_join`/`on_member_remove`/`on_member_update` (subscription resync).

### User-facing surface

**No slash commands and no prefix commands are registered.** `LogCollectorBot` subclasses
`commands.Bot` rather than `discord.Client` purely for the cog machinery. The entire user interface is
passive: post a `.txt`, `.log`, or `.json` file in a monitored channel and the bot reacts ✅ / ⚠️ / ❌
and, where the outcome needs words, replies with the parse error. Reactions are reconciled, not just
added, so a re-processed message ends with only the reaction matching its current state.

### Scheduled work

- `channel_monitor` (`discord.ext.tasks.loop`, every 5 minutes) reloads the active
  `channel_id -> tournament_id` map, so adding or removing a tournament channel takes effect without a
  restart. A finished tournament stays watched for 24 hours so a late upload still lands.
- On `on_ready`, the last 500 messages of every monitored channel are rescanned concurrently and any
  unprocessed attachment is uploaded fire-and-forget (no result wait).

### Redis realtime

Indirectly, through the shared subscription resolver: a membership-triggered resync publishes the thin
`subscription.updated` signal on `workspace:{id}:subscriptions`. The bot publishes nothing else to
Redis and consumes no realtime topic.

### Domain events

None. This service does not write to the transactional outbox.

## Data owned

It owns no schema. Everything it touches belongs to another service's domain, and there are no
migrations here — the single Alembic project lives at `backend/migrations/`.

Reads (`log_processing`, see
[`../../docs/database_erd.md`](../../docs/database_erd.md#ingestion--log_processing)):

- `log_processing.discord_channel` — the watched-channel map, written by parser-service's admin
  `rpc.discord_channel.*` methods.
- `log_processing.record` — the already-processed check and the failure text shown to the uploader;
  written by parser-service.

Reads elsewhere: `workspace.discord_guild_id` (guild → workspace ids) and `auth.oauth_connections`
(Discord user id → platform user).

Writes, only through the shared subscription resolver during a membership resync:
`subscriptions.entitlement` (upsert of the verdict) and `subscriptions.check_log` (append-only attempt
log). Same rows tournament-service and parser-service write; this service is an extra writer, not the
owner.

## Dependencies

- **Discord** — gateway WebSocket plus REST, through the `proxy` egress container. The bot token also
  reaches Discord directly from the shared subscription resolver during a resync.
- **RabbitMQ** — every inbound request and the log-upload/result path. Optional: with `RABBITMQ_URL`
  unset the bot still starts and still watches channels, but uploads fail with "RabbitMQ unavailable"
  and no directory lookup is served.
- **PostgreSQL** — the tables above, always through `shared.repository`; no ad hoc SQLAlchemy in this
  service.
- **Redis** — the `subscription.updated` realtime signal and the subscription-resolver caches.
- **parser-service** — over the broker only. It is never called over HTTP.
- **identity-service** — over the gateway, for the machine-to-machine service token (below).

## Configuration

`backend/env/discord.env`, layered over `backend/env/common.env` (see the `.example` files). What
actually changes behaviour:

- `DISCORD_TOKEN` — bot token. Also passed to the subscription resolver for its own Discord calls.
- `RABBITMQ_URL` — optional. Unset disables every broker subscriber and the upload path.
- `REDIS_URL` — required. Without it, membership events resolve subscriptions but never invalidate the
  realtime cache.
- `PROXY_TYPE` / `PROXY_IP` / `PROXY_PORT` / `PROXY_USERNAME` / `PROXY_PASSWORD` — egress proxy for all
  Discord traffic, both the gateway connection and attachment downloads.
- `AUTH_SERVICE_URL`, `SERVICE_CLIENT_ID`, `SERVICE_CLIENT_SECRET`, `SERVICE_TOKEN_SKEW_SECONDS` —
  service authentication, below.
- `PARSER_URL` — base URL for the parser HTTP client. Retained by `ParserClientFactory`; see the
  operational note on the unexercised internal path.
- `WORKER_METRICS_PORT`, `LOG_LEVEL`, `JSON_LOGGING`, `TRACING_ENABLED`, `OTLP_ENDPOINT` — observability.

### Service authentication

`ServiceTokenClient` exchanges `SERVICE_CLIENT_ID` / `SERVICE_CLIENT_SECRET` for a service access token
by POSTing `{AUTH_SERVICE_URL}/service/token`. In production `AUTH_SERVICE_URL` is
`http://gateway:8080/api/auth`, so the call lands on the Go gateway, which forwards it as an RPC to
`rpc.identity.service_token` on identity-service — this service never talks to identity directly.

The token identifies the *process*, not a user: its claims are `sub=discord-service`, `type=service`,
`iss=auth-service`, `aud=internal`, and whatever scope list identity has configured for this client id
in `SERVICE_SCOPES`. It carries no user id, no workspace, and no RBAC role, so it authorises nothing a
user could do — it only proves to another internal service that the caller is this bot. Lifetime is
short (5 minutes by default on the identity side); the client caches it and refreshes
`SERVICE_TOKEN_SKEW_SECONDS` early, under a lock so concurrent callers share one round trip instead of
each minting a token.

## Running

```bash
# Local
python main.py

# Dev stack: the workers profile is required.
make dev-up-full                                  # core stack + workers
docker compose --profile workers up -d discord-worker
```

`make dev-up` deliberately does **not** start this service — it sits behind `profiles: ["workers"]` in
`docker-compose.yml`, so the core dev stack comes up without a live Discord connection. Dev runs the
process under `watchfiles` with forced polling; production runs `python main.py` bare, with
`restart: always` and a trivial `python -c "import sys; sys.exit(0)"` healthcheck — the bot serves no
port, so that check proves only that the interpreter runs, not that the gateway session is alive.

## Operational notes

- **Single replica.** Every replica opens its own Discord gateway session under the same token and
  therefore receives the *same* `on_message` events, so N replicas do N uploads of the same
  attachment. The `_processing_messages` guard is per-process and the `exists_done` check is a racy
  read, neither is a cross-replica lock. The broker side is replica-ready — request/reply queues
  round-robin and the exclusive result queue exists precisely so results reach the right replica — but
  the gateway side is not. Do not scale this service; it is absent from the default `PROD_SCALE` set
  for that reason.
- **Failure handling on `discord_commands`.** A malformed payload, a missing channel, a deleted
  message, or a permissions error is `reject`ed straight to `discord_commands.dlq`; an unexpected
  exception is `nack`ed and requeued. A `send_dm` the recipient cannot receive (DMs closed, no mutual
  guild, unknown user) is `ack`ed instead — the notification already exists in the in-app inbox, and
  no retry changes the outcome. Retries are RabbitMQ's, there is no application-level backoff.
- **Upload timeout.** A parse result that does not arrive within 120 s leaves the message marked as
  timed out even if the parse later succeeds. The upload itself is not retried.
- **Idempotency is by `(tournament_id, filename)`**, checked against `log_processing.record` before
  upload. Two different logs sharing a filename inside one tournament collapse to one; a re-upload
  after a failed parse is allowed, because only a `done` record blocks.
- **History rescan cost.** Startup and every `process_all` walk up to 500 messages per channel, all
  channels concurrently, each attachment costing one Discord CDN download through the proxy.
- **The internal HTTP path to parser is currently unexercised.** `ParserClientFactory.create()` only
  attaches the service token when called with `destination="internal"`, and the sole call site passes
  `destination="discord"` (the CDN download). Since match-log upload moved to the broker, nothing in
  this service mints a service token at runtime; `PARSER_URL` and the credentials are configured for a
  path that no longer runs.

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
- **Metrics:** Prometheus on `WORKER_METRICS_PORT` (dev 9100, prod 9100) — the shared worker metrics
  plus `discord_gateway_ready` and `discord_gateway_latency_seconds`

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

No RPC namespace of its own. The gateway's route table contains no entry pointing here, and
`/api/docs` does not describe this service. Everything below is broker or gateway-event traffic;
the only outbound RPCs are the ones a card button makes (see *User-facing surface*).

### RabbitMQ

| Queue / exchange | Direction | Purpose |
| --- | --- | --- |
| `discord_commands` | consumes | `DiscordCommandEvent` — `process_all` (rescan every channel of a tournament), `process_message` (re-ingest one message), `post_message` (one Components V2 `card` to a channel, with the PNG it shows when `card.image_url` is `attachment://<file>`), `send_dm` (one card to one user), `edit_message` (replace the card of a message the bot sent) and `delete_message` (remove it). The four message actions carry `message_ref`, the `discord_message` row the platform claimed for that message: the bot resolves *where* the message is from that row and writes back what Discord answered, so no publisher ever handles a Discord message id and one delete path serves DMs and channel posts alike. Every message is a card; there is no plain content or embed path. `allow_mentions=true` lets the users a card `<@id>`-mentions be pinged — never `@everyone` or a role; `false` (the default) and every DM ping nobody. A Discord refusal other than a missing channel/user or a closed DM (a 400 on the payload, an outage outlasting discord.py's own retries) is rejected to the DLQ with status `discord_error`, never requeued — and the row says `failed` with the reason either way. Published by parser-service's `rpc.discord_channel.backfill`, balancer-service's mix posts, live signup edits and post deletions, and app-service's notification delivery. |
| `rpc.identity.discord_identity` | requests | The linked account's identity payload for a clicking Discord user (`not_found` = not linked). A successful answer is cached for 30 s (see *Operational notes*). |
| action subjects | requests | `rpc.tournament.regteam_accept` / `regteam_decline` / `reg_pub_check_in` / `reg_pub_get_me`, `rpc.app.notification_preferences_update`, `rpc.balancer.custom.self_*` — each called with that identity, exactly as the gateway would for the same person on the site. |
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

**Look.** One palette and one emoji set for every surface, defined once in
`shared/domain/discord_ui.py`. Publishers write an emoji as a shortcode (`:owt_tank:`) in card text
and by name (`emoji="tank"`) on a button; `src/interactions/emoji.py` swaps them for the
**application emoji** uploaded as `owt_<name>` (Developer Portal → the app → Emojis; they work in
every guild and in DMs), loaded once in `setup_hook`. An emoji not uploaded shows its Unicode
fallback; a division badge (`div_<tier slug>`) has none and simply disappears. The dev and prod
bots are different applications with different emoji ids, which is why no id ever leaves this
service — see *Operator tools* for the uploader.

**Card buttons.** Notification cards (built by app-service, laid out by `src/interactions/cards.py`)
carry link buttons and action buttons. An action button's `custom_id` is `owt:<action>:<target>` —
what and on which object, never on whose behalf. `InteractionsCog.on_interaction` answers every such
click — and every submit of a form the bot opened — by `custom_id` (no per-message views, so cards
keep working across restarts), and `ActionDispatcher` runs it:

1. acknowledge within Discord's 3 s (a deferred message update — nothing flashes in the channel);
   `mix.setup` is the exception: it answers with its form, which Discord accepts only as the very
   first response, so nothing is looked up before it;
2. `rpc.identity.discord_identity` for `interaction.user.id` — not linked → the clicker is told how to
   link, and **no platform call is made**; deactivated → refused;
3. the action's own RPC with that identity (`src/interactions/actions.py` is the whole, fixed
   list — see the table below);
4. an ephemeral reply in the clicker's Discord language, iconed and coloured by outcome (ok green;
   a rule refusal or an outage amber; an error red), with refusals worded by the service's machine
   code (`invite_expired`, `check_in_closed`, …);
5. in a DM only, the spent buttons come off the card and a status line takes their place. A button
   on an ephemeral reply is answered by replacing that reply rather than stacking another under it.

The DM card carries a small «Notifications» button (`notifications.menu`, answered by the bot
alone): it opens, for the reader alone, a prompt with «turn all off» (`notifications.mute:all` —
every DM group false; in-app notifications stay) and a notification-settings link. Discord allows
ephemeral messages only as an answer to a click, hence the trigger rather than a separate DM.

| Action | RPC | Where the component lives |
|---|---|---|
| `invite.accept` / `invite.decline` | `rpc.tournament.regteam_accept` / `…regteam_decline` | team-invite DM card |
| `check_in` | `rpc.tournament.reg_pub_check_in` | tournament DM card |
| `registration.view` | `rpc.tournament.reg_pub_get_me` | tournament DM card |
| `notifications.menu` | — (the bot alone) | every DM card |
| `notifications.mute` | `rpc.app.notification_preferences_update` | the prompt `notifications.menu` opens |
| `mix.join` | `rpc.balancer.custom.self_join` | mix signup post, seat panel |
| `mix.leave` | `rpc.balancer.custom.self_leave` | mix signup post, seat panel |
| `mix.roles` | `rpc.balancer.custom.self_get` | mix signup post («My seat») |
| `mix.setup` | — (the bot alone: opens the seat form) | seat panel |
| `mix.seat_set` | `rpc.balancer.custom.self_update` | the seat form's submit |

**Mix self-signup.** A host opens signup for a pickup mix and balancer-service posts one **live**
card into the workspace's channel: who hosts, how many lobbies, where a new player lands, how many
signed up by first role, «Join» / «My seat» / «Leave». balancer-service edits it (`edit_message`)
whenever something it shows changes; it locks with a disabled «Join» when signup closes and loses
its buttons when the mix ends. Edits of one message within 2 s collapse into the last one here, and
a host removing a post (or the whole mix) sends `delete_message` for its row, which is how the card
leaves the channel.

Every `mix.*` action answers with the same self-state, rendered into the **seat panel**, an
ephemeral card: participation and lobby, the role order with rank and division badge, the roles not
played, flex, and notes (unranked roles, role edits locked by the host). Its «Edit roles»
(`mix.setup`) opens a form — three radio groups («1st/2nd/3rd role», the first also offering «any
ranked role») and a flex checkbox, prefilled from the button's own target
(`<game>-<order>-<flex>`, e.g. `42-ts-1`; `a` = any ranked role, `x` = none), so the bot keeps no
state. The submit (`owt:mix.seat_set:<game>`, fields `role1`..`role3`, `flex`) becomes one
`self_update`; a value the bot never minted is refused before any platform call, and the panel is
replaced in place. Refusals are worded from the mix's own blocker codes (`signup_closed`,
`roster_full`, `role_edit_off`, …); the three link blockers (`discord_not_linked`,
`battlenet_not_linked`, `player_not_linked`) add a profile link.

**`/mix`** (guild-only) shows the same seat panel for the newest open mix of the workspace bound to
that guild (`workspace.discord_guild_id` → `rpc.balancer.custom.self_current`), so a player never
has to scroll for the signup post. It is the bot's only application command; the tree is synced by
the operator tool below, never on boot.

**Lineup post.** `custom.post_discord` sends one card: mix · lobby · game, the map and the points a
win moves, the host's screenshot of the matchup as the card's picture (team blocks in text when
there is none), and a line mentioning every seated player with a linked Discord — the one post that
pings.

A clicker's identity is looked up once and reused for 30 s, so a chain of clicks (open the panel,
edit roles, submit, leave) costs one identity RPC instead of four; an unlink or a deactivation
therefore bites within half a minute rather than on the very next click. Only a *successful* answer
is kept — "not linked" and "deactivated" are re-asked every time, so linking an account takes effect
at once. Every click logs one line with `action`, `target`, `status` and `code`.

**Match logs.** Passive: post a `.txt`, `.log`, or `.json` file in a monitored channel and the bot
reacts `owt_ok` / `owt_warn` / `owt_error` and, where the outcome needs words, replies with the parse
error. Reactions are reconciled, not just added, so a re-processed message ends with only the
reaction matching its current state — the legacy ✅ / ⚠️ / ❌ included.

### Operator tools

Run from `backend/discord-service` with the service env (REST only, safe beside the live bot):

- `python -m src.tools.emoji_sync [--dry-run] [--dir PATH] [--grids]` — uploads every missing
  `owt_<name>` application emoji: the role icons from `frontend/public/roles`, the division badges
  from `frontend/public/divisions/<slug>.png`, and anything drawn into
  `assets/emoji/<name>.png|gif|webp` (names from `shared/domain/discord_ui.py`; ≤ 256 KiB). An
  existing name is never replaced — delete it in the portal first, which blanks it in messages
  already posted. Once per application.
  `--grids` adds the badges no file in the repo carries: every tier of every **division grid** in the
  database, uploaded as `div_<slug>` (the name `division_emoji` builds) from the tier's `icon_url`,
  relative URLs resolved against `PUBLIC_SITE_URL` over plain HTTP — the site is ours, so the Discord
  egress proxy is not used. A slug claimed by two different grids is uploaded once (first grid wins)
  and warns with both grid ids; two versions of one grid repeating a slug is normal and silent. A
  response over 256 KiB or without an `image/*` content type is skipped by name, and the plan warns
  up front if the application would pass Discord's 2000-emoji cap. Needs database access; rerun it
  after a workspace publishes a grid.
- `python -m src.tools.sync_commands [--guild ID]` — syncs `/mix`; `--guild` for an instant dev sync.
- `python -m src.tools.preview --channel ID card.json ...` — posts `DiscordCard` JSON files through
  the real layout, to judge a design with the uploaded emoji.

### Scheduled work

- `channel_monitor` (`discord.ext.tasks.loop`, every 5 minutes) reloads the active
  `channel_id -> tournament_id` map, so adding or removing a tournament channel takes effect without a
  restart. A finished tournament stays watched for 24 hours so a late upload still lands.
- On `on_ready`, the last 500 messages of every monitored channel are rescanned concurrently and any
  unprocessed attachment is uploaded fire-and-forget (no result wait).
- `GatewayWatchdog` (`discord.ext.tasks.loop`, every 30 s) proves the gateway session is alive — see
  *Operational notes*.

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

Reads elsewhere: `workspace.discord_guild_id` (guild → workspace ids), `auth.oauth_connections`
(Discord user id → platform user) and `discord_message` (below).

Writes `discord_message` — the one state of every message the platform sends on its own behalf
(notification DMs, workspace broadcasts, mix signup and lineup posts). Ownership is split on purpose
and neither half is this service's: **publishers insert** the row in the transaction that decides to
send (`shared/services/discord_messages.py`) and set `deleting` when they want it gone; **this
service updates** it, because it is the only process that hears Discord answer. It writes `status`,
`discord_channel_id`, `message_id` and `error`, and nothing else on the row — never `subject`, never
`dedupe_key`, never a new row. The transitions it performs are exactly `pending → posted` (with the
ids, the DM channel for a DM; conditional on the row still being `pending`), `pending → failed`
(with the reason a refusal gives), `pending → deleted` (a delete reached the row before its own post
did, so the message is deleted by never being sent) and `deleting → deleted` (the message is gone
from Discord, was already, or had just been sent when the delete landed and was taken straight back
out). Every one of them stages the realtime signal of the row's subject on the same transaction, so
the page showing a mix refetches when its post lands, fails or disappears.

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
- **identity-service** — over the gateway, for the machine-to-machine service token (below), and over
  the broker for `rpc.identity.discord_identity` when a card button is pressed.
- **tournament-service, app-service, balancer-service** — over the broker only, for the card actions
  and `/mix`.

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
- `PUBLIC_SITE_URL` — from `common.env`; where button replies link back to (link Discord, notification
  settings), and the base `emoji_sync --grids` resolves a tier's relative `icon_url` against. The same
  value app-service renders the cards' own links from.
- `GATEWAY_HEARTBEAT_PATH` — where the watchdog records a live gateway session and where the
  healthcheck reads it back (default `/tmp/discord-worker.alive`). Both ends read this one variable;
  override it only if `/tmp` is not writable.
- `GATEWAY_UNREADY_TIMEOUT_SECONDS` — how long the gateway session may stay down before the process
  exits so Docker restarts it (default `300`).
- `WORKER_METRICS_PORT`, `LOG_LEVEL`, `JSON_LOGGING`, `TRACING_ENABLED`, `OTLP_ENDPOINT` — observability.

### Service authentication

`ServiceTokenClient` exchanges `SERVICE_CLIENT_ID` / `SERVICE_CLIENT_SECRET` for a service access token
by POSTing `{AUTH_SERVICE_URL}/service/token`. In production `AUTH_SERVICE_URL` is
`http://gateway:8080/api/auth`, so the call lands on the Go gateway, which forwards it as an RPC to
`rpc.identity.service_token` on identity-service — the token path never talks to identity directly.

The token identifies the *process*, not a user: its claims are `sub=discord-service`, `type=service`,
`iss=auth-service`, `aud=internal`, and whatever scope list identity has configured for this client id
in `SERVICE_SCOPES`. It carries no user id, no workspace, and no RBAC role, so it authorises nothing a
user could do — it only proves to another internal service that the caller is this bot. Acting *for* a
user is a separate, narrower path: the card actions above, for linked accounts only, with that user's
own identity payload. Lifetime is short (5 minutes by default on the identity side); the client caches
it and refreshes `SERVICE_TOKEN_SKEW_SECONDS` early, under a lock so concurrent callers share one round
trip instead of each minting a token.

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
process under `watchfiles` with forced polling; production runs `python main.py` bare with
`restart: always`. Both compose files run the same healthcheck, `python -m src.tools.healthcheck`,
every 30 s: it reads the heartbeat file the watchdog touches *only* while the gateway session is
actually up, so an unhealthy container means the bot has gone deaf — not merely that the interpreter
still runs, which is all the old `python -c "import sys; sys.exit(0)"` ever proved. The probe imports
nothing outside the standard library, so it cannot report a configuration problem as a dead session.

## Operational notes

- **Liveness is self-reported.** A Discord gateway session can die while the process stays up:
  discord.py reconnects on its own, and when that loop stops making progress nothing exits, so
  `restart: always` never fires and every card, DM and `/mix` answer silently stops. `GatewayWatchdog`
  (`src/watchdog.py`) ticks every 30 s and, while the bot is ready *and* its latency is a real number
  (it is `NaN` until the first heartbeat round-trip), touches `GATEWAY_HEARTBEAT_PATH` and sets the
  gauges `discord_gateway_ready` (0/1) and `discord_gateway_latency_seconds` on the metrics port.
  Once the session has been down longer than `GATEWAY_UNREADY_TIMEOUT_SECONDS` it logs an error and
  calls `os._exit(1)` — not `sys.exit` or `bot.close()`, because both unwind through the very
  connection that is already broken and an exception inside a `tasks.loop` is caught and logged by
  discord.py rather than ending the process. The counter restarts from the last live tick, so a
  session that recovers is never killed by the outage before it. Docker's probe only reads the file,
  so a watchdog that never ran looks exactly like a bot that never connected: unhealthy.
- **Identity is cached for 30 s.** A successful `rpc.identity.discord_identity` answer is kept per
  Discord user id (`cachetools.TTLCache`, 2048 entries, process memory). The consequence is the
  trade: an unlink or a deactivation bites within 30 s instead of on the next click. Refusals are
  never cached, so a freshly linked account works immediately, and every action RPC still authorises
  on its own — the cache shortens *who you are*, never *what you may do*.
- **Single replica.** Every replica opens its own Discord gateway session under the same token and
  therefore receives the *same* `on_message` events, so N replicas do N uploads of the same
  attachment. The `_processing_messages` guard is per-process and the `exists_done` check is a racy
  read, neither is a cross-replica lock. The broker side is replica-ready — request/reply queues
  round-robin and the exclusive result queue exists precisely so results reach the right replica — but
  the gateway side is not. Do not scale this service; it is absent from the default `PROD_SCALE` set
  for that reason.
- **Failure handling on `discord_commands`.** A malformed payload, a command naming a
  `discord_message` row that no longer exists, a missing channel, a deleted message, or a
  permissions error is `reject`ed straight to `discord_commands.dlq`; an unexpected exception is
  `nack`ed and requeued. A `send_dm` the recipient cannot receive (DMs closed, no mutual guild,
  unknown user) is `ack`ed instead — the notification already exists in the in-app inbox, and no
  retry changes the outcome. Every refusal that settles the message also writes `failed` and its
  reason on the row first, so the page that asked for it stops waiting. A `delete_message` Discord
  refuses is `ack`ed with the row left `deleting`: requeueing it would hammer the same refusal.
  Retries are RabbitMQ's, there is no application-level backoff. A database failure *after* a
  successful send is logged and `ack`ed, never requeued — a second send would post the card twice,
  while a row stuck at `pending` merely reads `lost` once the queue's 5-minute TTL passes.
- **Nothing de-duplicates `discord_commands`; the row does.** The old 60 s debounce on
  `post_message` / `send_dm` is gone — it compared target and body in process memory, which cannot
  tell a redelivery from a deliberate second post. Each case it covered is now guarded where the
  fact lives: a **redelivered command** finds its `discord_message` row past `pending` and is
  `ack`ed without sending anything (the row is the only thing that knows a message was already
  sent); **one event claimed twice** never produces a second command at all, because
  `DiscordMessageRepository.claim` inserts `ON CONFLICT DO NOTHING` on the unique
  `(channel, target, dedupe_key)` in the publisher's own transaction and returns nothing the second
  time; **two notification rows for one event** are prevented a step earlier still, by
  `notify(dedupe_key=…)` returning the existing row over `ix_notification_dedupe` instead of writing
  a second one. A deliberate repeat — a host pressing "post" again — carries no `dedupe_key`, so it
  is a new row and it posts, which the debounce used to swallow.
- **Order between commands for one message is the row's doing, not the broker's.** aio-pika runs
  every delivery in its own task (`aiormq.Channel._on_deliver` → `create_task`) and this broker sets
  no `prefetch_count`, so FastStream gives this subscriber no serialisation whatsoever: two commands
  naming the same row can be in flight together. What orders them is the state each handler reads
  and writes. An `edit_message` whose row is still `pending` waits out up to
  `EDIT_PENDING_ATTEMPTS` coalescing windows (~10 s) for the post to land, then drops the edit — the
  next change re-renders the whole card anyway. A `delete_message` that finds no `message_id` yet
  leaves the row `deleting` and deletes nothing; the post handler reads that status and closes the
  row *instead of* sending, so the message is deleted by never existing. The last interleaving — a
  delete reading the row while the post is mid-`send` — is closed in the database: `mark_posted` is
  an `UPDATE … WHERE id = :id AND status = 'pending'` and reports whether it applied, so a row the
  delete already moved to `deleting` never becomes `posted`. The bot, holding the message it has
  just created, deletes it on the spot and marks the row `deleted`.
- **Edit coalescing.** `edit_message` is deferred by 2 s per `message_ref`, last card wins, and is
  `ack`ed on scheduling (A → B → A must end on A, so it is coalesced, never de-duplicated). A
  `delete_message` drops the edit still waiting for its message. The window is process memory, which
  the single-replica rule above makes enough; a crash loses one pending edit until the next change.
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

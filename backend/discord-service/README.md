# Discord Service (discord-worker)

The Discord side of the platform: a [discord.py](https://discordpy.readthedocs.io/) bot that sends
every Discord message the platform sends, answers the buttons on them, watches tournament channels for
match-log attachments, and answers the guild/member lookups other services need. **Every Discord
interaction except the OAuth login goes through this process**: no other service holds
`DISCORD_TOKEN`, calls Discord's REST API or renders a Discord card. It exists as its own process
because a Discord gateway session is stateful and single-tenant — one persistent WebSocket per bot
token, carrying the message-content and members intents — and that connection cannot be shared with
or restarted alongside a stateless RPC worker.

It runs no HTTP server. It is reached by Discord itself over the gateway WebSocket, and by the rest of
the platform over RabbitMQ only: its own `rpc.discord.*` namespace (which the Go gateway routes the
admin Discord screens to), named queues (`discord_commands`, `discord_member_roles`,
`discord_guild_*`, `discord_voice_move`, `pickup_mix_changed`, `upload_match_log`,
`match_log_result`, `discord_member_changed`) and the `tournament.events` exchange. See
[`../../docs/architecture.md`](../../docs/architecture.md) for how it sits in the wider platform.

- **Compose service:** `discord-worker` — dev profile `workers`, unconditional in production
- **Entry point:** `main.py` (`LogCollectorBot` in `src/bot.py`)
- **Run command:** `python main.py`
- **Transport:** Discord gateway WebSocket inbound; RabbitMQ — `rpc.discord.*` request/reply, named
  queues, plus one per-replica queue on the `tournament.events` topic exchange; no HTTP
- **Metrics:** Prometheus on `WORKER_METRICS_PORT` (dev 9100, prod 9100) — the shared worker metrics
  plus `discord_gateway_ready` and `discord_gateway_latency_seconds`

## Responsibilities

- **Every message the platform sends.** Notification DMs, workspace broadcasts, mix signup and lineup
  posts: a publisher claims a `discord_message` row and queues a cardless `send`; the bot renders the
  card from that row (`src/render/`) and posts it. Live mix cards are re-rendered by the bot itself
  whenever their mix changes (`pickup_mix.changed`, `src/services/mix_projector.py`).
- **Card buttons and `/mix`.** Answers every click and form on those cards as the clicking user's
  linked account (see *User-facing surface*).
- **Match-log intake from Discord.** Turns qualifying attachments in watched tournament channels
  into upload requests. It downloads the actual bytes; stats-service owns workspace/content-hash
  deduplication, so a reused filename never hides changed content.
- **Upload feedback.** Marks the hand-off on the message at once, then adds each file's verdict
  (`done`, `failed` or `awaiting_link`, with its error text) when stats-service's result names that
  message. It never queries a latest-by-filename record to invent a verdict.
- **Tournament channel bindings.** Which Discord channel a tournament collects logs from
  (`rpc.discord.channel.*`), validated against the workspace's own guild.
- **Discord directory.** The only process holding a live guild cache, so it answers guild info, guild
  roles, guild channels, and per-member role sets on behalf of every other service — and the
  workspace Discord screens through `rpc.discord.workspace_*`.
- **Member changes as events.** A member joining, leaving, or having roles changed is published as
  `DiscordMemberChangedEvent`; stats-service re-resolves that user's Boosty subscription instead of
  waiting for its scheduled sweep.

## Interface

### `rpc.discord.*`

Request/reply subjects in `src/rpc_api.py`, routed by the Go gateway (`gateway/internal/discord`,
identity injected there) and described in `/api/docs` (`src/openapi_schemas.py`, `src/openapi_docs.py`).
Each one authorises with the caller's identity in the workspace the object belongs to.

| Subject | HTTP path | Permission | Answer |
| --- | --- | --- | --- |
| `rpc.discord.workspace_roles` | `GET /api/v1/workspaces/{workspace_id}/discord/roles` | `workspace.update` | `{guild_id, roles}` |
| `rpc.discord.workspace_channels` | `GET /api/v1/workspaces/{workspace_id}/discord/channels` | `workspace.update` | `{guild_id, channels}` |
| `rpc.discord.workspace_guild` | `GET /api/v1/workspaces/{workspace_id}/discord/guild` | `workspace.update` | `{guild_id, connected, name, icon_url, member_count, owner_*}` |
| `rpc.discord.channel.get` / `upsert` / `backfill` / `delete` | `/api/v1/admin/tournaments/{id}/discord-channel[...]` | `discord_channel.read` / `update` / `update` / `delete` | the tournament's binding (`DiscordChannelRead`) |

A workspace with no linked guild answers `guild_id: null` and empty lists (`connected: false`); a
Discord failure answers the body with a stable `error` code (`guild_not_found`, `discord_error`,
`invalid`) instead of a 500 — the exception text is logged, never returned. `channel.upsert` accepts
only a text channel of the tournament workspace's guild: 409 `discord_guild_not_linked`, 422
`discord_channel_not_in_guild`, 503 `discord_unavailable` when the channel lookup itself fails. A
write reloads the watched-channel map in-process; `backfill` starts an in-process rescan of the last
500 messages and answers at once (404 without an active binding).

The other outbound RPCs are the ones a card button makes (see *User-facing surface*) and
`rpc.balancer.custom.discord_view`, the mix view the bot renders mix cards from.

### RabbitMQ

| Queue / exchange | Direction | Purpose |
| --- | --- | --- |
| `discord_commands` | consumes | `DiscordCommandEvent` — `{action: send \| delete, message_ref}` and nothing else. `message_ref` is the `discord_message` row a publisher claimed (`shared/services/discord_messages.py`); the row says where the message goes (`channel` + `target`) and what it is about (`kind`, `subject`, `slot`, `payload_json`). `send` renders the row (`src/render/`) and posts it to the channel or DMs the user; `delete` removes the posted message. The bot writes back what Discord answered, so no publisher ever handles a Discord message id or a card, and one delete path serves DMs and channel posts alike. Edits are never commands: see `pickup_mix_changed`. |
| `pickup_mix_changed` | consumes | `PickupMixChangedEvent` from balancer-service's and tournament-service's outboxes: re-render the live cards of that mix (or of every mix of the workspace) — `src/services/mix_projector.py`. |
| `rpc.balancer.custom.discord_view` | requests | The view a mix card is rendered from: signup state and roster, and each requested lineup with its seats, map, lobby code, team names, Discord ids to ping and whether it is still `current` (5 s timeout; `not_found` = the mix is gone). |
| `rpc.identity.discord_identity` | requests | The linked account's identity payload for a clicking Discord user (`not_found` = not linked). A successful answer is cached for 30 s (see *Operational notes*). |
| action subjects | requests | `rpc.tournament.regteam_accept` / `regteam_decline` / `reg_pub_check_in` / `reg_pub_get_me`, `rpc.app.notification_preferences_update`, `rpc.balancer.custom.self_*` — each called with that identity, exactly as the gateway would for the same person on the site. |
| `discord_member_roles` | consumes, replies | Role ids held by a set of users in a guild. Called by the shared Discord-role subscription strategy (`shared/services/subscriptions/strategies.py`, 5 s timeout). |
| `discord_guild_roles` | consumes, replies | The guild's role list. |
| `discord_guild_channels` | consumes, replies | The guild's text channels. |
| `discord_guild_info` | consumes, replies | Guild name, icon, member count, connectivity. |
| `discord_voice_move` | consumes, replies | Move a lobby's players between voice channels (the lineup card's voice buttons, through balancer-service). |
| `upload_match_log` | publishes | `UploadMatchLogEvent` carrying the log bytes base64-encoded plus the `channel_id`/`message_id` it came from, consumed by stats-service. |
| `match_log_result` | consumes | `MatchLogProcessedEvent`, the parse verdict for one uploaded file, naming the message to put it on. |
| `discord_member_changed` | publishes | `DiscordMemberChangedEvent` (guild, user, `role_update` / `member_join` / `member_remove`), straight from the gateway event — there is no transaction for an outbox row to join. Consumed by stats-service. |
| `tournament.events` (topic exchange) | consumes | `tournament.state.changed`, on a server-named, exclusive, auto-deleted queue per replica: each replica reloads its own watched-channel map. A binding changed through `rpc.discord.channel.*` reloads it in-process. |

The durable queues it consumes (`discord_commands`, the five `discord_*` request/reply queues,
`match_log_result` and `pickup_mix_changed`) dead-letter to `dlx` with a `<name>.dlq` routing key —
the bot declares all eight DLQs before it starts consuming — and most carry a message TTL (60 s for
the directory lookups, 5 min for `discord_commands` and `match_log_result`) — a lookup no live bot
answers expires rather than piling up. `discord_commands` and `pickup_mix_changed` each consume on
their own channel with `prefetch_count=4`: a send renders a card (an RPC, maybe a picture drawn)
before Discord answers, and a burst queues at the broker instead of starting a task per delivery.
Every Discord-facing handler awaits `bot.wait_until_ready()` first, so a request arriving during
startup blocks until the gateway session is up instead of answering from an empty cache. Directory
lookups fall back to a REST call when the gateway cache has not yet seen the guild.

### Match-log upload and its verdict

`AttachmentProcessor` downloads the attachment through the egress proxy and publishes the base64
bytes to `upload_match_log` as `UploadMatchLogEvent`, naming the message it came from
(`channel_id`, `message_id`). Nothing waits: once a message's files are out its reactions are
reconciled to `ok` (all went out), `ok` + `warn` (some did) or `error` (none did; the reason is
logged).

stats-service echoes the two ids onto `MatchLogProcessedEvent`, which carries the persisted
`ingest_job_id`, status and error text; only upload failure before job creation has a null job id.
`awaiting_link` means the bytes were accepted but no unique eligible live game was found: the
uploader is told to ask an administrator to select the encounter/game and retry. Results land on the
one durable `match_log_result` work queue; any replica can consume one, because the event says which
message it answers. The handler fetches that message (a message deleted or hidden since is acked and
logged) and **adds** the verdict: `ok` for a processed file; `ok` + `warn` and a reply naming the
file and its error for anything else — `ok` stays, since the upload itself went through. It never
removes a reaction, so on a message with several logs a later success cannot take back an earlier
file's `warn`, and adding a reaction the bot already has is a no-op.

### Discord gateway events

`LogIngestionCog` — `on_ready` (load channels, catch up on missed history, start the fallback reload loop),
`on_message` and `on_message_edit` in monitored channels. `MembershipEventsCog` —
`on_guild_join`/`on_guild_remove` (logging only) and `on_member_join`/`on_member_remove`/`on_member_update`
(publish `DiscordMemberChangedEvent`; with `RABBITMQ_URL` unset the change is logged and dropped).

### User-facing surface

**Look.** One palette and one emoji set for every surface, defined once in `src/ui.py`. The
renderers (`src/render/`) write an emoji as a shortcode (`:owt_tank:`) in card text and by name
(`emoji="tank"`) on a button; `src/interactions/emoji.py` swaps them for the
**application emoji** uploaded as `owt_<name>` (Developer Portal → the app → Emojis; they work in
every guild and in DMs), loaded once in `setup_hook`. An emoji not uploaded shows its Unicode
fallback; a rank badge (`div_*`) has none and simply disappears. The dev and prod
bots are different applications with different emoji ids, which is why no id ever leaves this
service — see *Operator tools* for the uploader.

**Cards.** Every card the bot sends on the platform's behalf is a `DiscordCard`
(`src/render/card.py`) rendered from its `discord_message` row by `src.render.render` and laid out
as Components V2 by `src/interactions/cards.py`: a notification from the payload its publisher
stored on the row (`src/render/notifications.py`, ru/en by the workspace's notification locale,
branded with the workspace name and the tournament logo or workspace icon as they are when the card
is rendered), a mix card from the view balancer-service answers (`src/render/mix.py`). A
notification never pings; a lineup pings its seated players and nobody else.

**Card buttons.** Cards carry link buttons and action buttons. An action button's `custom_id` is
`owt:<action>:<target>` —
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
| `mix.away` / `mix.back` | `rpc.balancer.custom.self_away` (`away: true` / `false`) | mix signup post |
| `voice.move` / `voice.return` | — (the bot alone: a confirm prompt) | the lobby's newest lineup card |
| `voice.move_confirm` / `voice.return_confirm` | `rpc.balancer.custom.voice_move` / `…voice_return` | that prompt |

**Mix self-signup.** A host opens signup for a pickup mix; balancer-service claims a
`mix.signup` row (`subject='mix:<id>'`, `slot='signup'`, no payload) and queues `send`, and the bot
renders one **live** card into the workspace's channel from `rpc.balancer.custom.discord_view`: who
hosts, how many lobbies, where a new player lands, each lobby's stage (`signup.lobbies`, with a running
match's or live draft's clock), the roster by first role in the mix's own game (`discipline_roles`:
Overwatch roles and Full flex by emoji, other games' roles by name, none in a one-role game; a rank
badge from the game's own ladder), away players marked and out of the role counters, a footer naming the
game's identity provider (`DISCIPLINES[d].identity_provider`: Battle.net, Riot ID, Steam), and
«Join» / «My seat» / «Leave» / «Away» / «Back». Any mutation that changes what the card shows — a click here, an edit
on the site, a host closing signup — emits `pickup_mix.changed`, and the bot's projector re-renders
the mix's newest live signup card and every live lineup card of it (an event naming no mix — a
renamed player — re-renders every mix's signup card in the workspace). Re-renders of one message
within 2 s collapse into a single Discord edit of the render made at that moment; a render equal to
the row's `card_json` edits nothing. The post locks with a disabled «Join» when signup closes and
loses its buttons when the mix ends. A host removing a post (or the whole mix) queues `delete` for
its row, which is how the card leaves the channel.

Every `mix.*` action answers with the same self-state, rendered into the **seat panel**, an
ephemeral card: participation and lobby, the role order with rank (and the division badge of the
game's own ladder), the roles not played, flex, an «away» line, and notes (unranked roles, role edits locked by
the host). The panel names the game's roles from the self state's `discipline_roles`; a one-role game
shows its rank alone. Its «Edit roles» (`mix.setup`, never offered for a one-role game such as
Deadlock) opens a form — `min(3, role count)` radio groups over the mix game's rated roles («1st/2nd/3rd
role», the first also offering «any ranked role»; for a game with more roles, LoL's five positions,
the first says the full order is set on the site) and a flex checkbox when the game has Full flex —
prefilled from the button's own target (`<game>-<discipline>-<order>-<flex>`, e.g. `42-overwatch-ts-1`,
`42-lol-mts-0`; one letter per role, its code's first, unique per game; `a` = any ranked role,
`x` = none), so the bot keeps no state. The submit (`owt:mix.seat_set:<game>-<discipline>`, fields
`role1`.., `flex`) becomes one `self_update` whose order is the form's picks, so a LoL order of five
comes back as three; a value the bot never minted is refused before any platform call, and the panel is
replaced in place. Refusals are worded from the mix's own blocker codes (`signup_closed`,
`roster_full`, `role_edit_off`, …); the link blockers add a profile link: `discord_not_linked`,
the mix game's provider (`battlenet_not_linked` for Overwatch, `riot_not_linked` for League of
Legends, `steam_not_linked` for Deadlock) and the provider-neutral `player_not_linked`.

A lobby captain's DMs (`mix.ban_room_opened`, `mix.draft_started`) are ordinary notifications
rendered by `src/render/notifications.py`, with a «Lobby room» link to
`/balancer/mix/<game>/lobby/<letter>`.

**`/mix`** (guild-only) shows the same seat panel for the newest open mix of the workspace bound to
that guild (`workspace.discord_guild_id` → `rpc.balancer.custom.self_current`), so a player never
has to scroll for the signup post. It is the bot's only application command; its names and
descriptions are Russian with English translations, installed when the operator tool below syncs
the tree — never on boot.

**Lineup post.** balancer-service claims a `mix.lineup` row (`slot='lineup:<lobby>:<match>'`); the
bot renders one card from the view's lineup — mix · lobby · game, the map and the points a win
moves, the lobby's in-game join code as inline code (when the host set one; a backtick in it reads as `'`),
the matchup as a 1200×630 PNG it draws itself (`src/render/mix_lineup_image.py`, fonts and
role glyphs in `assets/lineup`, map art and rank badges fetched over HTTP), and a line mentioning
every seated player with a linked Discord — the one post that pings. Only a lobby's newest live
lineup card carries the voice buttons: posting a new one re-renders the lobby's older ones without
them. A lineup whose match is recorded (or whose mix is over) is history and stays as it was posted.

A clicker's identity is looked up once and reused for 30 s, so a chain of clicks (open the panel,
edit roles, submit, leave) costs one identity RPC instead of four; an unlink or a deactivation
therefore bites within half a minute rather than on the very next click. Only a *successful* answer
is kept — "not linked" and "deactivated" are re-asked every time, so linking an account takes effect
at once. Every click logs one line with `action`, `target`, `status` and `code`.

**Match logs.** Passive: post a `.txt`, `.log`, or `.json` file in a monitored channel and the bot
reacts `owt_ok` / `owt_warn` / `owt_error`. Failures include the correlated error text, and
awaiting-link includes an actionable administrator-link-and-retry reply, even for a single
attachment, in the guild's preferred locale (ru/en). Reactions are reconciled so a reprocessed
message reflects its current result.

### Operator tools

Run from `backend/discord-service` with the service env (REST only, safe beside the live bot):

- `python -m src.tools.emoji_sync [--dry-run] [--dir PATH]` — uploads every missing
  `owt_<name>` application emoji: the set in `assets/emoji/<name>.png|gif|webp` (rendered by
  `node frontend/scripts/gen-discord-emoji.mjs`: the site's role icons tinted with the role colours,
  everything else lucide icons in the `--aqt-*` palette), plus every game's rank emblems: each
  native ladder tier's `icon_url` under the checkout's `frontend/public`, named by `badge_name` in
  `src/ui.py` — Overwatch's `/divisions/<slug>.png` as `div_<slug>`, another game's picture as
  `div_<game>_<file>` (Deadlock's Mystic 1..6 all `div_deadlock_mystic`); ≤ 256 KiB. Signup rows,
  the seat panel and the lineup picture badge a rank with its game's own ladder (`ladder_grid`),
  never with a workspace's own grid, whose tiers are bare numbers — so these 91 (45 Overwatch,
  10 LoL, 11 Deadlock, 25 Valorant) are the only badges it needs. An existing name is never
  replaced — delete it in the portal first, which blanks it in messages already posted. Once per
  application. Exits non-zero when Discord refused an upload; the Discord calls go through the
  egress proxy, like the bot's.
  **Normally it runs as the one-shot `discord-emoji` compose service** (profile `tools`, so `up`
  never starts it): `ops/deploy/remote-deploy.sh` runs it on every release right after the
  migrations — non-fatal, a missing emoji only falls back to Unicode — and `make prod-discord-emoji`
  / `make discord-emoji` run it by hand. It mounts the checkout's `frontend/public`, which the bot
  image does not carry.
- `python -m src.tools.sync_commands [--guild ID]` — syncs `/mix` with its English translations;
  `--guild` for an instant dev sync.
- `python -m src.tools.preview --channel ID card.json ...` — posts `DiscordCard` JSON files through
  the real layout, to judge a design with the uploaded emoji.

### Scheduled work

- The watched `channel_id -> tournament_id` map reloads on every `tournament.state.changed` (see
  *RabbitMQ*) and in-process after every `rpc.discord.channel.*` write; reloads run one at a time, a
  burst queueing behind the one in flight. `channel_monitor` (`discord.ext.tasks.loop`, every 60
  minutes) is only the fallback: no event announces a finished tournament leaving its 24-hour grace
  (kept so a late upload still lands), and it also repairs an event that was lost.
- Application emoji are re-read from Discord every 10 minutes (and once in `setup_hook`), so an
  upload by the `discord-emoji` job shows up without a restart.
- On `on_ready`, every monitored channel catches up on what it missed: the messages after its rescan
  cursor (`stats.discord_channel.last_scanned_message_id`, at most 500, oldest first), or the last
  500 when it has none. Qualifying attachments are uploaded; stats-service deduplicates their bytes.
- Re-renders of live mix cards wait out a 2 s coalescing window per message (see *Operational
  notes*).
- `GatewayWatchdog` (`discord.ext.tasks.loop`, every 30 s) proves the gateway session is alive — see
  *Operational notes*.

### Redis realtime

Every `discord_message` status change the bot writes stages the realtime signal of the row's subject
(see *Data owned*); a re-render that only changes `card_json` stages nothing. The bot consumes no
realtime topic.

### Domain events

`DiscordMemberChangedEvent` onto `discord_member_changed`, published straight from the gateway event:
there is no transaction for an outbox row to join, and a lost one is caught up by stats-service's
scheduled subscription sweep. This service does not write to the transactional outbox.

## Data owned

It owns no schema of its own. Everything it touches belongs to another service's domain, and there
are no migrations here — the single Alembic project lives at `backend/migrations/`.

Reads and writes `stats.discord_channel` — the tournament ↔ channel binding behind the watched-channel
map (`rpc.discord.channel.*`) and each channel's rescan cursor — through `DiscordChannelRepository`.
Match-log jobs and failure details are not read by the bot: upload outcomes arrive on the result
event that names their message. See [`../../docs/database_erd.md`](../../docs/database_erd.md).

Reads elsewhere: `workspace.discord_guild_id` (the guild a workspace posts into — the send guard,
`/mix`, `rpc.discord.*`), `workspace.name` / `icon_url` and `tournament.logo_url` (a notification
card's branding), `notification_workspace_config.locale` (the language of a notification card) and
`discord_message` (below).

Writes `discord_message` — the one state of every message the platform sends on its own behalf
(notification DMs, workspace broadcasts, mix signup and lineup posts). Ownership is split on purpose
and neither half is this service's: **publishers insert** the row in the transaction that decides to
send (`shared/services/discord_messages.py`), with `payload_json` holding what the bot cannot re-read
from a table (a notification's payload; `None` for a mix card, which balancer answers for), and set
`deleting` when they want it gone; **this service updates** it, because it is the only process that
renders the card and hears Discord answer. It writes `status`, `discord_channel_id`, `message_id`,
`error` and `card_json` (its last render, `DiscordCard.model_dump(mode="json")`, which the next
render is compared against), and nothing else on the row — never `subject`, never `payload_json`,
never `dedupe_key`, never a new row. The transitions it performs are exactly `pending → posted` (with
the ids, the DM channel for a DM; conditional on the row still being `pending`), `pending → failed`
(with the reason a refusal gives), `pending → deleted` (a delete reached the row before its own send
did, so the message is deleted by never being sent) and `deleting → deleted` (the message is gone
from Discord, was already, or had just been sent when the delete landed and was taken straight back
out). Every one of them stages the realtime signal of the row's subject on the same transaction, so
the page showing a mix refetches when its post lands, fails or disappears.

## Dependencies

- **Discord** — gateway WebSocket plus REST, through the `proxy` egress container.
- **RabbitMQ** — every inbound request and the log-upload/result path. Optional: with `RABBITMQ_URL`
  unset the bot still starts and still watches channels, but uploads fail with "RabbitMQ unavailable",
  no card is sent and no directory lookup is served.
- **PostgreSQL** — the tables above; every write through `shared.repository`, a few reads as plain
  `sa.select` (branding, the workspace guild).
- **Redis** — the realtime signal of every `discord_message` change.
- **stats-service** — over the broker only. It is never called over HTTP.
- **identity-service** — over the broker for `rpc.identity.discord_identity` when a card button is pressed.
- **balancer-service** — `rpc.balancer.custom.discord_view` for every mix card the bot renders, plus
  the mix card actions and `/mix`.
- **tournament-service, app-service** — over the broker only, for the card actions.
- **The site and its media** — the lineup picture's map art and rank badges, fetched over HTTP
  (`PUBLIC_SITE_URL`, the map image URLs the database stores).

## Configuration

`backend/env/discord.env`, layered over `backend/env/common.env` (see the `.example` files). What
actually changes behaviour:

- `DISCORD_TOKEN` — bot token.
- `RABBITMQ_URL` — optional. Unset disables every broker subscriber, the upload path and the
  member-change events.
- `REDIS_URL` — required. Without it, a `discord_message` change never reaches the page showing it.
- `PROXY_TYPE` / `PROXY_IP` / `PROXY_PORT` / `PROXY_USERNAME` / `PROXY_PASSWORD` — egress proxy for all
  Discord traffic, both the gateway connection and attachment downloads.
- `PUBLIC_SITE_URL` — from `common.env`; the base of every link a card or a button reply carries
  (mix board, tournament pages, notification settings, link Discord) and of the rank badges a lineup
  picture draws.
- `GATEWAY_HEARTBEAT_PATH` — where the watchdog records a live gateway session and where the
  healthcheck reads it back (default `/tmp/discord-worker.alive`). Both ends read this one variable;
  override it only if `/tmp` is not writable.
- `GATEWAY_UNREADY_TIMEOUT_SECONDS` — how long the gateway session may stay down before the process
  exits so Docker restarts it (default `300`).
- `WORKER_METRICS_PORT`, `LOG_LEVEL`, `JSON_LOGGING`, `TRACING_ENABLED`, `OTLP_ENDPOINT` — observability.

### Service authentication

This service holds no service credential: nothing in it calls another service over HTTP, so there is no
service token to mint (identity-service's `SERVICE_CLIENTS` has no discord entry). Acting *for* a user
is the narrow path: the card actions above, for linked accounts only, with that user's own identity
payload. `rpc.discord.*` callers are authorised from the identity the gateway injects.

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
  attachment; the `_processing_messages` guard is per-process, not a cross-replica lock. The
  projector's coalescing windows are process memory too. The broker side is replica-ready —
  request/reply queues, `discord_commands` and `match_log_result` round-robin (a command and a verdict
  name their row and message), and each replica's own channel-registry queue hears every tournament
  change — but the gateway side is not. Do not scale this service; it is absent from the default
  `PROD_SCALE` set for that reason.
- **Failure handling on `discord_commands`.** A malformed payload (an action other than `send` /
  `delete` included), a command naming a `discord_message` row that no longer exists, a missing
  channel, a channel outside the workspace's guild, a permissions error or a payload Discord refuses
  is `reject`ed straight to `discord_commands.dlq`; an unexpected exception — balancer-service not
  answering the mix view included — is `nack`ed and requeued with the row still `pending`. A row
  with nothing to render (its mix is gone, its lineup's match is already played, its payload fills
  no card) and a DM the recipient cannot receive (DMs closed, no mutual guild, unknown user) are
  `ack`ed instead: no retry changes the outcome, and a notification already exists in the in-app
  inbox. Every refusal that settles the message also writes `failed` and its reason on the row
  first, so the page that asked for it stops waiting. A `delete` Discord refuses is `ack`ed with the
  row left `deleting`: requeueing it would hammer the same refusal. Retries are RabbitMQ's, there is
  no application-level backoff. A database failure *after* a successful send is logged and `ack`ed,
  never requeued — a second send would post the card twice, while a row stuck at `pending` merely
  reads `lost` once the queue's 5-minute TTL passes.
- **A channel post goes to the workspace's own guild only.** Before rendering a `discord_channel`
  row the bot checks that the channel's guild is the `workspace.discord_guild_id` of the row's
  workspace; a workspace with no guild linked, or a channel id from another guild (the bot sits in
  every workspace's guild), fails the row with "channel is not in the workspace's Discord guild".
  DMs carry no guild and are not checked.
- **Nothing de-duplicates `discord_commands`; the row and the nonce do.** The old 60 s debounce is
  gone — it compared target and body in process memory, which cannot tell a redelivery from a
  deliberate second post. Each case it covered is now guarded where the fact lives: a **redelivered
  command** finds its `discord_message` row past `pending` and is `ack`ed without sending anything
  (the row is the only thing that knows a message was already sent); a **crash between Discord's
  answer and `mark_posted`** leaves the row `pending`, and the redelivered send carries the same
  `nonce` (the row id, with `enforce_nonce`), so Discord answers it with the message the first send
  created instead of a second one; **one event claimed twice** never produces a second command at
  all, because `DiscordMessageRepository.claim` inserts `ON CONFLICT DO NOTHING` on the unique
  `(channel, target, dedupe_key)` in the publisher's own transaction and returns nothing the second
  time; **two notification rows for one event** are prevented a step earlier still, by
  `notify(dedupe_key=…)` returning the existing row over `ix_notification_dedupe` instead of writing
  a second one. A deliberate repeat — a host pressing "post" again — carries no `dedupe_key`, so it
  is a new row and it posts, which the debounce used to swallow.
- **Order between commands for one message is the row's doing, not the broker's.** The command
  subscriber runs up to four deliveries at once (`prefetch_count=4`, each in its own task), so two
  commands naming the same row can be in flight together. What orders them is the state each handler
  reads and writes. A `delete` that finds no `message_id` yet leaves the row `deleting` and deletes
  nothing; the send handler reads that status and closes the row *instead of* sending, so the
  message is deleted by never existing. The last interleaving — a delete reading the row while the
  send is mid-flight — is closed in the database: `mark_posted` is an
  `UPDATE … WHERE id = :id AND status = 'pending'` and reports whether it applied, so a row the
  delete already moved to `deleting` never becomes `posted`. The bot, holding the message it has
  just created, deletes it on the spot and marks the row `deleted`.
- **Edit coalescing lives in the projector.** A `pickup_mix.changed` event schedules a re-render
  per affected row; the first one opens a 2 s window, and when it closes the bot locks the row
  (`get_for_update`), renders the mix as it is *then*, and edits the message only when the render
  differs from the row's `card_json` — then records it. Events cannot land out of order, and A → B →
  A ends on A. One arriving while a flush writes schedules the next window. A row still `pending`
  (its send is on its way) is waited out for up to `EDIT_PENDING_ATTEMPTS` windows (~10 s), then
  the re-render is dropped — the next change renders the whole card anyway; a row past `posted` is
  left alone, and a message found gone closes its row. A picture is only drawn and uploaded when its
  file name (a hash of everything drawn) differs from the one the message shows. A failed render or
  edit is logged and costs that edit only; the windows are process memory, which the
  single-replica rule above makes enough.
- **A verdict has five minutes to land.** `match_log_result` carries a 5-minute TTL; a result that
  expires dead-letters to `match_log_result.dlq` and the message keeps its hand-off reaction only. A
  verdict whose message was deleted (or the bot can no longer see) is acked and logged, never retried.
- **Idempotency belongs to stats-service.** Identical bytes deduplicate within their workspace;
  different bytes under the same filename create different jobs. Reuploading identical bytes
  preserves the existing job's outcome and retry budget; an administrator explicitly retries
  failed or awaiting-link jobs. Filenames and tournament ids never identify a result; the message ids
  it echoes do.
- **History rescan cost.** A (re)connect costs only what each channel missed since its cursor (at
  most 500 messages per channel, all channels concurrently); an admin backfill walks the last 500.
  Each attachment costs one Discord CDN download through the proxy.
- **Two HTTP clients, neither to a service.** `AttachmentClientFactory`
  (`services/attachment_client.py`) fetches a log from Discord's CDN through the egress proxy; the
  bytes reach stats-service over RabbitMQ (`UploadMatchLogEvent`). `src/render` fetches a lineup
  picture's map art and rank badges directly (3 s timeout, an in-process TTL cache of an hour; a
  picture that fails to load is left out of the drawing, the post still goes).

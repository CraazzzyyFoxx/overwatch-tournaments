# Deadlock mixes: lobby bot, ingest status and import hints: release note

A Deadlock private-lobby match gets statistics from deadlock-api only once the match's salts are known, and salts reach
deadlock-api from the players' desktop (`deadlock-api-ingest`), never from a browser. The site now helps a mix get
there: a host can create the lobby through deadlock-api's bot, every seat shows whether its player's ingest is active,
and the import window says why a search is still waiting. Hints and links
(<https://deadlock-api.com/ingest-cache>, the Windows installer) sit in the mix room, the player's seat panel, the
import window, account settings next to the Steam link and the docs (`organizers/mixes`, `players/stats`).

**Bot lobby.** On the live stage of a lobby (`live_encounter_id` set) the host creates the in-game party with
deadlock-api's bot: `POST /api/v1/balancer/workspaces/{workspace_id}/custom-games/{game_id}/bot-lobby`
(`{"lobby_index", "region"}`, `AuthRequired`, the gateway's default long deadline because the worker waits on
deadlock-api) → `rpc.balancer.custom.create_bot_lobby`, same audience as `set_lobby_code`, answers the mix read
payload and emits `pickup_mix_changed(change="bot_lobby")`.
- Calls `POST /v1/matches/custom/create`: `is_publicly_visible`, `cheats_enabled`, `duplicate_heroes_enabled` and
  `randomize_lanes` false, `min_roster_size` = seated players, `game_mode` `street_brawl` for 4 per team else `normal`.
  The party code goes into `mix.lobby.lobby_code`.
- The bot joins as a spectator and leaves 15 minutes after creation whatever the match state; recreating for the same
  encounter replaces the party (new token, new code).
- Region is remembered per host per discipline in `balancer.user_config` (default `europe`); read as
  `bot_lobby_region` on the mix payload.
- Errors: 409 `no_live_match`, 422 `unsupported_lobby_bot`, 422 `invalid_region`, 429 `lobby_bot_rate_limited:<seconds>`
  (`details.retry_after` and the `Retry-After` header carry the same seconds; the plain slug when deadlock-api names
  none; deadlock-api allows 10 creations per hour per IP, 100 per 30 min per key), 503 `lobby_bot_failed`
  (deadlock-api unreachable or refusing; not 502).
- Each mix lobby entry gains `bot_lobby` (`party_code`, `created_at`, `expires_at`, `match_id`) for the lobby's current
  live encounter only; the token and the callback secret never leave the server. `GET
  /api/v1/balancer/custom-games/{custom_game_id}` is `AuthOptional` with `NoWorkspaceFill`, so `bot_lobby_region`
  resolves for the viewer (null anonymously) instead of being scoped to a credential's sole workspace.

**Match id.** Two paths, whichever lands first:
- Callback: `POST /api/v1/lobby-bot/callback/{token}` (game-neutral: the token names the party), `AuthNone`, served by a dedicated gateway handler
  (not the JSON dispatcher) that relays the raw body (16 KiB cap, 413 above) and `X-Callback-Secret` to
  `rpc.balancer.custom.bot_lobby_callback`. `POST …/callback/{token}/settings` is acknowledged with 204 at the
  gateway and never reaches the worker. The token is one-time and stored as SHA-256; the secret is compared with
  `hmac.compare_digest` when deadlock-api sent one. An unknown, answered or expired token, a wrong secret or a body
  without a match id answers 204 like a good one (no oracle). The body format is not documented by deadlock-api, so
  it is parsed defensively: number, string, `{"match_id"}` or digits.
- Poll: a balancer poller (60 s, Redis leader lock) asks `GET /v1/matches/custom/{party_id}/match-id` for rows younger
  than 20 min with no match id. It needs no public URL. The create call sends `callback_url` only when
  `PUBLIC_SITE_URL` is not localhost, so a dev stack relies on the poller alone.
**Filing.** The stats match-search tick, for a recorded round whose encounter has a bot-lobby match id
(`mix.bot_lobby.match_id`), files that id directly (`submit_fetch`, no requester, `found`) instead of searching by
players, so no player needs a linked account. A round that already has statistics or a filed id ignores the bot's id
(logged).

**Ingest status.** `GET /api/v1/balancer/workspaces/{workspace_id}/custom-games/{game_id}/ingest-status`
(`AuthRequired`: anonymous gets 401; 30 s gateway deadline) → `rpc.balancer.custom.ingest_status`:
`{"window_days": 14, "players": {"<player_id>": {"active", "last_upload_at"} | null}}`
from deadlock-api `GET /v1/players/{account_id}/ingest-status`, cached in Redis for 15 min per account (an unknown
answer is not cached). A player with no linked account, or a deadlock-api error, gives `null` (unknown), never
"inactive". Account ids stay on the server. 422 `unsupported_ingest_status` for other games. deadlock-api calls that
endpoint internal: its contract may change.

**Module hooks.** `DisciplineSpec.lobby_bot` and `DisciplineSpec.ingest_status`; Deadlock implements them in
`shared/disciplines/deadlock/lobby.py` and `ingest_status.py`. Discipline descriptor: `capabilities.lobby_bot`,
`capabilities.ingest_status`, `lobby_bot: {regions, default_region} | null`. `DisciplineSpec.ingest_client` names
where a player gets the uploader (`ingest_client: {instructions_url, installer_url} | null` on the descriptor); the
frontend hints render only those links, so no game's URLs live in core.

**History wire.** `rpc.balancer.custom.match_history` rows: `match_search_error` is also set while `match_search` is
`searching` (`no_match_yet` or `source_unavailable`), and `match_search_next_attempt_at` says when the next attempt
runs. The import window translates both.

**Rate limits.** Without `DEADLOCK_API_KEY` deadlock-api fetches a missing match for 3 requests an hour per IP (300 with
a key), so an import can take up to an hour to arrive; the import window shows the next attempt.

## Configuration

| Env | Service | Needed | Effect |
| --- | --- | --- | --- |
| `DEADLOCK_API_KEY` | `balancer.env` and `stats.env` | optional, recommended | Sent as `X-API-KEY` on every deadlock-api call (lobby create, match-id poll, ingest status; the stats fetch). Unset = the public per-IP limits, which a mix-heavy site exhausts quickly. The balancer reads it from its own environment, so set it in both files |
| `PUBLIC_SITE_URL` | balancer-service (via `common.env`; the production compose sets it from `SITE_URL`) | required for the callback | Must be the public origin deadlock-api can reach (`https://…`). Left at `http://localhost:3000` (or any localhost host) the create call omits `callback_url` and only the poller finds the match id |

## Migration and deploy

Revision `botlobby01` (down revision `stagepts02`) creates `mix.bot_lobby` (unique per encounter, unique token hash,
`ON DELETE CASCADE` from `encounter.encounter`, the workspace and the mix) and adds
`balancer.user_config.bot_lobby_regions` (JSONB, default `{}`: the remembered region per discipline). Pure expand.
Deploy from one SHA:
1. Set `PUBLIC_SITE_URL` to the public origin and, optionally, `DEADLOCK_API_KEY` in `balancer.env` and `stats.env`.
2. Run the migration (`botlobby01`).
3. Roll balancer-service (with the poller), stats-service, app-service (capabilities).
4. Roll the gateway (new routes and the callback handler, regenerated `schemas.json`) and the frontend (regenerated
   `api.generated.ts`). The gateway goes after the balancer: its new routes answer only once a worker consumes the
   queues.

### Downgrade cost

Downgrade drops `mix.bot_lobby` and `balancer.user_config.bot_lobby_regions`. Matches already filed stay; a bot lobby's
pending match id is lost, and the host files it by hand; hosts' remembered regions reset to the default.

## Wire changes

| Change | Kind |
| --- | --- |
| `POST …/custom-games/{game_id}/bot-lobby` (`AuthRequired`) | additive |
| `GET …/custom-games/{game_id}/ingest-status` (`AuthRequired`) | additive |
| `POST /api/v1/lobby-bot/callback/{token}` (`AuthNone`, 204) and `…/settings` (204 at the gateway) | additive, public |
| Mix payload `bot_lobby` per lobby, `bot_lobby_region` | additive |
| Discipline `capabilities.lobby_bot`, `capabilities.ingest_status`, `lobby_bot` | additive |
| Discipline descriptor `ingest_client` (`instructions_url`, `installer_url` or null): the links the hints show | additive |
| Match history `match_search_error` while searching, `match_search_next_attempt_at` | additive / changed meaning |

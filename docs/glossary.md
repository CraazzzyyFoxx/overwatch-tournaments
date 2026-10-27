# Glossary

Domain vocabulary used across the database, the RPC surface, and the UI. Terms are defined by
where they live in the system, not by how Overwatch uses them.

For the identity model in depth see [`users-identity.md`](./users-identity.md); for tables and
columns see [`database_erd.md`](./database_erd.md); for the Russian UI renderings of the
player-facing subset see [`../frontend/src/i18n/GLOSSARY.md`](../frontend/src/i18n/GLOSSARY.md).

## Tenancy and identity

| Term | Meaning |
| --- | --- |
| **Workspace** | The tenant root, `public.workspace`. An organizer's isolated world: branding, domain, members, tournaments, ranks, achievements. Nearly every business row carries `workspace_id`, directly or through `tournament` / `workspace_member`. |
| **Custom domain / subdomain** | How a request is resolved to a workspace. The host is matched against a workspace subdomain or a verified custom domain in `backend/shared/tenancy/hostnames.py`. |
| **Login account** | `auth.user` — credentials, sessions, OAuth connections, API keys. Owned by `identity-service`. |
| **Player** | `players.user` — the domain person: game-provider handles, statistics, match history. Owned by `app-service`. Distinct from the login account and linked to it, at most 1:1, through `auth_user_id`. |
| **Virtual player** | A `players.user` whose `auth_user_id` is `NULL`: a person the platform knows from parsed match logs or a CSV import who has never signed in. Called a *shadow player* in some older code and documents. |
| **Identity provider** | The social provider whose handle identifies a player of a game, declared by its module: `battlenet` for Overwatch, `riot` for LoL and VALORANT, `steam` for Deadlock. Riot IDs use `Name#TAG`; inner name spaces are preserved. A Steam handle is the decimal SteamID3 account id, whatever spelling was entered (SteamID64, `[U:1:N]`, `STEAM_X:Y:Z`, a `/profiles/` link). This game identity is distinct from the login account. |
| **Workspace member** | `public.workspace_member`, unique per `workspace_id` + `player_id`. The anchor every workspace-scoped domain object hangs off: roster entries, registrations, drafts, achievements, ranks. |
| **RBAC** | Grant-only permission catalog plus workspace system roles, with a `user_permission_deny` overlay that can subtract. Bootstrapped from `backend/shared/rbac/`. |
| **Entitlement / subscription requirement** | A condition on registration or check-in — a Discord role or a Twitch subscription — evaluated by the admission layer before a player is allowed through. |

## Tournament structure

| Term | Meaning |
| --- | --- |
| **Tournament** | The top-level competitive event inside a workspace. Owns its lifecycle state machine, registration, stages, and standings. |
| **Phase** | Where a tournament is in its lifecycle: announcement, registration, check-in, draft, live, finished. Drives what the public page and the admin surfaces offer. A tournament starts announced — public and readable, with nothing to do until its registration window opens. |
| **Stage** | One competitive segment of a tournament — a group stage or a playoff. Not to be confused with *phase*, which is lifecycle, not competition. |
| **Stage item / stage item input** | The current bracket model: a stage decomposes into items (a group, a bracket round), and items declare their inputs. `group` is the legacy model kept for historical tournaments. |
| **Group stage / round-robin / Swiss** | Stage formats. Round-robin plays every pairing; Swiss pairs by current score for a fixed number of rounds. |
| **Bracket** | The elimination tree, single or double. |
| **Discipline** | The game a tournament, mix and every encounter under it is played in: `catalog.discipline.code`, currently `overwatch`, `lol`, `deadlock` and `valorant`. Copied onto each encounter from its owner and never changed. Behaviour lives in a module under `backend/shared/disciplines/<slug>/`, reached only through the registry `shared.disciplines`: kinds and their labels, character classes, catalog sync source, sides where declared, role ontology, team-format presets, `native_ranks`, `native_ladder`, `identity_provider` and `match_fetchers`. These contracts do not by themselves complete the LoL, Deadlock or VALORANT gameplay vertical. |
| **Encounter** | One meeting of N participants, `encounter.encounter` — the root of the game-neutral match layer. A best-of duel is an encounter with `slot_count = 2`, an FFA lobby (not the *Mix lobby* below) one with `slot_count = N`; there is no `format` column and no home or away side. Its bracket position (stage, stage item, round) lives in `tournament.bracket_encounter`, not on the encounter. |
| **Encounter owner** | What an encounter belongs to: exactly one of `tournament_id` (a tournament round) or `custom_game_id` (a pickup mix round), enforced by `ck_encounter_owner`. Tournament code reads tournament-owned encounters only; the owner key also carries the workspace and discipline, so the copies cannot disagree with the owner. |
| **Mix round** | One recorded round of a pickup mix: an `encounter.encounter` owned by `mix.custom_game` (`custom_game_id`, no tournament), Bo1, result source `host`. The balancer facts of it live in `mix.round`; who sat where is the participation roster (`encounter.team_member`). |
| **Mix round member** | `mix.round_member`: a workspace member's balancer fact in one mix round — seated, with the rank delta frozen at record time, or busy in another lobby of the same mix. |
| **Participation** | One team's seat in one encounter, `encounter.team`. Append-only: replacing the occupant writes a new row and sets the old one `active = false`; the participation writer never reactivates or deletes a retired row (only deleting the encounter itself removes it), so the games, claims and journal entries that point at it still answer "who played this". `team_id` is the source tournament team and goes `NULL` if that team is deleted; `name` is the snapshot that survives it. Written only by `shared/services/encounter/participants.py`. |
| **Slot** (encounter) | The numbered seat a participation occupies, `1..slot_count`. Slot numbers replace home/away. Not the roster slot or the map-veto slot defined under *Rosters, registration, balancing*. |
| **Participation roster** | `encounter.team_member`: the snapshot of who was on a participation — workspace member, display name, rank, substitute flag — with leaf assignments in `team_member_role (team_member_id, dimension_id, role_id)`. Taken when the seat is filled; later roster edits do not rewrite it. |
| **Scoring rule** | `encounter.scoring_rule`: the preset (`wins` or `points`), the organizer's score columns, placement points, and two formulas — `game_formula` pays one game, `end_formula` says when the encounter is over. A duel series is the `wins` preset; an FFA lobby is `points`. Evaluated only by `backend/shared/domain/encounter_scoring.py`, through the formula engine, never `eval`. |
| **Encounter link** | An explicit advancement edge: the team that finished in position *k* of one encounter fills a numbered slot of another, `tournament.encounter_link`. The bracket is these edges, not an implied tree shape. |
| **Encounter game** | One position in the series, `encounter.game`. Owns the map, the mode played (`mode_id`: the map's catalog parent when that parent is a mode, else what an accepted log observed) and the accepted result: `state` (`planned`, `awaiting_result`, `disputed`, `confirmed`, `cancelled`), `result_source` (`captain_agreement`, `admin`, `admin_log`) and a `result_version`. Each participation's numbers, side and replay code are a row of `encounter.game_team`. A cancelled game keeps its position as history and is never reactivated; replaying a position creates a new game. A game — not a `Match` — is the unit of result authority. |
| **Game claim** | One participation's claim about one game, `encounter.game_claim` plus one `game_claim_result` row per participation, at most one claim per game per claimant. Matching claims confirm the game with `result_source = captain_agreement`; conflicting claims put it in `disputed` for an admin. `basis_version` is the game's `result_version` the claim was made against, so a claim filed against a superseded result is stale. A claim against a confirmed game is rejected (`result_locked`); changing that result is the admin correction command, which requires a reason. |
| **Series report** | One participation's report of the whole encounter, `encounter.team_report` plus a `team_report_result` row per participation (score, placement, wins), with `games_played`, closeness and the organizer's custom fields. A participation may re-file until the result is confirmed; once every live participation has reported and the reports agree, the encounter's result becomes a `series_claim`, and reports that disagree put it in `disputed` for an admin. After `confirmed`, a report is rejected (`result_locked`). |
| **Result source** | Whose result stands on an encounter, `encounter.result_source`: `games` (the aggregate of the confirmed games), `series_claim`, `admin`, `import` (Challonge), or `host` (a mix round the host recorded). `NULL` while no official result exists. Only `games` is overwritten by game changes or a rule recalculation; the other four are decisions and only a reopen removes them. |
| **Result version** | `encounter.result_version`: bumped by every result change — a confirmation, a reopen, and a report-driven move to `pending_confirmation` or `disputed` alike — each of which runs in one transaction with the encounter row locked `FOR UPDATE` and writes exactly one `encounter.result_audit` row. Reports and claims carry the version they were based on. Written only by `shared/services/encounter/result.py`. |
| **Match** | Parsed observations for one `encounter.game`, stored in `stats.match` with workspace/discipline ownership. It carries statistics, not the official result, and its own mode (`mode_entity_id`: the document's `mode`, else the map's catalog parent). Public duel fields follow historical encounter slots; `stats.match_team.source_position` separately preserves decoder order. Game position, not an inferred map index, orders the series. |
| **Standings** | The computed table for a stage: points, tiebreakers (Buchholz, head-to-head), placement. |
| **Seed / seeding** | A team's ordering going into a stage; also the input to first-ban rules in map veto. |

## Rosters, registration, balancing

| Term | Meaning |
| --- | --- |
| **Role dimension** | An axis of a game's roles — OW `player_role`, LoL `position`, Deadlock and VALORANT `agent` (one role: ranks are per player, not per position). Its cardinality is `single` or `multi`; exactly one dimension per discipline is `rated`. |
| **Role** | A `catalog.role` row: the module's roles, plus workspace sub-roles under them. An assignment is one leaf, its parent derived (D86); workspace sub-role codes are `<parent>_<slug>`, for example `support_main`. |
| **Role ref** | A role on the wire: `{dimension, role, parent}` codes. `role` is the leaf, `parent` is derived output (`null` for a module role) and ignored on input. |
| **Team format** | An owner's roster rules: starter/substitute sizes, dimension modes and role quotas. A tournament and a mix own a copy of a workspace default or module preset; later template edits do not change it. |
| **Open slot** | A slot without a role constraint — `flex` in slot maps and solver documents; not a role. `is_flex` (Full Flex) is a separate player attribute. |
| **Registration** | A player's or team's application to a tournament, with roles, top heroes, and status. Optionally imported from Google Sheets. |
| **Check-in** | Confirmation, inside a time window, that a registered participant will actually play. |
| **Roster** | The players assigned to a team. Each roster entry points at a `workspace_member`, not at a bare player. |
| **Roster shape** | The rated-dimension slot projection of a team format — e.g. `{tank: 1, damage: 2, support: 2}` or six open (`flex`) slots. Resolved server-side; `RosterShapeRead` carries `dimension` and a `tournament`, `custom_game`, `workspace` or `preset` source. `team_size` and `draft_rounds` are derived server-side, never recomputed on the client. |
| **Slot** | One position in a roster shape (a role slot or a flex slot). In map veto, a slot is instead one map of a series. |
| **Substitute** | A roster member who replaces another; substitution chains are rendered under the player they replace. |
| **Balancer** | The team-building solver: a multi-objective genetic search implemented in the native Rust `tournament_balancer` crate and driven by `balancer-service`. |
| **Mix lobby** | One of the (at most six) matches a pickup mix runs at once — `mix.lobby`, keyed `(custom_game_id, lobby_index)`. Owns that match's balance document, pager position, next map and `balanced_at`; the mix itself owns none of them. Rendered as «лобби A … F» in the Russian UI. Membership is derived from the lobby's selected variant, never stored; only the host's `lobby_pin` is. |
| **Draft** | The live alternative to the balancer: captains pick players in a snake order, server-authoritative clock, optimistic concurrency on `version`. |
| **Rank layer** | Where a player's rank number came from: registration or author override, then workspace canon, then the module's native rank. Stored ranks are scoped to the discipline's rated module roles by `role_id`; the workspace and author books are never merged. The effective source on the wire is `native`, not `ow`. |
| **Native ladder** | A game's own rank ladder declared by its module: Overwatch has 45 tiers, LoL 31 (league-v4 Iron IV … Challenger), Deadlock 66 (Initiate 1 … Eternus 6), VALORANT 25 (Iron 1 … Radiant). It is not a workspace's organizer-defined division grid; a game with one seeds new grids from it and falls back to it when it has no grid. |
| **Native rank** | A player's rank on that ladder, read through the module's `native_ranks` hook and normalized to the owning grid; the resolver's last layer. A discipline without that hook never reads another game's snapshots. |
| **Mix ranker** | The host-selectable alternative to flat points per win (`user_config.rating_mode = ranker`): each member keeps a hidden OpenSkill rating per catalog role of the discipline's rated dimension next to the open rank. Open slots (`flex`) hold no hidden rating and move no host book. Idea and specification: [mixtura-ranker](https://github.com/mixtura-dev/mixtura-ranker) by Dmitriy (@dmelackov); implemented in `balancer-service/src/domain/mix_ranker.py`. |
| **Open / hidden / effective rating** | Mix ranker terms. *Open* — the rank in the host's book, set by people. *Hidden* — the statistical `(mu, sigma)` per workspace member and catalog `role_id`, derived from mix history. *Effective* — the open rating corrected towards the hidden one; what a ranker host's mixes are balanced on. |
| **Division** | An organizer-defined rank band in a versioned division grid. Version mappings keep ranks comparable across seasons. |
| **Division grid** | A workspace or system grid belonging to one discipline. Tiers hold internal `rank_min/max` and optional `native_rank_min/max`. Every workspace gets its own grid of each enabled game with a native ladder (v1 = that ladder), made the game's default unless a default exists or a system grid of the game is in force; only a game new to the workspace with no tournaments of it moves off a system grid. A new grid starts from the native ladder or a published copy of a chosen version, and never activates itself. Workspace defaults are independent per discipline; an event can pin a matching version. A game without a native ladder needs a tiered grid of its own before its first event. |

## Maps, heroes, statistics

| Term | Meaning |
| --- | --- |
| **Catalog entity** | A character, map or mode of one discipline in `catalog.entity`; a map's parent (`parent_id`) is the mode it belongs to, if any, and a character's class is `attrs.class`. A played match's mode is its own (`stats.match.mode_entity_id`, `encounter.game.mode_id`), never read from the map: one map can host several modes (Deadlock's Midtown). |
| **Kind** | The core's catalog vocabulary: `character` / `map` / `mode`. A module declares which kinds it has and only labels them — for example, "Hero" or "Champion" for `character`. |
| **Map pool** | The set of maps available to a stage or round. A game that declares the `mode` kind may also name modes in the shared pool: a match of another mode is refused (`mode_not_in_pool`), and rooms veto the maps only. |
| **Map veto / pick-ban** | The pick and ban sequence that reduces a pool to the maps actually played, driven by a `map_veto_config`. |
| **Reserve map** | The map held back for a tie. |
| **Match log** | An Overwatch log file uploaded by an organizer or through the Discord bot, parsed by `stats-service` into matches, per-round statistics, kill feed, and assists. |
| **Ingest job** | `stats.ingest_job`: actual content hash, exact stored raw reference, optional binding hints and parse lifecycle. `awaiting_link` means valid input still lacks an accepted game binding (no unique game proven by the participants' rosters); it is not a completed match and wrote nothing. An administrator binds it with a complete team map, or replays a `done` job with an explicit reparse that names the observation revision seen. |
| **Canonical match document** | The strict `owt.match/1` JSON a producer posts to `POST /api/v1/stats/matches` (OpenAPI `stats.MatchDoc`). Idempotent per `(workspace, source.kind, external_id)`, else per byte hash; a corrected document uses a new `external_id`. |
| **Match import** | A tournament game's match requested by its external id (a Deadlock match id) instead of an uploaded file: one `stats.match_fetch` row per `(source kind, external id, game)`, retried by `stats-worker` through the module's `match_fetchers` entry until the match is served or 24 h pass, then stored and ingested exactly like an upload. |
| **Ingest evidence** | The `match.ingested` event a stored observation revision publishes. The match layer answers with one `match_ingested` journal receipt (`accepted`, `logs_disabled`, `result_locked`, …); only a tournament with `logs_official` can take it, and an organizer's own result always wins. |
| **Observation anchor** | A workspace member row created by ingestion for a person the workspace does not know (`observed_only`): never a membership, visibility or role until a real admission. |
| **Stat fact / event** | `stats.fact` stores numeric observations at their native member/team/entity/segment grain using discipline-qualified stat definitions. `stats.event` preserves event order, duplicates and nullable endpoints using discipline-qualified event types. |
| **Cutover receipt** | Immutable complete owner-state proof captured with writers drained. Later native changes require validated before/after audit chains and release review; unexplained changes block legacy deletion. |
| **Playtime** | Time a player spent on a hero, reported as a share of the match. |
| **MVP impact** | The scoring model that ranks a player's contribution within a match; the basis of MVP achievements. |
| **Achievement** | A declarative rule (a JSON condition tree) evaluated against match data, plus a manual grant/revoke overlay. |
| **Rank snapshot** | A point-in-time native rank of a linked game account in `rank.rank_snapshot` (one `discipline` per row): Overwatch per role from OverFast for a BattleTag, League of Legends per queue (Solo/Duo, Flex) from the Riot API for a Riot ID, Deadlock one series per Steam account from deadlock-api; the series behind rank history. |

## Platform mechanics

| Term | Meaning |
| --- | --- |
| **Gateway** | The Go process at `gateway/`. The only thing in the system that speaks HTTP and WebSocket to the outside. |
| **RPC worker** | A Python FastStream service. It exposes no HTTP; the gateway calls it as `rpc.<service>.<method>` over RabbitMQ, request/reply, under an `x-deadline-ms` budget. |
| **Envelope** | The `{ok, data, error}` shape every RPC reply uses. |
| **Outbox** | `event_outbox`. A state change writes its domain event in the same transaction as the change; a sweeper drains the table and publishes, so an event can never be lost or emitted for a rolled-back write. |
| **Realtime topic** | A named channel a client can subscribe to over WebSocket — `tournament:{id}:bracket`, `encounter:{id}:map-veto`, and so on. Access is checked per topic. |
| **Replay** | Redelivery of missed realtime events after a reconnect, from `realtime.workspace_event`. Non-durable topics have no event row and therefore no replay. |
| **Response cache** | The gateway's in-process cache of anonymous public reads, 30 s TTL, invalidated by the workers over Redis pub/sub. Live draft reads are scoped to their draft session instead: 5 s TTL, dropped by any frame on the session's board or chat topic. |

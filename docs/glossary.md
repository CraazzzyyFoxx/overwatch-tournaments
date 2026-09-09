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
| **Player** | `players.user` — the domain person: BattleTag, statistics, match history. Owned by `app-service`. Distinct from the login account and linked to it, at most 1:1, through `auth_user_id`. |
| **Virtual player** | A `players.user` whose `auth_user_id` is `NULL`: a person the platform knows from parsed match logs or a CSV import who has never signed in. Called a *shadow player* in some older code and documents. |
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
| **Encounter** | One meeting between two teams — the best-of series, `tournament.encounter`. |
| **Encounter link** | An explicit advancement edge: the winner (or loser) of one encounter feeds a named slot of another. The bracket is these edges, not an implied tree shape. |
| **Match** | One played map inside an encounter, `matches.match`. An encounter of best-of-3 has up to three matches. |
| **Standings** | The computed table for a stage: points, tiebreakers (Buchholz, head-to-head), placement. |
| **Seed / seeding** | A team's ordering going into a stage; also the input to first-ban rules in map veto. |

## Rosters, registration, balancing

| Term | Meaning |
| --- | --- |
| **Registration** | A player's or team's application to a tournament, with roles, top heroes, and status. Optionally imported from Google Sheets. |
| **Check-in** | Confirmation, inside a time window, that a registered participant will actually play. |
| **Roster** | The players assigned to a team. Each roster entry points at a `workspace_member`, not at a bare player. |
| **Roster shape** | How many slots a team has and which roles they ask for — e.g. `{tank: 1, dps: 2, support: 2}` or six flex slots. Resolved server-side in `backend/shared/domain/roster_shape.py` and sent to the client already resolved; `team_size` and `draft_rounds` are derived from it there and never recomputed on the client. |
| **Slot** | One position in a roster shape (a role slot or a flex slot). In map veto, a slot is instead one map of a series. |
| **Substitute** | A roster member who replaces another; substitution chains are rendered under the player they replace. |
| **Balancer** | The team-building solver: a multi-objective genetic search implemented in the native Rust `moo_core` crate and driven by `balancer-service`. |
| **Draft** | The live alternative to the balancer: captains pick players in a snake order, server-authoritative clock, optimistic concurrency on `version`. |
| **Rank layer** | Where a player's rank number came from. A workspace has a shared canon; each ranking author additionally keeps their own book, and an author rank overrides canon for that author only. The two dictionaries are never merged. |
| **Division** | A rank band. `division_grid` versions the SR ranges and maps between versions so ranks stay comparable across seasons. |

## Maps, heroes, statistics

| Term | Meaning |
| --- | --- |
| **Map pool** | The set of maps available to a stage or round. |
| **Map veto / pick-ban** | The pick and ban sequence that reduces a pool to the maps actually played, driven by a `map_veto_config`. |
| **Reserve map** | The map held back for a tie. |
| **Match log** | An Overwatch log file uploaded by an organizer or through the Discord bot, parsed by `parser-service` into matches, per-round statistics, kill feed, and assists. |
| **Playtime** | Time a player spent on a hero, reported as a share of the match. |
| **MVP impact** | The scoring model that ranks a player's contribution within a match; the basis of MVP achievements. |
| **Achievement** | A declarative rule (a JSON condition tree) evaluated against match data, plus a manual grant/revoke overlay. |
| **Rank snapshot** | A point-in-time Overwatch rank fetched from OverFast for a linked BattleTag; the series behind rank history. |

## Platform mechanics

| Term | Meaning |
| --- | --- |
| **Gateway** | The Go process at `gateway/`. The only thing in the system that speaks HTTP and WebSocket to the outside. |
| **RPC worker** | A Python FastStream service. It exposes no HTTP; the gateway calls it as `rpc.<service>.<method>` over RabbitMQ, request/reply, under an `x-deadline-ms` budget. |
| **Envelope** | The `{ok, data, error}` shape every RPC reply uses. |
| **Outbox** | `event_outbox`. A state change writes its domain event in the same transaction as the change; a sweeper drains the table and publishes, so an event can never be lost or emitted for a rolled-back write. |
| **Realtime topic** | A named channel a client can subscribe to over WebSocket — `tournament:{id}:bracket`, `encounter:{id}:map-veto`, and so on. Access is checked per topic. |
| **Replay** | Redelivery of missed realtime events after a reconnect, from `realtime.workspace_event`. Non-durable topics have no event row and therefore no replay. |
| **Response cache** | The gateway's in-process cache of anonymous public reads, 30 s TTL, invalidated by the workers over Redis pub/sub. |

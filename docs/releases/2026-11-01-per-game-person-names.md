# Per-game person names: release note

A person used to be shown by `players.user.name` everywhere, which is usually an Overwatch-shaped `Name#1234`. A
Valorant roster showed BattleTags, Deadlock showed numeric SteamIDs, and the Riot `#TAG` was cut off together with every
other `#…`. Surfaces owned by one game now name a person in that game; cross-game surfaces keep the canonical name.
Rules: `docs/users-identity.md` §3.6.

## What shows where

- **One game's surfaces:** tournament rosters, teams, overview, participants, registrations, encounter pick-ban targets
  and mix pick-ban members, match pages (scoreboards, kill feed, breakdowns), tournament analytics standings, the
  lobby and character leaderboards, the statistics page with a game selected, drafts, and the mix
  roster/lobby/room/leaderboard. Shown name, first found: the workspace `display_name`, then the game handle (the
  game's identity provider's primary account visible in that workspace or globally; Steam shows the persona name, never
  the id), then the event's snapshot, then `players.user.name`. The `#tag` is muted, and hidden in drafts, dense cells
  and the encounter OG image. Hovering shows the canonical name, plus the name used at the event when it differs.
- **Cross-game surfaces stay canonical:** the profile header with "all games", teammates, achievements, the players
  index, platform leaders on the home page, favorites, and search results. With one game selected, the profile header
  adds a muted line with the person's handle in that game.
- **Admin:** roster, team and registration-team views show the game name with the canonical name beside it.
- **Links:** every profile link is built from the canonical name (`display.canonical`).
- **Search:** `users.search` also matches `social_account.display_name` (Steam personas) of publicly visible accounts.

## Wire changes

Each person row on those surfaces carries `display: PersonDisplayRead` (`name`, `tag`, `canonical`, `snapshot`; every
key is always present). These display-only fields were removed:

- `NativeMatchMember.player_name`
- `LobbyLeaderboardEntry.name`
- `CharacterLeaderboardEntry.username` and `player_name`
- `CharacterStatBest.player_name`
- `PlayerLeaderboardRow.name`
- `DraftPlayerRead.player_name`
- the pick-ban target's `name`

`StatRecord.player` is now `{id, display}`. Data fields (`name`, `primary_handle`, `identity`, `handle_snapshot`) are
unchanged.

The cache keys of every changed read moved to a new version, so no payload missing `display` is served: `teams:v4`,
`registration_list:v3`, `native_encounters:v6`, `native_encounters_overview:v6`, `native_encounters_insights:v3`,
`native_match_stats:v3`, `standings_by_tournament:v3`, `draft_board:v2`, `user_characters:v3`, `user_encounters:v9`,
`user_tournament_encounters:v9`.

Known limit: a changed social account, account visibility or workspace `display_name` reaches cached reads only when
their TTL expires or the tournament next writes, the same as other people's cosmetic data today. The Discord bot's
messages and images are unchanged.

## Migration and deploy

No migration. Deploy from one SHA: the backend services (tournament, stats, balancer, app, analytics), the gateway
(regenerated `schemas.json`) and the frontend (regenerated `api.generated.ts`). A frontend served before its backend
reads a missing `display` and breaks name rendering, so roll the backend and gateway first.

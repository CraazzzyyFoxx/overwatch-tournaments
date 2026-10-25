# Mix lobby code: the in-game join code on the board and the lineup card: release note

**The lobby code.** Each lobby of a mix can store the in-game lobby's join code (Deadlock's custom lobby, a LoL or
VALORANT party code), so players stop asking for it in chat. Every game has it and it is optional: a reader sees
nothing until the host sets one.
- **The host enters it.** The field is «Код лобби» on the lobby's desk (under the next map) and in the lobby's room
  (above the stage, in every phase). Saving trims it and keeps up to 64 characters. A blank field clears it.
- **Players read and copy it.** It shows on the desk, in the room and in «Ваше место» for a seated player, each with
  a copy button. The desk's screenshot carries it too.
- **In Discord.** The posted lineup card has a line «Код лобби: `…`» under the map line. A change re-renders the live
  card (`pickup_mix_changed`, change `lobby_code`).
- **Its lifetime.** It stays across matches until the host changes it, and the host can change it while the match is
  live (no `match_live`). A clone and a newly opened lobby start without one.
- **Visibility.** It is public like the rest of the lobby: anyone who can open the mix board sees it.

## Migration and deploy

One migration after `mixclock01`: **`mixcode01`**. It adds `mix.lobby.lobby_code`, a nullable `VARCHAR(64)` with no
default, so the ADD COLUMN is metadata-only. Deploy from one SHA: run the migration first, then roll
balancer-service, discord-service, the gateway (new route, regenerated `schemas.json`) and the frontend.

### Downgrade cost

Rolling back drops the column, so every stored code is lost.

## Wire changes

| Change | Kind |
| --- | --- |
| `PUT …/custom-games/{id}/lobby-code` (`rpc.balancer.custom.set_lobby_code`), body `{lobby_index, lobby_code}`: host or co-host; 422 over 64 characters, 404 `lobby_not_found` | additive |
| Mix read and list: each lobby carries `lobby_code` (null = none) | additive |
| `discord_view` lineups carry `lobby_code` | additive |

## Not in this release

The code in the bot's `/mix` seat panel, a DM to the lobby when it changes, a per-game switch to hide the field, and a
seated-players-only code.

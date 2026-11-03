# Tournament voice channels: release note

Organizers can have the Discord bot create voice channels for a tournament. Each team gets a voice channel, and
there is one shared hub that moves each participant into their own channel. An `individual_swiss` stage gets a pool of
round slots that is reused every round. Channels of eliminated teams are removed when the next stage is activated.
Everything is removed after the final. Team channels can be made private to the roster and staff roles. Substitutes
get access, and the players they replace keep it. Design and rules: `docs/tournament-voice-channels.md`.

## Where

The setting is in Admin → tournament → Settings → Discord → «Голосовые каналы». It is off for every tournament until
an organizer enables it.

## Wire changes

- New admin routes: `GET`/`PUT /api/v1/admin/tournaments/{id}/voice` and `POST /api/v1/admin/tournaments/{id}/voice/sync`.
  Their RPC subjects are `rpc.tournament.voice_get`, `rpc.tournament.voice_put` and `rpc.tournament.voice_sync`.
- New internal RPC: `rpc.tournament.voice_plan`, served by tournament-service and called by discord-service.
- New event: `tournament.voice.sync_requested` on `tournament.events`.
- New queues, owned by discord-service:
  - `discord_voice_sync`, bound to `tournament.events`;
  - `cache_invalidation_discord_voice`, bound to `cache.invalidation` with `cache.invalidated.tournament.#`;
  - a `.dlq` for each.
- `gateway/internal/openapi/schemas.json` and `frontend/src/types/api.generated.ts` are regenerated (additions only).

## Known limits

- Match notifications do not carry a link to the voice channel, despite the agreed design. Individual Swiss
  encounters are not notified at all today, and the notification payload is shared by every recipient. Players
  reach their channel through the hub.
- The bot keeps routes in process memory. After a restart nobody is moved until the routes change again; the hub
  works again after the startup sync.
- If the bot crashes between creating a channel and saving its row, that channel is orphaned and a duplicate is
  created.

## Migration and deploy

Migration `voice01` creates `tournament.voice_settings` and `tournament.voice_channel`. Deploy from one SHA in this
order: migration, tournament-service, gateway, discord-service (still a single replica), then the frontend. The bot
needs these permissions in the voice category: Manage Channels, Manage Roles, Move Members, View Channel and Connect.

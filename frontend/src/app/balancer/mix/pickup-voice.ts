import { ApiError } from "@/lib/api/error";
import type { CustomGame, MixVoiceOptions, MixVoicePatch } from "@/services/custom-game.service";
import type { DiscordVoicePermission } from "@/types/discord.types";

/** A mix still being played holds its voices; a finished one frees them. */
const ACTIVE: Record<string, true> = { draft: true, balanced: true };

export type BusyVoice = { gameName: string; lobbyIndex: number };

/** Team voices other open mixes of the workspace already picked; general voices are shared, never busy. */
export function busyVoices(games: CustomGame[], currentGameId: number): Map<string, BusyVoice> {
  const busy = new Map<string, BusyVoice>();
  for (const game of games) {
    if (game.id === currentGameId || ACTIVE[game.status] !== true) continue;
    for (const lobby of game.lobbies) {
      for (const id of [lobby.team1_voice_channel_id, lobby.team2_voice_channel_id]) {
        if (id) busy.set(id, { gameName: game.name, lobbyIndex: lobby.lobby_index });
      }
    }
  }
  return busy;
}

/** What the bot lacks on the category and on these voices: a non-empty answer disables moving. */
export function voiceBlocker(
  options: MixVoiceOptions | undefined,
  ids: (string | null)[],
): DiscordVoicePermission[] {
  if (!options) return [];
  const missing = new Set(options.category_missing_permissions ?? []);
  const channels = [...options.general, ...options.team];
  for (const id of ids) {
    for (const permission of channels.find((channel) => channel.id === id)?.missing_permissions ?? []) {
      missing.add(permission);
    }
  }
  return [...missing];
}

/** The mix's whole voice setup with one pick changed: the endpoint replaces it at once. */
export function voicePatch(
  game: CustomGame,
  change: { general?: string | null; lobbyIndex?: number; team?: 1 | 2; channelId?: string | null },
): MixVoicePatch {
  return {
    general_voice_channel_id:
      change.general !== undefined ? change.general : game.general_voice_channel_id,
    lobbies: game.lobbies.map((lobby) => {
      const mine = lobby.lobby_index === change.lobbyIndex;
      return {
        lobby_index: lobby.lobby_index,
        team1_voice_channel_id:
          mine && change.team === 1 ? (change.channelId ?? null) : lobby.team1_voice_channel_id,
        team2_voice_channel_id:
          mine && change.team === 2 ? (change.channelId ?? null) : lobby.team2_voice_channel_id,
      };
    }),
  };
}

export type MixVoiceRefusal =
  | "voice_not_configured"
  | "general_voice_not_configured"
  | "general_voice_outside_category"
  | "discord_unavailable";

/**
 * The four refusals a move or a return answers with. They are setup problems
 * the host fixes, not failures -- so the page says them in the reader's
 * language (`mixes.voice.errors.*`) instead of showing the server's slug.
 */
const REFUSALS: Record<MixVoiceRefusal, true> = {
  voice_not_configured: true,
  general_voice_not_configured: true,
  general_voice_outside_category: true,
  discord_unavailable: true,
};

/**
 * Which refusal this error is, or `null` for anything else. The slug travels as
 * the detail string of a 409/503, which `parseApiError` carries as the message.
 */
export function voiceRefusal(error: unknown): MixVoiceRefusal | null {
  if (!(error instanceof ApiError)) return null;
  const hit = error.details.find((detail) => REFUSALS[detail.msg as MixVoiceRefusal] === true);
  return (hit?.msg as MixVoiceRefusal | undefined) ?? null;
}

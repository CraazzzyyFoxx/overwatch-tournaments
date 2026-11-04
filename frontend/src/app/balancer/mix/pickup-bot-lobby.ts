import { ApiError } from "@/lib/api/error";
import type { CustomGame, MixBotLobby } from "@/services/custom-game.service";
import type { DisciplineMetadata } from "@/types/discipline.types";

/** What the host's bot-lobby control needs: the regions on offer, where the choice starts and the write. */
export type BotLobbyOptions = {
  regions: readonly string[];
  defaultRegion: string;
  /** The host's remembered region for this game; wins over `defaultRegion` while the bot still serves it. */
  rememberedRegion: string | null;
  creating: boolean;
  onCreate: (region: string) => void;
};

/** The control for a writer of a game whose bot can open lobbies (`capabilities.lobby_bot`); `null` otherwise. */
export function botLobbyOptions(
  metadata: DisciplineMetadata | undefined,
  game: CustomGame | undefined,
  canWrite: boolean,
  creating: boolean,
  onCreate: (region: string) => void
): BotLobbyOptions | null {
  const bot = metadata?.discipline.capabilities.lobby_bot === true ? metadata.lobby_bot : null;
  if (!canWrite || bot == null) return null;
  return {
    regions: bot.regions,
    defaultRegion: bot.default_region,
    rememberedRegion: game?.bot_lobby_region ?? null,
    creating,
    onCreate
  };
}

/** The region the select starts on: the host's own pick, else their remembered one, else the game's default. */
export function initialRegion(options: BotLobbyOptions): string {
  return options.rememberedRegion != null && options.regions.includes(options.rememberedRegion)
    ? options.rememberedRegion
    : options.defaultRegion;
}

/** Whole minutes until the bot leaves, rounded up; `<= 0` once it has. `now` is epoch ms (the minute clock). */
export function botLobbyMinutesLeft(botLobby: MixBotLobby, now: number): number {
  return Math.ceil((Date.parse(botLobby.expires_at) - now) / 60_000);
}

export type BotLobbyRefusal =
  | { code: "lobby_bot_rate_limited"; minutes: number | null }
  | { code: "lobby_bot_failed" | "no_live_match" };

const REFUSAL_CODES = ["lobby_bot_rate_limited", "lobby_bot_failed", "no_live_match"] as const;

/**
 * Which refusal of the create route this error is, or `null` for anything else. The slug travels as the detail string
 * (`msg`) -- for a rate limit as `lobby_bot_rate_limited:<seconds>` -- or as `code`; `retry_after` in the body wins.
 */
export function botLobbyRefusal(error: unknown): BotLobbyRefusal | null {
  if (!(error instanceof ApiError)) return null;
  for (const detail of error.details) {
    const code = REFUSAL_CODES.find((known) => detail.code === known || detail.msg.startsWith(known));
    if (code == null) continue;
    if (code !== "lobby_bot_rate_limited") return { code };
    const retryAfter = (error.body as { retry_after?: unknown } | undefined)?.retry_after;
    const seconds =
      typeof retryAfter === "number" ? retryAfter : Number(/\d+/.exec(detail.msg.slice(code.length))?.[0] ?? NaN);
    return { code, minutes: Number.isFinite(seconds) ? Math.max(1, Math.ceil(seconds / 60)) : null };
  }
  return null;
}

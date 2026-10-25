/**
 * Tournament stream + link shapes.
 *
 * There is no OpenAPI type generation in this project — `src/types/*.types.ts`
 * are written by hand and kept in sync with the backend by eye. These mirror
 * `stream-service`'s `rpc.stream.tournament_streams` and
 * `rpc.stream.{tournament,encounter}_vods` responses and
 * `tournament.tournament_link`.
 */

export type StreamPlatform = "twitch" | "youtube" | "other";

/**
 * The team a streaming participant plays for in THIS tournament.
 *
 * Nullable for two ordinary reasons, not one: rosters may not exist yet (a
 * player streams during `check_in`, long before the balancer forms teams), and
 * an official broadcast has no team at all. Both read as "no team caption".
 *
 * `id` is load-bearing beyond display: it is the join key the bracket uses to
 * mark which slots have someone on air, so it must be the tournament team id
 * that `EncounterTeam.team_id` carries.
 */
interface StreamTeam {
  id: number;
  name: string;
}

/** The player behind a participant stream. `null` for an official broadcast. */
interface StreamStreamer {
  id: number;
  name: string;
  avatar_url: string | null;
  team: StreamTeam | null;
}

export interface StreamEntry {
  platform: StreamPlatform;
  /** Twitch login, or a human-readable channel identifier on other platforms. */
  channel: string;
  url: string;
  /**
   * Tri-state on purpose.
   *
   * `true`/`false` — the poller has live detection for this platform (Twitch)
   * and reports the current state. `null` — there IS no live detection for the
   * platform (YouTube/other), so liveness is UNKNOWN. `null` is NOT `false`:
   * an unknown channel must not render an "offline" badge, it renders no badge
   * at all (see `STREAM_STATUS_META` in `@/lib/social/stream-platform`).
   */
  live: boolean | null;
  title: string | null;
  game_name: string | null;
  viewer_count: number | null;
  /** Already sized (440x248) by the backend — no `{width}x{height}` placeholders. */
  thumbnail_url: string | null;
  /** ISO8601. */
  started_at: string | null;
  player: StreamStreamer | null;
}

export interface TournamentStreams {
  /**
   * Official broadcast links, live or not — the link itself is always worth
   * showing.
   */
  official: StreamEntry[];
  /** Participant streams — only the ones currently live. */
  participants: StreamEntry[];
}

/** A logged map, or — when no map of the encounter has a usable log — the series start. */
export type StreamChapterKind = "map" | "series";

/** Where in a past broadcast one of the streamer's team's matches begins. */
export interface StreamChapter {
  encounter_id: number;
  /** `encounter.encounter.name`, e.g. "Team A vs Team B". */
  encounter_name: string;
  kind: StreamChapterKind;
  /** The game's position in the series, when the log is bound to a game. */
  map_position: number | null;
  /** `null` for a series chapter. */
  map_name: string | null;
  /** Seconds into the VOD, the tournament's stream delay already applied. */
  offset_s: number;
}

/** A participant's past POV broadcast whose Twitch VOD still exists. */
export interface StreamVod {
  /** Twitch video id, without the "v" prefix the player wants. */
  vod_id: string;
  url: string;
  channel: string;
  /** ISO8601, the stream start. */
  started_at: string;
  /** ISO8601, the last time the poller saw it live: the end, or about now while live. */
  ended_at: string;
  player: StreamStreamer;
  chapters: StreamChapter[];
}

/** Body of both VOD reads (tournament and encounter). */
export interface StreamVods {
  vods: StreamVod[];
}

/** Mirrors `TOURNAMENT_LINK_KINDS` in `backend/shared/models/tournament/link.py`. */
export type TournamentLinkKind =
  | "discord"
  | "stream"
  | "vod"
  | "bracket"
  | "rules"
  | "other";

export interface TournamentLink {
  id: number;
  tournament_id: number;
  kind: TournamentLinkKind;
  label: string | null;
  url: string;
  sort_order: number;
  is_active: boolean;
}

/**
 * Create/update payloads of `/api/v1/admin/tournament-links`.
 *
 * `id` is server-assigned and `tournament_id` is immutable once created, so the
 * update payload is a partial of the editable columns only.
 */
export interface TournamentLinkCreateInput {
  tournament_id: number;
  kind: TournamentLinkKind;
  label?: string | null;
  url: string;
  sort_order?: number;
}

export type TournamentLinkUpdateInput = Partial<
  Pick<TournamentLink, "kind" | "label" | "url" | "sort_order" | "is_active">
>;

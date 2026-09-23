import { getSocialProviderConfig } from "@/lib/social/providers";
import type { StreamEntry, StreamPlatform } from "@/types/stream.types";

/**
 * Platform detection + live-status presentation for stream entries.
 *
 * The backend already stamps `platform` on every entry; these helpers exist for
 * the cases where only a raw URL is in hand (an official `tournament_link` read
 * straight off the tournament, an admin form preview) and for keeping the
 * live/offline/unknown presentation in ONE registry.
 */

/**
 * Platform of a stream URL, by host. Unparseable or unknown hosts are `"other"`
 * rather than an error — a link the organiser typed is still worth rendering.
 */
function detectStreamPlatform(url: string): StreamPlatform {
  let hostname: string;
  try {
    hostname = new URL(url).hostname.toLowerCase().replace(/^www\./, "");
  } catch {
    return "other";
  }
  if (hostname === "twitch.tv" || hostname.endsWith(".twitch.tv")) {
    return "twitch";
  }
  if (
    hostname === "youtube.com" ||
    hostname.endsWith(".youtube.com") ||
    hostname === "youtu.be"
  ) {
    return "youtube";
  }
  return "other";
}

/**
 * Twitch login out of a channel URL, lowercased (Twitch logins are lowercase).
 * `null` for anything that is not a `twitch.tv/<login>` page — including the
 * ones that look like a channel but are not (`/videos/…`, `/directory/…`).
 */
function extractTwitchChannel(url: string): string | null {
  if (detectStreamPlatform(url) !== "twitch") {
    return null;
  }
  let pathname: string;
  try {
    pathname = new URL(url).pathname;
  } catch {
    return null;
  }
  const [first, ...rest] = pathname.split("/").filter(Boolean);
  // A channel page is exactly one segment. `/videos/123`, `/directory/game/x`
  // and `/<login>/clip/…` are not channels.
  if (!first || rest.length > 0) {
    return null;
  }
  const login = first.toLowerCase();
  return /^[a-z0-9_]{3,25}$/.test(login) ? login : null;
}

/**
 * Which of the three presentation buckets a `StreamEntry.live` value falls
 * into. `null` is its own bucket: the platform has no live detection, so the
 * state is UNKNOWN, not offline.
 */
export type StreamStatus = "live" | "offline" | "unknown";

/**
 * Typed as a union rather than `string` because `next-intl` messages are
 * strictly typed (`src/global.d.ts`) and `t()` rejects a widened key.
 */
type StreamStatusLabelKey = "stream.status.live" | "stream.status.offline";

type StreamStatusMeta = {
  /**
   * Pill copy, or `null` for NO pill at all. `unknown` renders nothing — a grey
   * "offline" badge on a YouTube link would assert a fact we do not have. The
   * rule lives here once instead of as a `live === null` ternary at each call
   * site, same reasoning as `TOURNAMENT_STATUS_META`.
   */
  labelKey: StreamStatusLabelKey | null;
  /** `.status-pill.{variant}` class from `globals.css` (scoped by `.aqt-tn`). */
  pillClassName: string;
  /** Whether the pill carries the animated `.dot`. */
  hasDot: boolean;
  /** Whether the player may be embedded for this state. */
  embeddable: boolean;
};

export const STREAM_STATUS_META: Record<StreamStatus, StreamStatusMeta> = {
  live: {
    labelKey: "stream.status.live",
    pillClassName: "status-pill live",
    hasDot: true,
    embeddable: true,
  },
  offline: {
    labelKey: "stream.status.offline",
    pillClassName: "status-pill finished",
    hasDot: false,
    embeddable: false,
  },
  unknown: {
    labelKey: null,
    pillClassName: "",
    hasDot: false,
    embeddable: false,
  },
};

export function getStreamStatus(live: boolean | null): StreamStatus {
  if (live === null) {
    return "unknown";
  }
  return live ? "live" : "offline";
}

/**
 * Stable identity of an entry across refetches.
 *
 * Platform + channel is what the poller dedupes on, so it survives a tick that
 * reorders the list — unlike an array index, which would re-key every consumer
 * as soon as one channel goes offline.
 */
export function streamEntryKey(entry: StreamEntry): string {
  return `${entry.platform}:${entry.channel}`;
}

/**
 * What to call this entry's platform in "Watch on …".
 *
 * A known provider is named from the shared catalog; anything else is named by
 * its host, because the catalog's fallback label for an unknown key would
 * render the literal word "Other" at a viewer who is looking for a site name.
 */
export function streamPlatformLabel(entry: StreamEntry): string {
  if (entry.platform !== "other") {
    return getSocialProviderConfig(entry.platform).label;
  }
  try {
    return new URL(entry.url).hostname.replace(/^www\./, "");
  } catch {
    return entry.channel;
  }
}

/**
 * The Twitch login this entry can be embedded with, or `null` when it cannot
 * carry a player at all.
 *
 * Embeddability is asked of `STREAM_STATUS_META` rather than re-derived from
 * `live === true`, so the rule stays in the one registry that also decides the
 * pill. The channel prefers what the poller stamped and falls back to the URL,
 * because an official link the organiser typed may be all there is (a
 * `tournament_link` row that no Helix response has matched yet carries the URL
 * but no login).
 */
export function embeddableTwitchChannel(entry: StreamEntry): string | null {
  if (!STREAM_STATUS_META[getStreamStatus(entry.live)].embeddable) {
    return null;
  }
  if (entry.platform !== "twitch") {
    return null;
  }
  return entry.channel.trim() || extractTwitchChannel(entry.url);
}

/**
 * Streams in the order the UI presents them: busiest first.
 *
 * The order is spelled out rather than left to whatever the read returned,
 * because these lists are refetched on every poller tick and the top entry
 * drives an iframe. A pick that moved with input order would tear down and
 * restart the player on each tick.
 *
 * A `null` `viewer_count` (the poller has not stamped one yet) sinks BELOW a
 * counted zero rather than outranking a channel with a real number, and ties
 * break on `channel`, which is unique per entry — so the order is total and
 * resolves identically tick after tick.
 */
export function sortStreamsByAudience(entries: readonly StreamEntry[]): StreamEntry[] {
  return [...entries].sort((a, b) => {
    const byViewers = (b.viewer_count ?? -1) - (a.viewer_count ?? -1);
    return byViewers !== 0 ? byViewers : a.channel.localeCompare(b.channel);
  });
}

/**
 * How long the channel has been on air, as `3h 12m` / `47m`, or `null` when
 * the poller has not stamped `started_at` (or stamped something unparseable).
 *
 * Coarser than `formatSeriesClock`: seconds on an uptime tick over would just
 * be a number that changes while you read it. Anything under a minute reads as
 * `0m` rather than `null` — the channel IS live, it just started.
 *
 * `now` is a parameter, and nullable, so the CALLER owns the clock: reading it
 * here would be impure in render and would render a server instant into HTML
 * that the client then disagrees with. `null` (see `useMinuteClock`) means "no
 * clock yet" and yields no duration at all. A future `started_at` — clock skew
 * between the poller and the browser — clamps to zero instead of rendering a
 * negative duration.
 */
export function formatStreamUptime(
  startedAt: string | null | undefined,
  units: { h: string; m: string },
  now: number | null
): string | null {
  if (!startedAt || now == null) {
    return null;
  }
  const start = Date.parse(startedAt);
  if (!Number.isFinite(start)) {
    return null;
  }
  const minutes = Math.max(0, Math.floor((now - start) / 60_000));
  const hours = Math.floor(minutes / 60);
  return hours > 0 ? `${hours}${units.h} ${minutes % 60}${units.m}` : `${minutes}${units.m}`;
}


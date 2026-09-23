// The two rules here both exist to keep an iframe alive.
//
// `sortStreamsByAudience` decides which channel the theater plays when the
// viewer has not picked one, and that list is refetched on every poller tick.
// If the order were partial — ties left to input order, `null` viewer counts
// landing wherever — the top entry could swap between two equally-watched
// channels on a tick and tear down a playing player. So the order has to be
// TOTAL, not merely "sorted by viewers".
//
// `formatStreamUptime` is the one figure on the card derived from the clock,
// and the clock is nullable by design (see `useMinuteClock`).
import { describe, expect, it } from "vitest";

import type { StreamEntry } from "@/types/stream.types";

import { formatStreamUptime, sortStreamsByAudience, streamEntryKey } from "./stream-platform";

function entry(overrides: Partial<StreamEntry> = {}): StreamEntry {
  return {
    platform: "twitch",
    channel: "somestreamer",
    url: "https://twitch.tv/somestreamer",
    live: true,
    title: null,
    game_name: null,
    viewer_count: 0,
    thumbnail_url: null,
    started_at: null,
    player: null,
    ...overrides
  };
}

const UNITS = { h: "h", m: "m" };

describe("sortStreamsByAudience", () => {
  it("puts the busiest channel first", () => {
    const sorted = sortStreamsByAudience([
      entry({ channel: "quiet", viewer_count: 3 }),
      entry({ channel: "busy", viewer_count: 418 }),
      entry({ channel: "middling", viewer_count: 15 })
    ]);

    expect(sorted.map((item) => item.channel)).toEqual(["busy", "middling", "quiet"]);
  });

  // A count the poller has not stamped yet is UNKNOWN, not zero. Ranking it
  // above a channel with a real, measured zero would let an unmeasured entry
  // take the frame.
  it("sinks an unstamped viewer count below a counted zero", () => {
    const sorted = sortStreamsByAudience([
      entry({ channel: "unstamped", viewer_count: null }),
      entry({ channel: "measured", viewer_count: 0 })
    ]);

    expect(sorted.map((item) => item.channel)).toEqual(["measured", "unstamped"]);
  });

  // The tie-break is what makes the order total: `channel` is unique per entry,
  // so two channels on the same count resolve the same way every tick.
  it("resolves equal counts identically whatever order they arrive in", () => {
    const a = entry({ channel: "alpha", viewer_count: 2 });
    const b = entry({ channel: "bravo", viewer_count: 2 });

    expect(sortStreamsByAudience([a, b]).map((item) => item.channel)).toEqual(["alpha", "bravo"]);
    expect(sortStreamsByAudience([b, a]).map((item) => item.channel)).toEqual(["alpha", "bravo"]);
  });

  it("leaves the caller's array alone", () => {
    const input = [entry({ channel: "quiet", viewer_count: 1 }), entry({ channel: "busy", viewer_count: 9 })];

    sortStreamsByAudience(input);

    expect(input.map((item) => item.channel)).toEqual(["quiet", "busy"]);
  });
});

describe("streamEntryKey", () => {
  it("separates the same login on two platforms", () => {
    expect(streamEntryKey(entry({ platform: "twitch", channel: "same" }))).not.toBe(
      streamEntryKey(entry({ platform: "youtube", channel: "same" }))
    );
  });
});

describe("formatStreamUptime", () => {
  const started = "2026-08-16T09:00:00Z";
  const startedMs = Date.parse(started);

  it("reads hours and minutes past the hour", () => {
    expect(formatStreamUptime(started, UNITS, startedMs + 3 * 3_600_000 + 12 * 60_000)).toBe("3h 12m");
  });

  it("drops the hour segment under an hour", () => {
    expect(formatStreamUptime(started, UNITS, startedMs + 47 * 60_000)).toBe("47m");
  });

  // The channel IS live; it just started. `null` here would read as "no data".
  it("reports a just-started channel as zero minutes, not nothing", () => {
    expect(formatStreamUptime(started, UNITS, startedMs + 5_000)).toBe("0m");
  });

  // The poller's clock and the browser's disagree by seconds routinely; a
  // negative duration on screen would be a bug report.
  it("clamps a start in the future to zero", () => {
    expect(formatStreamUptime(started, UNITS, startedMs - 90_000)).toBe("0m");
  });

  it("renders nothing before the client clock exists", () => {
    expect(formatStreamUptime(started, UNITS, null)).toBeNull();
  });

  it("renders nothing without a stamped start", () => {
    expect(formatStreamUptime(null, UNITS, startedMs)).toBeNull();
  });

  it("renders nothing for an unparseable stamp", () => {
    expect(formatStreamUptime("not a date", UNITS, startedMs)).toBeNull();
  });
});

import { describe, expect, it } from "vitest";

import { areStreamsVisible, mayHavePastBroadcasts } from "./status";
import type { TournamentStatus } from "@/types/tournament.types";

/**
 * The stream gate, spelled out over the WHOLE status vocabulary rather than the
 * two statuses that should pass. A status added to `TournamentStatus` without a
 * decision here fails the exhaustiveness case below instead of silently
 * inheriting "hidden" — which is how the pre-gate bug read in reverse: a
 * registration-phase page showed a permanent "channel is offline" dock and an
 * empty Streams tab.
 */
const EXPECTED: Record<TournamentStatus, boolean> = {
  registration: false,
  // The live player draft is broadcast, so it is the one pre-competition phase
  // whose streams belong on screen.
  draft: true,
  check_in: false,
  live: true,
  // Match play under another name — it shares the "live" presentation bucket,
  // which is what the gate actually tests.
  playoffs: true,
  completed: false,
  archived: false
};

describe("areStreamsVisible", () => {
  for (const [status, expected] of Object.entries(EXPECTED) as [TournamentStatus, boolean][]) {
    it(`${expected ? "shows" : "hides"} streams in ${status}`, () => {
      expect(areStreamsVisible(status)).toBe(expected);
    });
  }
});

/**
 * The past-broadcast read, over the whole vocabulary like the live gate above.
 * The poller records from check-in on, and a finished event keeps its VODs —
 * the one place this gate must disagree with `areStreamsVisible`.
 */
const PAST_BROADCASTS: Record<TournamentStatus, boolean> = {
  announcement: false,
  registration: false,
  check_in: true,
  draft: true,
  live: true,
  playoffs: true,
  completed: true,
  archived: true
};

describe("mayHavePastBroadcasts", () => {
  for (const [status, expected] of Object.entries(PAST_BROADCASTS) as [TournamentStatus, boolean][]) {
    it(`${expected ? "reads" : "skips"} past broadcasts in ${status}`, () => {
      expect(mayHavePastBroadcasts(status)).toBe(expected);
    });
  }
});

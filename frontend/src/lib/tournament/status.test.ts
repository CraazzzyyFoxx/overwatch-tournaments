import { describe, expect, it } from "vitest";

import { areStreamsVisible, displayStatus, mayHavePastBroadcasts } from "./status";
import type { TournamentFlowNode } from "@/types/flow.types";
import type { TournamentDisplayStatus, TournamentStatus } from "@/types/tournament.types";

/**
 * The stream gate, spelled out over the WHOLE display vocabulary rather than the
 * status that should pass. A status added without a decision here fails the
 * exhaustiveness case below instead of silently inheriting "hidden" — which is
 * how the pre-gate bug read in reverse: a registration-phase page showed a
 * permanent "channel is offline" dock and an empty Streams tab.
 */
const EXPECTED: Record<TournamentDisplayStatus, boolean> = {
  announcement: false,
  registration: false,
  check_in: false,
  forming: false,
  live: true,
  completed: false,
  archived: false
};

describe("areStreamsVisible", () => {
  for (const [status, expected] of Object.entries(EXPECTED) as [TournamentDisplayStatus, boolean][]) {
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
const PAST_BROADCASTS: Record<TournamentDisplayStatus, boolean> = {
  announcement: false,
  registration: false,
  check_in: true,
  forming: true,
  live: true,
  completed: true,
  archived: true
};

describe("mayHavePastBroadcasts", () => {
  for (const [status, expected] of Object.entries(PAST_BROADCASTS) as [TournamentDisplayStatus, boolean][]) {
    it(`${expected ? "reads" : "skips"} past broadcasts in ${status}`, () => {
      expect(mayHavePastBroadcasts(status)).toBe(expected);
    });
  }
});

function node(id: number, kind: string, status: string): TournamentFlowNode {
  return { id, kind, name: `Node ${id}`, status, config: {}, schedule: [], stage_id: null } as TournamentFlowNode;
}

function show(status: TournamentStatus, nodes?: TournamentFlowNode[]) {
  return displayStatus({ status, flow_nodes: nodes });
}

describe("displayStatus", () => {
  it("is the status unless the tournament is live", () => {
    expect(show("announcement", [node(1, "registration", "open")])).toBe("announcement");
    expect(show("completed")).toBe("completed");
    expect(show("archived")).toBe("archived");
  });

  it("shows registration while a registration node is open and no stage is live", () => {
    expect(show("live", [node(1, "registration", "open"), node(2, "stage", "draft")])).toBe("registration");
  });

  it("shows check_in while a registration node is in check-in", () => {
    expect(show("live", [node(1, "registration", "check_in")])).toBe("check_in");
  });

  it("shows live once a stage is live, even with registration still open", () => {
    expect(show("live", [node(1, "registration", "open"), node(2, "stage", "live")])).toBe("live");
  });

  it("shows live once a stage has completed, and when the read has no nodes", () => {
    expect(show("live", [node(1, "registration", "closed"), node(2, "stage", "completed")])).toBe("live");
    expect(show("live")).toBe("live");
  });

  it("shows forming while live with registration closed and no stage started", () => {
    expect(
      show("live", [node(1, "registration", "closed"), node(2, "formation", "forming"), node(3, "stage", "ready")])
    ).toBe("forming");
  });
});

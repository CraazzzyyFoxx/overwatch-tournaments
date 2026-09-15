import { describe, expect, it } from "bun:test";

import type { BracketMatch } from "@/components/bracket-view.helpers";

import {
  buildLayout,
  CARD_HEIGHT,
  CARD_WIDTH,
  HEADER_GAP_Y,
  HEADER_HEIGHT,
  MATCH_GAP_Y,
  PADDING_X,
  PADDING_Y,
  ROUND_GAP_X
} from "./layout";

const label = (round: number) => `R${round}`;
const columnX = (index: number) => PADDING_X + index * (CARD_WIDTH + ROUND_GAP_X);
const upperTop = PADDING_Y + HEADER_HEIGHT + HEADER_GAP_Y;
const pitch = CARD_HEIGHT + MATCH_GAP_Y;

function match(id: number, round: number, overrides: Partial<BracketMatch> = {}): BracketMatch {
  return {
    id,
    round,
    status: "open",
    score: { home: 0, away: 0 },
    home_team_id: id * 10,
    away_team_id: id * 10 + 1,
    ...overrides
  };
}

const nodeOf = (layout: ReturnType<typeof buildLayout>, id: number) =>
  layout.nodes.find((node) => node.encounter.id === id)!;

describe("buildLayout", () => {
  it("lays a single elimination out one column per round, each round centred in the widest one", () => {
    const layout = buildLayout(
      [
        match(1, 1),
        match(2, 1),
        match(3, 1),
        match(4, 1),
        match(5, 2),
        match(6, 2),
        match(7, 3)
      ],
      "single_elimination",
      label
    );

    expect(nodeOf(layout, 1)).toMatchObject({ x: columnX(0), y: upperTop });
    expect(nodeOf(layout, 4).y).toBe(upperTop + 3 * pitch);
    // Round 2 holds two cards; its block sits in the middle of round 1's four.
    const sectionHeight = 4 * CARD_HEIGHT + 3 * MATCH_GAP_Y;
    const blockHeight = 2 * CARD_HEIGHT + MATCH_GAP_Y;
    expect(nodeOf(layout, 5)).toMatchObject({
      x: columnX(1),
      y: upperTop + (sectionHeight - blockHeight) / 2
    });
    expect(nodeOf(layout, 7)).toMatchObject({
      x: columnX(2),
      y: upperTop + (sectionHeight - CARD_HEIGHT) / 2
    });
    expect(layout.headers.map((header) => header.label)).toEqual(["R1", "R2", "R3"]);
    expect(layout.height).toBe(upperTop + sectionHeight + PADDING_Y);
  });

  // A play-in round narrower than the round it feeds does not centre over the
  // whole section: it drops half a pitch so its card lands between the pair it
  // feeds, the way a viewer reads a bye.
  it("offsets a sparse play-in round by half a pitch instead of centring it", () => {
    const layout = buildLayout(
      [match(1, 1), match(2, 2), match(3, 2), match(4, 3)],
      "single_elimination",
      label
    );

    expect(nodeOf(layout, 1).y).toBe(upperTop + pitch / 2);
    expect(nodeOf(layout, 2).y).toBe(upperTop);
  });

  it("places a double elimination's grand final and reset right of both brackets and wires them", () => {
    const layout = buildLayout(
      [
        match(1, 1),
        match(2, 1),
        match(3, 2), // UB final
        match(4, -1), // LB final
        match(5, 3), // Grand Final
        match(6, 4) // Grand Final Reset
      ],
      "double_elimination",
      label
    );

    // Main columns = max(upper 2, lower 1); the finals take the two after.
    expect(nodeOf(layout, 5).x).toBe(columnX(2));
    expect(nodeOf(layout, 6).x).toBe(columnX(3));
    expect(layout.width).toBe(PADDING_X * 2 + 4 * CARD_WIDTH + 3 * ROUND_GAP_X);

    const edgeIds = new Set(layout.edges.map((edge) => edge.id));
    expect(edgeIds).toEqual(
      new Set(["edge-1-3", "edge-2-3", "edge-3-5", "edge-4-5", "edge-5-6"])
    );
    // Lower headers sit in their own section, below the upper bracket's cards.
    const lower = layout.headers.find((header) => header.section === "lower")!;
    expect(lower.y).toBeGreaterThan(nodeOf(layout, 2).y + CARD_HEIGHT);
  });

  // The team path highlight follows a connector only once the source is played:
  // an open match has no winner to carry forward.
  it("names the winner on a settled connector and nobody on an open one", () => {
    const layout = buildLayout(
      [
        match(1, 1, { status: "completed", score: { home: 0, away: 2 } }),
        match(2, 1),
        match(3, 2)
      ],
      "single_elimination",
      label
    );

    const byId = new Map(layout.edges.map((edge) => [edge.id, edge]));
    expect(byId.get("edge-1-3")).toMatchObject({ teamId: 11, isCompleted: true, sourceId: 1, targetId: 3 });
    expect(byId.get("edge-2-3")).toMatchObject({ teamId: null, isCompleted: false });
  });
});

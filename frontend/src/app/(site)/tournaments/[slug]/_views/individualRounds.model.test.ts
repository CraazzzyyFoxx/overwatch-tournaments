import { describe, expect, it } from "vitest";

import type { IndividualRound } from "@/types/tournament.types";

import { buildRoundViews, currentRound } from "./individualRounds.model";

function seat(slot: number, score: number) {
  return { participation_id: slot, slot, name: `Seat ${slot}`, score, placement: null, members: [] };
}

function round(number: number, status: "pending" | "open" | "completed", scores: [number, number]) {
  return {
    round: number,
    encounters: [
      {
        encounter_id: number * 10,
        status,
        result_status: "none",
        best_of: 3,
        // Wire order is not slot order.
        seats: [seat(2, scores[1]), seat(1, scores[0])]
      }
    ]
  } as unknown as IndividualRound;
}

describe("buildRoundViews", () => {
  it("orders rounds, seats by slot and numbers lobbies from 1", () => {
    const views = buildRoundViews([round(2, "open", [1, 0]), round(1, "completed", [2, 1])]);

    expect(views.map((view) => view.round)).toEqual([1, 2]);
    expect(views[0].lobbies[0]).toMatchObject({ encounterId: 10, number: 1, bestOf: 3 });
    expect(views[0].lobbies[0].seats.map((s) => s.slot)).toEqual([1, 2]);
    expect(currentRound(views)).toBe(2);
    expect(currentRound([])).toBeNull();
  });

  it("names a winner only on a finished, decided lobby and hides a pending 0-0", () => {
    const [pending, open, decided, level] = buildRoundViews([
      round(1, "pending", [0, 0]),
      round(2, "open", [1, 0]),
      round(3, "completed", [1, 2]),
      round(4, "completed", [1, 1])
    ]).map((view) => view.lobbies[0]);

    expect([pending.scored, open.scored, decided.scored]).toEqual([false, true, true]);
    expect([pending.winnerSlot, open.winnerSlot, decided.winnerSlot, level.winnerSlot]).toEqual([
      null,
      null,
      2,
      null
    ]);
  });
});

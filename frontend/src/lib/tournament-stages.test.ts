import { describe, expect, it } from "vitest";

import { groupTournamentStageFlow, nextStageOrder, phaseOrderForArrangement } from "./tournament-stages";

/**
 * `order` is a phase number the organizer owns, not a row index: stages sharing
 * one run in parallel, and the gaps between them are deliberate. Both helpers
 * exist so nothing in the admin screen quietly renumbers them.
 */
describe("stage phases", () => {
  it("groups stages sharing an order into one wave, in phase then id order", () => {
    const waves = groupTournamentStageFlow([
      { id: 4, order: 2 },
      { id: 2, order: 1 },
      { id: 1, order: 1 },
      { id: 3, order: 2 }
    ]);

    expect(waves.map((wave) => wave.map((stage) => stage.id))).toEqual([
      [1, 2],
      [3, 4]
    ]);
  });

  it("puts a new stage in a phase of its own, after the last one", () => {
    expect(nextStageOrder([{ order: 0 }, { order: 3 }, { order: 3 }])).toBe(4);
    expect(nextStageOrder([])).toBe(0);
  });

  it("hands the existing phase numbers back out in the dragged order", () => {
    // Groups(0) · Playoff Low(2) · Playoff High(2): dragging High to the top
    // moves it into phase 0 and pushes Groups into the shared phase 2.
    const phases = phaseOrderForArrangement([
      { id: 3, order: 2 },
      { id: 1, order: 0 },
      { id: 2, order: 2 }
    ]);

    expect([...phases]).toEqual([
      [3, 0],
      [1, 2],
      [2, 2]
    ]);
  });

  it("never densifies a gapped sequence into 0..n-1", () => {
    const phases = phaseOrderForArrangement([
      { id: 1, order: 0 },
      { id: 2, order: 5 },
      { id: 3, order: 9 }
    ]);

    expect([...phases.values()]).toEqual([0, 5, 9]);
  });
});

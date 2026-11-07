import { describe, expect, it } from "vitest";

import type { StageSummary } from "@/types/tournament.types";

import {
  groupTournamentStageFlow,
  nextStageOrder,
  phaseOrderForArrangement,
  phasesBesideAbove,
  pickCurrentStage
} from "./stages";

type Flags = Partial<Pick<StageSummary, "status" | "is_published">>;
const flags = { status: "draft", is_published: false };
const groups = (over: Flags = {}) =>
  ({ id: 1, stage_type: "swiss", order: 0, ...flags, ...over }) as StageSummary;
const playoffs = (over: Flags = {}) =>
  ({ id: 2, stage_type: "double_elimination", order: 1, ...flags, ...over }) as StageSummary;
const done = { is_published: true, status: "completed" } as const;

describe("pickCurrentStage", () => {
  it.each([
    ["both stages still drafts", [groups(), playoffs()], 1],
    ["groups running, playoff not started", [groups({ is_published: true }), playoffs()], 1],
    ["groups finished, playoff not started", [groups(done), playoffs()], 1],
    [
      "groups unfinished, playoff published",
      [groups({ is_published: true }), playoffs({ is_published: true })],
      1
    ],
    ["groups finished, playoff started", [groups(done), playoffs({ is_published: true })], 2],
    [
      "the active stage, whatever else holds",
      [groups({ is_published: true }), playoffs({ status: "live", is_published: true })],
      2
    ],
    ["everything finished", [groups(done), playoffs(done)], 2]
  ] as const)("live tournament, %s", (_case, stages, expected) => {
    expect(pickCurrentStage(stages, "live")?.id).toBe(expected);
  });

  it("picks the playoff that decided a finished tournament over a group stage", () => {
    const stages = [groups(done), playoffs(done)];

    expect(pickCurrentStage(stages, "completed")?.id).toBe(2);
    expect(pickCurrentStage(stages, "archived")?.id).toBe(2);
  });

  it("has nothing to pick without stages", () => {
    expect(pickCurrentStage([], "live")).toBeNull();
  });
});

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

  it("joins a stage to the phase above, and splits it off without landing on a later wave", () => {
    const list = [
      { id: 1, order: 0 },
      { id: 2, order: 1 },
      { id: 3, order: 1 },
      { id: 4, order: 2 }
    ];
    expect([...phasesBesideAbove(list, 2, "parallel")]).toEqual([[2, 0]]);
    // Low division (3) leaves High's phase: it and the final after it each move one phase later.
    expect([...phasesBesideAbove(list, 3, "after")]).toEqual([
      [3, 2],
      [4, 3]
    ]);
    expect(phasesBesideAbove(list, 1, "parallel").size).toBe(0);
  });
});

// One claim: before a single match is played, the group stage's tab still leads
// somewhere once teams are seeded (its table), while an ungenerated bracket's
// tab does not.
import { describe, expect, it } from "vitest";

import type { Stage, StageItem, Tournament } from "@/types/tournament.types";

import { buildBracketTabs } from "./bracketStages.model";

const tournament = { id: 117, slug: "txao-5" } as Tournament;

function stage(id: number, stageType: Stage["stage_type"], items: Partial<StageItem>[]): Stage {
  return { id, stage_type: stageType, name: `Stage ${id}`, items } as Stage;
}

const seeded = { id: 1, inputs: [{ id: 10 }] } as Partial<StageItem>;
const empty = { id: 2, inputs: [] } as Partial<StageItem>;

function tabs(groups: Stage[], playoff: Stage, activeStageId: number) {
  return buildBracketTabs({
    tournament,
    groupStages: groups,
    eliminationStages: [playoff],
    activeStageId,
    viewParam: null,
    matchCountsKnown: true,
    stageIdsWithMatches: new Set(),
    labels: { groupStage: "Group stage", playoff: "Playoff" }
  }).map(({ label, disabled }) => [label, disabled]);
}

describe("buildBracketTabs before any match", () => {
  it("keeps a seeded group stage selectable from the playoff tab", () => {
    const groups = stage(252, "swiss", [seeded, { ...seeded, id: 3 }]);
    const playoff = stage(253, "double_elimination", []);

    expect(tabs([groups], playoff, 253)).toEqual([
      ["Group stage", false],
      ["Playoff", false]
    ]);
  });

  it("disables what has nothing to show: unseeded groups, an ungenerated bracket", () => {
    const groups = stage(252, "swiss", [empty, { ...empty, id: 3 }]);
    const playoff = stage(253, "double_elimination", []);

    expect(tabs([groups], playoff, 252)).toEqual([
      ["Group stage", false],
      ["Playoff", true]
    ]);
    expect(tabs([groups], playoff, 253)).toEqual([
      ["Group stage", true],
      ["Playoff", false]
    ]);
  });
});

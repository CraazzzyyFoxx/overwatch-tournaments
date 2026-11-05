// One claim: before a single match is played, a tab still leads somewhere when
// its stage has something to show — a seeded group's table, an unfinished
// bracket's projection — and only a stage with nothing at all is disabled.
import { describe, expect, it } from "vitest";

import type { Stage, StageItem, Tournament } from "@/types/tournament.types";

import { buildBracketTabs, buildGroupStagePanels, selectBracketStages } from "./bracketStages.model";

const tournament = { id: 117, slug: "txao-5" } as Tournament;

function stage(
  id: number,
  stageType: Stage["stage_type"],
  items: Partial<StageItem>[],
  isCompleted = false
): Stage {
  return { id, stage_type: stageType, name: `Stage ${id}`, items, status: isCompleted ? "completed" : "draft" } as Stage;
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
  }).items.map(({ label, disabled }) => [label, disabled]);
}

describe("buildBracketTabs before any match", () => {
  it("keeps a seeded group stage and an unfinished bracket selectable", () => {
    const groups = stage(252, "swiss", [seeded, { ...seeded, id: 3 }]);
    const playoff = stage(253, "double_elimination", []);

    expect(tabs([groups], playoff, 253)).toEqual([
      ["Group stage", false],
      ["Playoff", false]
    ]);
    expect(tabs([groups], playoff, 252)).toEqual([
      ["Group stage", false],
      ["Playoff", false]
    ]);
  });

  it("disables what has nothing to show: unseeded groups, a finished empty bracket", () => {
    const groups = stage(252, "swiss", [empty, { ...empty, id: 3 }]);
    const finished = stage(253, "double_elimination", [], true);

    expect(tabs([groups], finished, 253)).toEqual([
      ["Group stage", true],
      ["Playoff", false]
    ]);
    expect(tabs([groups], finished, 252)).toEqual([
      ["Group stage", false],
      ["Playoff", true]
    ]);
  });
});

describe("an individual Swiss stage", () => {
  const individual = stage(300, "individual_swiss", []);

  it("is a group-scope stage with one panel and one tab, never judged on its items", () => {
    expect(selectBracketStages([individual], null, 300).activeGroupStages).toEqual([individual]);
    expect(buildGroupStagePanels([individual], [], [])).toHaveLength(1);
    // No items and no matches, yet its tab leads to the round view.
    expect(tabs([individual], stage(301, "single_elimination", []), 301)).toEqual([
      ["Stage 300", false],
      ["Playoff", false]
    ]);
  });
});

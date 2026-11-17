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
  isCompleted = false,
  order = 0
): Stage {
  return {
    id,
    stage_type: stageType,
    name: `Stage ${id}`,
    items,
    order,
    status: isCompleted ? "completed" : "draft"
  } as Stage;
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

describe("buildBracketTabs links", () => {
  it("the groups view link keeps its branch by naming its first group stage", () => {
    const a = stage(252, "swiss", [seeded, { ...seeded, id: 3 }]);
    const b = stage(254, "round_robin", [seeded]);
    const items = buildBracketTabs({
      tournament,
      groupStages: [a, b],
      eliminationStages: [],
      activeStageId: 252,
      viewParam: null,
      matchCountsKnown: true,
      stageIdsWithMatches: new Set(),
      labels: { groupStage: "Group stage", playoff: "Playoff" }
    }).items;
    expect(items[0].href).toContain("view=groups&stage=252");
  });
});

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

describe("a flow with several group-scope phases", () => {
  // Тхао #6: individual Swiss qualification → team Swiss groups → playoff, one phase each.
  const qualification = stage(308, "individual_swiss", [], false, 0);
  const groups = stage(309, "swiss", [seeded], false, 1);
  const playoff = stage(310, "single_elimination", [], false, 2);

  it("gives every phase its own tab, in phase order, named by its stage", () => {
    const result = buildBracketTabs({
      tournament,
      groupStages: [qualification, groups],
      eliminationStages: [playoff],
      activeStageId: 309,
      viewParam: null,
      matchCountsKnown: true,
      stageIdsWithMatches: new Set(),
      labels: { groupStage: "Group stage", playoff: "Playoff" }
    });
    expect(result.items.map(({ label, href }) => [label, href])).toEqual([
      ["Stage 308", "/tournaments/txao-5/bracket?stage=308"],
      ["Stage 309", "/tournaments/txao-5/bracket?stage=309"],
      ["Playoff", "/tournaments/txao-5/bracket?stage=310"]
    ]);
    expect(result.activeKey).toBe("stage-309");
  });

  it("draws only the selected phase in the groups view", () => {
    const stages = [qualification, groups, playoff];
    expect(selectBracketStages(stages, "groups", 309).activeGroupStages).toEqual([groups]);
  });

  it("still shares one tab between parallel group stages of a phase", () => {
    const a = stage(401, "round_robin", [seeded], false, 0);
    const b = stage(402, "round_robin", [seeded], false, 0);
    expect(tabs([a, b], stage(403, "single_elimination", [], false, 1), 401)).toEqual([
      ["Group stage", false],
      ["Playoff", false]
    ]);
    expect(selectBracketStages([a, b], "groups", 402).activeGroupStages).toEqual([a, b]);
  });
});

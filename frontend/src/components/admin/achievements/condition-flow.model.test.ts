// The achievement registry's own half of the condition builder. The tree ↔
// flat-graph conversion it used to own now lives in
// `components/rule-builder/rule-tree.test.ts`, shared with the pick-ban
// constructor; what is left here is what only achievements can answer: how a
// backend node name reads, and what one leaf says at a glance.
import { describe, expect, it } from "vitest";

import { SIDEBAR_GROUPS, conditionLabel, formatParamsSummary } from "./condition-flow.model";

describe("node names read as English", () => {
  it("keeps the acronyms a mechanical title-case would mangle", () => {
    expect(conditionLabel("hero_kd_best")).toBe("Hero K/D best");
    expect(conditionLabel("player_div")).toBe("Player division");
    expect(conditionLabel("match_mvp_check")).toBe("Match MVP check");
  });

  it("derives a label for a node the editor has never heard of", () => {
    // A node added on the backend shows up without an edit here.
    expect(conditionLabel("brand_new_node")).toBe("Brand new node");
  });

  it("falls back to a generic noun for a typeless node", () => {
    expect(conditionLabel(undefined)).toBe("condition");
  });
});

describe("one leaf at a glance", () => {
  it("summarises a stat threshold as stat, operator and value", () => {
    expect(
      formatParamsSummary("stat_threshold", { stat: "Eliminations", op: ">=", value: 20 })
    ).toBe("Eliminations, >= 20");
  });

  it("spells out a bracket path, whose params mean nothing raw", () => {
    expect(
      formatParamsSummary("bracket_path", {
        played_upper_bracket: false,
        min_lower_bracket_wins: 2,
        lost_in_round: { op: ">=", value: 3 },
      })
    ).toBe("lower bracket, LB wins >= 2, lost round >= 3");
  });

  it("is empty for a node with nothing to configure", () => {
    expect(formatParamsSummary("match_win", {})).toBe("");
  });
});

describe("the palette offers the engine's nodes", () => {
  it("names every leaf item with a registered type", () => {
    const leaves = SIDEBAR_GROUPS.flatMap((group) =>
      group.items.filter((item) => item.type === "leaf")
    );

    expect(leaves.length).toBeGreaterThan(0);
    expect(leaves.every((item) => (item.leafType ?? "") !== "")).toBe(true);
  });

  it("opens with the three logical operators, which every tree needs", () => {
    expect(SIDEBAR_GROUPS[0].items.map((item) => item.logicalOp)).toEqual(["AND", "OR", "NOT"]);
  });
});

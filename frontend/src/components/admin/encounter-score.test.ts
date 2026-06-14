import { describe, expect, it } from "bun:test";

import {
  GROUP_STAGE_SCORE_PRESETS,
  clampScoreValue,
  getMatchingScorePreset,
  isGroupStageScoreContext,
} from "@/components/admin/encounter-score";

describe("encounter score helpers", () => {
  it("exposes common group-stage result presets including draw", () => {
    expect(GROUP_STAGE_SCORE_PRESETS.map((preset) => preset.label)).toEqual([
      "2-0",
      "2-1",
      "1-1",
      "1-2",
      "0-2",
    ]);
  });

  it("matches an existing score to a preset", () => {
    expect(getMatchingScorePreset(2, 1)?.label).toBe("2-1");
    expect(getMatchingScorePreset(3, 2)).toBeUndefined();
  });

  it("clamps score input to a non-negative integer", () => {
    expect(clampScoreValue("4")).toBe(4);
    expect(clampScoreValue("-3")).toBe(0);
    expect(clampScoreValue("")).toBe(0);
    expect(clampScoreValue("2.9")).toBe(2);
  });

  it("detects group-stage contexts from stage or stage item", () => {
    expect(isGroupStageScoreContext({ stage_type: "round_robin" })).toBe(true);
    expect(isGroupStageScoreContext({ stage_type: "swiss" })).toBe(true);
    expect(isGroupStageScoreContext({ stage_type: "single_elimination" }, { type: "group" })).toBe(true);
    expect(isGroupStageScoreContext({ stage_type: "single_elimination" })).toBe(false);
  });
});

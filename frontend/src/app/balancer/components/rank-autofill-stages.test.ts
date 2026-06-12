import {
  defaultRankAutofillStages,
  moveStage,
  moveStageBySource,
  parseLookbackInput,
  setStageEnabled,
  setStageLookback,
  stageWindowValue
} from "./rank-autofill-stages";

type TestFunction = () => void | Promise<void>;
type Expectation<T> = {
  toBe: (expected: T) => void;
  toEqual: (expected: unknown) => void;
};

declare const describe: (name: string, fn: TestFunction) => void;
declare const it: (name: string, fn: TestFunction) => void;
declare const expect: <T>(actual: T) => Expectation<T>;

describe("rank autofill stage helpers", () => {
  it("builds the default chain ow → division_history → analytics, all enabled", () => {
    expect(defaultRankAutofillStages().map((stage) => stage.source)).toEqual([
      "ow",
      "division_history",
      "analytics"
    ]);
    expect(defaultRankAutofillStages().every((stage) => stage.enabled)).toBe(true);
  });

  it("returns a fresh default array each call", () => {
    expect(defaultRankAutofillStages() === defaultRankAutofillStages()).toBe(false);
  });

  it("moves a stage to a new index immutably", () => {
    const stages = defaultRankAutofillStages();
    const moved = moveStage(stages, 0, 2);
    expect(moved.map((stage) => stage.source)).toEqual(["division_history", "analytics", "ow"]);
    // original untouched
    expect(stages.map((stage) => stage.source)).toEqual(["ow", "division_history", "analytics"]);
  });

  it("returns the same reference on a no-op move", () => {
    const stages = defaultRankAutofillStages();
    expect(moveStage(stages, 1, 1) === stages).toBe(true);
    expect(moveStage(stages, 0, 9) === stages).toBe(true);
  });

  it("reorders by source ids", () => {
    const stages = defaultRankAutofillStages();
    const moved = moveStageBySource(stages, "analytics", "ow");
    expect(moved.map((stage) => stage.source)).toEqual(["analytics", "ow", "division_history"]);
  });

  it("toggles only the targeted stage", () => {
    const stages = defaultRankAutofillStages();
    const next = setStageEnabled(stages, "ow", false);
    expect(next.find((stage) => stage.source === "ow")?.enabled).toBe(false);
    expect(next.find((stage) => stage.source === "analytics")?.enabled).toBe(true);
    // original untouched
    expect(stages.find((stage) => stage.source === "ow")?.enabled).toBe(true);
  });

  it("writes lookback to the field matching the window kind", () => {
    const stages = defaultRankAutofillStages();
    const withDays = setStageLookback(stages, "ow", 14);
    expect(withDays.find((stage) => stage.source === "ow")?.lookback_days).toBe(14);

    const withTournaments = setStageLookback(stages, "analytics", 5);
    expect(withTournaments.find((stage) => stage.source === "analytics")?.lookback_tournaments).toBe(5);
  });

  it("reads the active window value regardless of backing field", () => {
    const stages = setStageLookback(setStageLookback(defaultRankAutofillStages(), "ow", 10), "analytics", 5);
    expect(stageWindowValue(stages[0])).toBe(10);
    expect(stageWindowValue(stages[2])).toBe(5);
    expect(stageWindowValue(stages[1])).toBe(null);
  });

  it("parses lookback input, treating empty / invalid / < 1 as no limit", () => {
    expect(parseLookbackInput("5")).toBe(5);
    expect(parseLookbackInput("  7 ")).toBe(7);
    expect(parseLookbackInput("3.9")).toBe(3);
    expect(parseLookbackInput("")).toBe(null);
    expect(parseLookbackInput("0")).toBe(null);
    expect(parseLookbackInput("-2")).toBe(null);
    expect(parseLookbackInput("abc")).toBe(null);
  });
});

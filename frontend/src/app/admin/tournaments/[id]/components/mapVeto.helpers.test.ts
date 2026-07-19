import { describe, expect, it } from "vitest";

import {
  BO3_SEQUENCE,
  BO5_SEQUENCE,
  buildBo1Sequence,
  buildToken,
  tokenLabel,
  validateVetoConfigForm
} from "./mapVeto.helpers";

describe("buildBo1Sequence", () => {
  it("alternates bans starting with the first team, then ends with a decider", () => {
    expect(buildBo1Sequence(5)).toEqual([
      "ban_first",
      "ban_second",
      "ban_first",
      "ban_second",
      "decider"
    ]);
  });

  it("produces exactly poolSize steps so the pool-size rule always holds", () => {
    for (const size of [2, 3, 7, 9]) {
      const sequence = buildBo1Sequence(size);
      expect(sequence).toHaveLength(size);
      expect(sequence[sequence.length - 1]).toBe("decider");
      expect(validateVetoConfigForm(sequence, Array.from({ length: size }, (_, i) => i + 1))).toEqual(
        []
      );
    }
  });
});

describe("preset sequences", () => {
  it("Bo3 and Bo5 are valid against a matching pool", () => {
    expect(validateVetoConfigForm(BO3_SEQUENCE, [1, 2, 3, 4, 5])).toEqual([]);
    expect(validateVetoConfigForm(BO5_SEQUENCE, [1, 2, 3, 4, 5, 6, 7])).toEqual([]);
  });
});

describe("validateVetoConfigForm", () => {
  it("rejects an empty pool and empty sequence", () => {
    const errors = validateVetoConfigForm([], []);
    expect(errors).toContain("Select at least one map for the pool.");
    expect(errors).toContain("The sequence must contain at least one step.");
  });

  it("rejects multiple deciders", () => {
    expect(validateVetoConfigForm(["decider", "decider"], [1, 2])).toContain(
      "Only one decider step is allowed."
    );
  });

  it("rejects a decider that is not the last step", () => {
    expect(validateVetoConfigForm(["decider", "ban_first"], [1, 2, 3])).toContain(
      "The decider step must be the last step."
    );
  });

  it("rejects a sequence longer than the pool", () => {
    expect(validateVetoConfigForm(BO3_SEQUENCE, [1, 2, 3])).toContain(
      "The sequence has 5 steps but the pool only has 3 maps."
    );
  });

  it("rejects ban-only sequences", () => {
    expect(validateVetoConfigForm(["ban_first", "ban_second"], [1, 2, 3])).toContain(
      "The sequence needs at least one pick or a decider."
    );
  });

  it("accepts a pick-based sequence without a decider", () => {
    expect(validateVetoConfigForm(["pick_first", "pick_second"], [1, 2, 3])).toEqual([]);
  });
});

describe("token round-trip", () => {
  it("builds side-agnostic tokens and labels them", () => {
    expect(buildToken("ban", "first")).toBe("ban_first");
    expect(buildToken("pick", "second")).toBe("pick_second");
    expect(buildToken("decider", "first")).toBe("decider");
    expect(tokenLabel("ban_second")).toBe("Ban 2nd");
    expect(tokenLabel("decider")).toBe("Decider");
  });
});

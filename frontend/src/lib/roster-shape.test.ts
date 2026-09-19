import { describe, expect, it } from "vitest";

import { isRoleSlotCode, orderSlotCodes, presetForSlots, slotsTotal } from "./roster-shape";

describe("presetForSlots", () => {
  it("recognizes the OW 5v5 shape", () => {
    expect(presetForSlots({ tank: 1, damage: 2, support: 2 })).toBe("ow5v5");
  });

  it("recognizes the role-free shape", () => {
    expect(presetForSlots({ flex: 6 })).toBe("flex6");
  });

  it("calls a hybrid shape custom", () => {
    expect(presetForSlots({ tank: 1, flex: 5 })).toBe("custom");
  });

  it("ignores key order", () => {
    expect(presetForSlots({ damage: 2, tank: 1, support: 2 })).toBe("ow5v5");
  });
});

describe("orderSlotCodes", () => {
  it("returns the canonical order regardless of key order", () => {
    expect(orderSlotCodes({ support: 2, flex: 1, damage: 2, tank: 1 })).toEqual([
      "tank",
      "damage",
      "support",
      "flex"
    ]);
  });

  it("omits codes that are absent or zeroed", () => {
    expect(orderSlotCodes({ tank: 1, damage: 0, flex: 5 })).toEqual(["tank", "flex"]);
    expect(orderSlotCodes({})).toEqual([]);
  });
});

describe("slotsTotal", () => {
  it("sums every slot count", () => {
    expect(slotsTotal({ tank: 1, flex: 5 })).toBe(6);
  });

  it("is zero for an empty map", () => {
    expect(slotsTotal({})).toBe(0);
  });
});

describe("isRoleSlotCode", () => {
  it("treats flex as the only role-free slot", () => {
    expect(isRoleSlotCode("flex")).toBe(false);
    expect(isRoleSlotCode("tank")).toBe(true);
  });
});

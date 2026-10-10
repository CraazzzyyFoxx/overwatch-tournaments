import { describe, expect, it } from "vitest";

import { groupDisplayName, groupHue, groupIndex } from "./group";

describe("groupDisplayName", () => {
  it("prefixes a bare letter or number with the group word", () => {
    expect(groupDisplayName("A", "Group")).toBe("Group A");
    expect(groupDisplayName(" 12 ", "Группа")).toBe("Группа 12");
  });

  it("leaves a name the organizer already spelled out alone", () => {
    expect(groupDisplayName("Группа А", "Group")).toBe("Группа А");
    expect(groupDisplayName("Upper", "Group")).toBe("Upper");
  });
});

describe("groupIndex", () => {
  it("reads the position from the trailing label in any script", () => {
    expect(groupIndex("B")).toBe(1);
    expect(groupIndex("Group c")).toBe(2);
    expect(groupIndex("Группа Б")).toBe(1);
    // Cyrillic В is the third letter, not a Latin B.
    expect(groupIndex("Группа В")).toBe(2);
    // Й is skipped, so К follows И as the tenth group.
    expect(groupIndex("Группа К")).toBe(9);
    expect(groupIndex("Group Z")).toBe(25);
    expect(groupIndex("Group 12")).toBe(11);
  });

  it("has no position for a label that is not a letter or a number", () => {
    expect(groupIndex("Playoffs")).toBeNull();
    expect(groupIndex("Group 0")).toBeNull();
    expect(groupIndex(null)).toBeNull();
  });
});

describe("groupHue", () => {
  it("gives neighbouring groups different hues and wraps past the palette", () => {
    const hues = ["A", "B", "C", "D", "E", "F"].map((name) => groupHue(name));
    expect(new Set(hues).size).toBe(6);
    expect(groupHue("G")).toBe(groupHue("A"));
    expect(groupHue("Группа Ж")).toBe(groupHue("Group 7"));
  });

  it("colours an unnumbered group like the first one", () => {
    expect(groupHue("Playoffs")).toBe(groupHue("A"));
  });
});

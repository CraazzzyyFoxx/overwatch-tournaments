import { describe, expect, it } from "vitest";

import { groupDisplayName } from "./group";

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

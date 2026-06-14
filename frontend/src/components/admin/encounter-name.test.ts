import { describe, expect, it } from "bun:test";

import { buildEncounterName } from "@/components/admin/encounter-name";

const teams = [
  { id: 1, name: "Txao" },
  { id: 2, name: "NoBrain" }
];

describe("encounter name helpers", () => {
  it("builds the name from selected teams", () => {
    expect(buildEncounterName(teams, 1, 2)).toBe("Txao vs NoBrain");
  });

  it("uses TBD for unselected or unknown teams", () => {
    expect(buildEncounterName(teams, 1, null)).toBe("Txao vs TBD");
    expect(buildEncounterName(teams, null, null)).toBe("TBD vs TBD");
    expect(buildEncounterName(teams, 99, 2)).toBe("TBD vs NoBrain");
  });
});

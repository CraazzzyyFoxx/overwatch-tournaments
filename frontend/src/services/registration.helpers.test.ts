import { describe, expect, it } from "bun:test";

import { rehydrateRegistrationList } from "@/services/registration.helpers";
import type { RegistrationListResponse } from "@/types/registration.types";
import type { DivisionGridVersion } from "@/types/workspace.types";

const grid = (id: number): DivisionGridVersion =>
  ({ id, tiers: [] }) as unknown as DivisionGridVersion;

const buildResponse = (): RegistrationListResponse =>
  ({
    registrations: [
      {
        id: 1,
        tournament_history: [
          {
            tournament_id: 10,
            tournament_name: "T10",
            role: "tank",
            division: 4,
            division_grid_version_id: 5,
          },
          {
            tournament_id: 11,
            tournament_name: "T11",
            role: null,
            division: null,
            division_grid_version_id: null,
          },
          {
            tournament_id: 12,
            tournament_name: "T12",
            role: "dps",
            division: 2,
            division_grid_version_id: 99, // not present in division_grids
          },
        ],
      },
      { id: 2, tournament_history: [] },
      { id: 3 }, // no tournament_history field at all
    ],
    // JSON object keys arrive as strings.
    division_grids: { "5": grid(5) },
  }) as unknown as RegistrationListResponse;

describe("rehydrateRegistrationList", () => {
  it("rehydrates division_grid_version from the shared map by string key", () => {
    const [reg] = rehydrateRegistrationList(buildResponse());
    const entry = reg.tournament_history![0];

    expect(entry.division_grid_version_id).toBe(5);
    expect(entry.division_grid_version?.id).toBe(5);
    // Preserves the other entry fields.
    expect(entry.tournament_id).toBe(10);
    expect(entry.division).toBe(4);
  });

  it("leaves division_grid_version null when the entry has no version id", () => {
    const [reg] = rehydrateRegistrationList(buildResponse());
    expect(reg.tournament_history![1].division_grid_version).toBeNull();
  });

  it("falls back to null for a version id missing from the map", () => {
    const [reg] = rehydrateRegistrationList(buildResponse());
    expect(reg.tournament_history![2].division_grid_version).toBeNull();
  });

  it("returns one entry per registration and normalises missing history to []", () => {
    const result = rehydrateRegistrationList(buildResponse());
    expect(result.map((r) => r.id)).toEqual([1, 2, 3]);
    expect(result[1].tournament_history).toEqual([]);
    expect(result[2].tournament_history).toEqual([]);
  });

  it("tolerates an empty envelope", () => {
    const result = rehydrateRegistrationList({
      registrations: [],
      division_grids: {},
    });
    expect(result).toEqual([]);
  });
});

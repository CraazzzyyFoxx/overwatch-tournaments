import { describe, expect, it } from "vitest";

import type { DraftFeasibility, DraftPlayer, DraftRoleEditResponse } from "@/types/draft.types";

import { availableRolesForPlayer, canCommitRoleEdit, roleEditImpact } from "./admin-control-model";

const feasible = (matched: number, isFeasible = false): DraftFeasibility => ({
  is_feasible: isFeasible,
  total_open_slots: 3,
  matched_slots: matched,
  unmatched_slots: [],
  slot_deficits: [],
  blocking_player_ids: [],
  reason_code: isFeasible ? null : "role_shortage"
});

const player = {
  id: 10,
  version: 4,
  primary_role: "tank",
  secondary_roles: ["damage"]
} as DraftPlayer;

describe("admin draft control model", () => {
  it("offers only roles the player does not already declare", () => {
    expect(availableRolesForPlayer(player)).toEqual(["support"]);
  });

  it("requires a current preview and valid audit inputs before role commit", () => {
    const preview: DraftRoleEditResponse = {
      player_id: player.id,
      role: "support",
      player_version: player.version,
      committed: false,
      before: feasible(1),
      after: feasible(2)
    };
    expect(canCommitRoleEdit({ player, role: "support", rankValue: 2500, reason: "Final support slot", preview })).toBe(true);
    expect(canCommitRoleEdit({ player: { ...player, version: 5 }, role: "support", rankValue: 2500, reason: "Final support slot", preview })).toBe(false);
    expect(canCommitRoleEdit({ player, role: "support", rankValue: 2500, reason: " ", preview })).toBe(false);
    // A rankless role is not playable, so there is no "confirm there is no
    // rank" path any more: null and 0 both refuse.
    expect(canCommitRoleEdit({ player, role: "support", rankValue: null, reason: "Final support slot", preview })).toBe(false);
    expect(canCommitRoleEdit({ player, role: "support", rankValue: 0, reason: "Final support slot", preview })).toBe(false);
  });

  it("describes whether preview improves or resolves feasibility", () => {
    expect(roleEditImpact({ before: feasible(1), after: feasible(2) })).toBe("improved");
    expect(roleEditImpact({ before: feasible(1), after: feasible(3, true) })).toBe("resolved");
    expect(roleEditImpact({ before: feasible(2), after: feasible(2) })).toBe("unchanged");
  });
});

import { describe, expect, it } from "vitest";

import type { RosterShape } from "@/lib/roster/shape";

import type { AdminRegistration } from "@/types/balancer-admin.types";

import {
  buildDraftSchedule,
  canCancelDraftSetup,
  derivePoolReadiness,
  filterCaptainRows,
  moveCaptain,
  orderCaptainIds,
  previousSetupStep,
  reseatCaptain,
  SETUP_STEPS,
  validateSetupStep,
  type DraftCaptainRow
} from "./setup-model";
import { captainSeat, poolRegistrationSummary } from "./setup-types";

const CAPTAIN_ROWS: DraftCaptainRow[] = [
  { id: 1, label: "Baida#21855", roles: ["tank", "damage", "support"], rank: null, rankRole: null },
  { id: 2, label: "agoNy4#2362", roles: ["support", "tank"], rank: 2600, rankRole: "support" },
  { id: 3, label: "sleepdarya#2298", roles: ["support"], rank: 3800, rankRole: "support" },
  { id: 4, label: "Zish#2101", roles: ["damage"], rank: 3100, rankRole: "damage" }
];

/** A `roster_shape` payload as the server sends it, for a 3-slot roster. */
const SHAPE: RosterShape = {
  slots: { tank: 1, damage: 2 },
  team_size: 3,
  flex_slots: 0,
  has_role_slots: true,
  draft_rounds: 2,
  source: null
};

describe("draft setup model", () => {
  it("defines the six-step flow", () => {
    expect(SETUP_STEPS).toEqual([
      "config",
      "pool",
      "captains",
      "order",
      "review",
      "ready"
    ]);
  });

  it("moves the setup flow back one step at a time", () => {
    expect(previousSetupStep("pool")).toBe("config");
    expect(previousSetupStep("config")).toBe("config");
  });

  it("allows cancelling local and persisted unfinished setup", () => {
    expect(canCancelDraftSetup("config", null)).toBe(false);
    expect(canCancelDraftSetup("pool", null)).toBe(true);
    expect(canCancelDraftSetup("config", "setup")).toBe(true);
    expect(canCancelDraftSetup("ready", "ready")).toBe(true);
    expect(canCancelDraftSetup("ready", "cancelled")).toBe(false);
  });

  it("blocks the seed on missing ranks and still counts accounts and exclusions", () => {
    const readiness = derivePoolReadiness(
      [
        { id: 1, roles: ["tank"], rank: 3000, hasAccount: true, excluded: false },
        { id: 2, roles: ["damage"], rank: null, hasAccount: true, excluded: false },
        { id: 3, roles: ["support"], rank: 2800, hasAccount: false, excluded: false },
        { id: 4, roles: ["support"], rank: 2700, hasAccount: true, excluded: true }
      ],
      2,
      SHAPE
    );

    expect(readiness.requiredPlayers).toBe(6);
    expect(readiness.actualPlayers).toBe(3);
    expect(readiness.missingRanks).toBe(1);
    expect(readiness.missingAccounts).toBe(1);
    expect(readiness.excludedPlayers).toBe(1);
    expect(readiness.blockers).toContain("not_enough_players");
    // The server refuses to seed an unranked pool player, so the wizard must
    // say so rather than let the organizer walk into a 4xx.
    expect(readiness.blockers).toContain("pool_unranked");
  });

  it("reorders captains deterministically for manual order", () => {
    expect(moveCaptain([10, 20, 30], 30, 10)).toEqual([30, 10, 20]);
    expect(moveCaptain([10, 20, 30], 99, 10)).toEqual([10, 20, 30]);
  });

  it("dragging a computed order overrides its seeds, not the selection order", () => {
    const ranks = new Map([
      [10, 3100],
      [20, 2500],
      [30, 2800]
    ]);
    const value = { ids: [10, 20, 30], teamNames: {}, roles: {}, order: "weakest_first" as const, randomSeed: 42 };
    const shown = orderCaptainIds(value.ids, value.order, ranks, value.randomSeed); // [20, 30, 10]

    // 10 dragged onto seat 1: the shown order with that move, now manual.
    expect(reseatCaptain(value, shown, 10, 20)).toMatchObject({ order: "manual", ids: [10, 20, 30] });
    expect(reseatCaptain(value, shown, 30, 20)).toMatchObject({ order: "manual", ids: [30, 20, 10] });
    // A drop outside the list changes nothing, and does not flip the order.
    expect(reseatCaptain(value, shown, 99, 20)).toBe(value);
  });

  it("keeps calculated captain order reproducible", () => {
    const ranks = new Map([
      [10, 3100],
      [20, 2500],
      [30, 2800]
    ]);
    expect(orderCaptainIds([10, 20, 30], "weakest_first", ranks, 42)).toEqual([20, 30, 10]);
    expect(orderCaptainIds([10, 20, 30], "strongest_first", ranks, 42)).toEqual([10, 30, 20]);
    expect(orderCaptainIds([10, 20, 30], "random", ranks, 42)).toEqual([30, 10, 20]);
  });

  it("breaks tied captain ranks by id in both directions, like the server", () => {
    const ranks = new Map([
      [30, 2500],
      [10, 2500],
      [20, 3000]
    ]);
    expect(orderCaptainIds([30, 10, 20], "weakest_first", ranks, 0)).toEqual([10, 30, 20]);
    expect(orderCaptainIds([30, 10, 20], "strongest_first", ranks, 0)).toEqual([20, 10, 30]);
  });

  it("previews snake order for every round", () => {
    expect(buildDraftSchedule([10, 20, 30], 3, "snake", [])).toEqual([
      { round: 1, teamIds: [10, 20, 30], rule: "linear", resolved: true },
      { round: 2, teamIds: [30, 20, 10], rule: "reverse", resolved: true },
      { round: 3, teamIds: [10, 20, 30], rule: "linear", resolved: true }
    ]);
  });

  it("marks a custom round unresolved when only the server knows its order", () => {
    // reverse is N->1 and the client can show it; the rank- and average-driven
    // rules are resolved server-side, so their teamIds must not be presented as
    // the schedule — that promise is what made the board look like it invented
    // its own order.
    const schedule = buildDraftSchedule([10, 20, 30], 4, "custom", [
      "reverse",
      "strongest_first",
      "weakest_first",
      "team_avg_asc"
    ]);

    expect(schedule.map((round) => round.rule)).toEqual([
      "reverse",
      "strongest_first",
      "weakest_first",
      "team_avg_asc"
    ]);
    expect(schedule.map((round) => round.resolved)).toEqual([true, false, false, false]);
    expect(schedule[0].teamIds).toEqual([30, 20, 10]);
  });

  it("blocks advancing until each step has its required data", () => {
    expect(
      validateSetupStep("config", {
        pickTimeSeconds: 5,
        captainIds: [],
        poolReady: false,
        previewFeasible: false
      })
    ).toContain("pick_time_out_of_range");
    expect(
      validateSetupStep("captains", {
        pickTimeSeconds: 45,
        captainIds: [],
        poolReady: true,
        previewFeasible: false
      })
    ).toEqual(["captains_required"]);
    expect(
      validateSetupStep("review", {
        pickTimeSeconds: 45,
        captainIds: [1, 2],
        poolReady: true,
        previewFeasible: true
      })
    ).toEqual([]);
  });

  it("sorts captains by rank in both directions and keeps unranked players last", () => {
    expect(
      filterCaptainRows(CAPTAIN_ROWS, { query: "", roles: [], sort: "rank_desc" }).map((r) => r.id)
    ).toEqual([3, 4, 2, 1]);
    // An unranked captain is unknown, not weakest: it stays last ascending too.
    expect(
      filterCaptainRows(CAPTAIN_ROWS, { query: "", roles: [], sort: "rank_asc" }).map((r) => r.id)
    ).toEqual([2, 4, 3, 1]);
    expect(
      filterCaptainRows(CAPTAIN_ROWS, { query: "", roles: [], sort: "name" }).map((r) => r.id)
    ).toEqual([2, 1, 3, 4]);
  });

  it("ORs the role filter and treats an empty selection as every role", () => {
    expect(
      filterCaptainRows(CAPTAIN_ROWS, { query: "", roles: ["damage"], sort: "rank_desc" }).map(
        (r) => r.id
      )
    ).toEqual([4, 1]);
    expect(
      filterCaptainRows(CAPTAIN_ROWS, { query: "", roles: ["damage", "support"], sort: "rank_desc" })
        .map((r) => r.id)
    ).toEqual([3, 4, 2, 1]);
    expect(filterCaptainRows(CAPTAIN_ROWS, { query: "", roles: [], sort: "rank_desc" })).toHaveLength(
      CAPTAIN_ROWS.length
    );
  });

  it("matches the search case-insensitively and never mutates the input order", () => {
    expect(
      filterCaptainRows(CAPTAIN_ROWS, { query: "  DARYA ", roles: [], sort: "rank_desc" }).map(
        (r) => r.id
      )
    ).toEqual([3]);
    expect(CAPTAIN_ROWS.map((row) => row.id)).toEqual([1, 2, 3, 4]);
  });

  it("narrows the list to the chosen captains without losing the sort", () => {
    expect(
      filterCaptainRows(CAPTAIN_ROWS, {
        query: "",
        roles: [],
        sort: "rank_desc",
        selectedOnly: true,
        selectedIds: [1, 4]
      }).map((row) => row.id)
    ).toEqual([4, 1]);
    // The chip is off by default: passing the selection alone changes nothing.
    expect(
      filterCaptainRows(CAPTAIN_ROWS, {
        query: "",
        roles: [],
        sort: "rank_desc",
        selectedIds: [1]
      })
    ).toHaveLength(CAPTAIN_ROWS.length);
  });

  it("seats a captain on their lead role unless the organizer pins another", () => {
    // Primary tank 2000, secondary damage 3500, and an inactive support that
    // must not count at all.
    const registration = {
      id: 9,
      roles: [
        { role: "tank", is_active: true, is_primary: true, priority: 0, rank_value: 2000 },
        { role: "damage", is_active: true, is_primary: false, priority: 1, rank_value: 3500 },
        { role: "support", is_active: false, is_primary: false, priority: 2, rank_value: 4200 }
      ]
    } as unknown as AdminRegistration;

    // The lead role's own rank, not the damage maximum.
    expect(captainSeat(registration, undefined, SHAPE)).toEqual({
      role: "tank",
      rank: 2000,
      options: ["tank", "damage"]
    });
    expect(captainSeat(registration, "damage", SHAPE)).toMatchObject({ role: "damage", rank: 3500 });
    // A pin the captain cannot play falls back to the lead role.
    expect(captainSeat(registration, "support", SHAPE)).toMatchObject({ role: "tank", rank: 2000 });
    // A role-less roster seats nobody on a role: the best playable rank.
    const allFlex = { slots: { flex: 3 }, has_role_slots: false };
    expect(captainSeat(registration, "damage", allFlex)).toEqual({ role: null, rank: 3500, options: [] });
    expect(captainSeat({ id: 10, roles: [] } as unknown as AdminRegistration, undefined, SHAPE)).toEqual({
      role: null,
      rank: null,
      options: []
    });
    expect(poolRegistrationSummary(registration).rank).toBe(2000);
  });
});

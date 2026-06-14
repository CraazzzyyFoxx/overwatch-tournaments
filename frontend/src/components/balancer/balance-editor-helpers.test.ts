import {
  canPlayerPlayRole,
  deriveRoleDiscomfort,
  moveBalancePlayer,
  type BalanceDropTarget,
} from "@/components/balancer/balance-editor-helpers";
import {
  calculateTeamDiscomfortFromPayload,
  calculateTeamVarianceFromPayload,
} from "@/app/balancer/components/balancer-page-helpers";
import type {
  BalancerRosterKey,
  InternalBalancePayload,
  InternalBalancePlayer,
} from "@/types/balancer-admin.types";

type TestFunction = () => void | Promise<void>;
type Expectation<T> = {
  toBe: (expected: T) => void;
  toEqual: (expected: unknown) => void;
  toBeNull: () => void;
  toBeUndefined: () => void;
  toBeCloseTo: (expected: number, precision?: number) => void;
};

declare const describe: (name: string, fn: TestFunction) => void;
declare const it: (name: string, fn: TestFunction) => void;
declare const expect: <T>(actual: T) => Expectation<T>;

function makePlayer(overrides: Partial<InternalBalancePlayer> = {}): InternalBalancePlayer {
  return {
    uuid: "1",
    name: "Player",
    assigned_rating: 3000,
    role_preferences: ["Tank"],
    all_ratings: { Tank: 3000 },
    is_flex: false,
    role_discomfort: 0,
    ...overrides,
  };
}

function emptyRoster(): Record<BalancerRosterKey, InternalBalancePlayer[]> {
  return { Tank: [], Damage: [], Support: [] };
}

function makePayload(
  teamRosters: Array<Partial<Record<BalancerRosterKey, InternalBalancePlayer[]>>>,
): InternalBalancePayload {
  return {
    teams: teamRosters.map((roster, index) => ({
      id: index + 1,
      name: `Team ${index + 1}`,
      average_mmr: 0,
      rating_variance: 0,
      total_discomfort: 0,
      max_discomfort: 0,
      roster: { ...emptyRoster(), ...roster },
    })),
    statistics: {},
    benched_players: [],
  };
}

describe("canPlayerPlayRole", () => {
  it("returns true for a role the player has a positive rating for", () => {
    const player = makePlayer({ all_ratings: { Tank: 3000, Damage: 2800 } });
    expect(canPlayerPlayRole(player, "Tank")).toBe(true);
    expect(canPlayerPlayRole(player, "Damage")).toBe(true);
  });

  it("returns false for a role the player has no rating for", () => {
    const player = makePlayer({ all_ratings: { Damage: 2800, Support: 2700 } });
    expect(canPlayerPlayRole(player, "Tank")).toBe(false);
  });

  it("treats a zero rating as not playable", () => {
    const player = makePlayer({ all_ratings: { Tank: 0, Damage: 2800 } });
    expect(canPlayerPlayRole(player, "Tank")).toBe(false);
  });

  it("falls back to role_preferences when all_ratings is missing", () => {
    const player = makePlayer({ all_ratings: undefined, role_preferences: ["Damage", "Support"] });
    expect(canPlayerPlayRole(player, "Damage")).toBe(true);
    expect(canPlayerPlayRole(player, "Tank")).toBe(false);
  });
});

describe("moveBalancePlayer role validation", () => {
  it("rejects moving a player into a role they cannot play", () => {
    const support = makePlayer({
      uuid: "10",
      role_preferences: ["Support"],
      all_ratings: { Support: 2700 },
    });
    const payload = makePayload([{ Support: [support] }, {}]);
    const target: BalanceDropTarget = { kind: "role-container", teamIndex: 1, roleKey: "Tank" };

    expect(moveBalancePlayer(payload, "10", target)).toBeNull();
  });

  it("allows moving a player into a role they can play", () => {
    const flexTank = makePlayer({
      uuid: "11",
      role_preferences: ["Damage", "Tank"],
      all_ratings: { Damage: 2900, Tank: 2800 },
    });
    const payload = makePayload([{ Damage: [flexTank] }, {}]);
    const target: BalanceDropTarget = { kind: "role-container", teamIndex: 1, roleKey: "Tank" };

    const next = moveBalancePlayer(payload, "11", target);
    expect(next).not.toBeNull();
    expect(next?.teams[1].roster.Tank.length).toBe(1);
    expect(next?.teams[0].roster.Damage.length).toBe(0);
  });

  it("rejects a swap when the displaced player cannot play the source role", () => {
    // dragged: Damage main being dropped onto an occupied Tank slot (can play Tank)
    const draggedDps = makePlayer({
      uuid: "20",
      role_preferences: ["Damage", "Tank"],
      all_ratings: { Damage: 2900, Tank: 2800 },
    });
    // occupant: pure Tank who cannot play Damage -> swap into Damage is illegal
    const occupantTank = makePlayer({
      uuid: "21",
      role_preferences: ["Tank"],
      all_ratings: { Tank: 3100 },
    });
    const payload = makePayload([{ Damage: [draggedDps] }, { Tank: [occupantTank] }]);
    const target: BalanceDropTarget = {
      kind: "player-row",
      teamIndex: 1,
      roleKey: "Tank",
      playerIndex: 0,
      playerId: "21",
    };

    expect(moveBalancePlayer(payload, "20", target)).toBeNull();
  });

  it("allows a swap when both players can play the swapped roles", () => {
    const draggedDps = makePlayer({
      uuid: "30",
      role_preferences: ["Damage", "Tank"],
      all_ratings: { Damage: 2900, Tank: 2800 },
    });
    const occupantFlex = makePlayer({
      uuid: "31",
      role_preferences: ["Tank", "Damage"],
      all_ratings: { Tank: 3100, Damage: 3000 },
    });
    const payload = makePayload([{ Damage: [draggedDps] }, { Tank: [occupantFlex] }]);
    const target: BalanceDropTarget = {
      kind: "player-row",
      teamIndex: 1,
      roleKey: "Tank",
      playerIndex: 0,
      playerId: "31",
    };

    const next = moveBalancePlayer(payload, "30", target);
    expect(next).not.toBeNull();
    expect(next?.teams[1].roster.Tank[0]?.uuid).toBe("30");
    expect(next?.teams[0].roster.Damage[0]?.uuid).toBe("31");
  });

  it("allows reordering within the same role bucket regardless of other roles", () => {
    const a = makePlayer({ uuid: "40", role_preferences: ["Damage"], all_ratings: { Damage: 2900 } });
    const b = makePlayer({ uuid: "41", role_preferences: ["Damage"], all_ratings: { Damage: 2800 } });
    const payload = makePayload([{ Damage: [a, b] }]);
    const target: BalanceDropTarget = {
      kind: "player-row",
      teamIndex: 0,
      roleKey: "Damage",
      playerIndex: 0,
      playerId: "40",
    };

    const next = moveBalancePlayer(payload, "41", target);
    expect(next).not.toBeNull();
    expect(next?.teams[0].roster.Damage[0]?.uuid).toBe("41");
  });
});

describe("deriveRoleDiscomfort", () => {
  it("returns 0 for a flex player on a playable role", () => {
    const player = makePlayer({ is_flex: true, all_ratings: { Tank: 3000, Damage: 2900 } });
    expect(deriveRoleDiscomfort(player, "Damage")).toBe(0);
  });

  it("returns 0 for the primary role and 100 per preference step", () => {
    const player = makePlayer({
      is_flex: false,
      role_preferences: ["Tank", "Damage", "Support"],
      all_ratings: { Tank: 3000, Damage: 2900, Support: 2800 },
    });
    expect(deriveRoleDiscomfort(player, "Tank")).toBe(0);
    expect(deriveRoleDiscomfort(player, "Damage")).toBe(100);
    expect(deriveRoleDiscomfort(player, "Support")).toBe(200);
  });

  it("returns 1000 for a playable off-preference role, 5000 for an unplayable role", () => {
    const player = makePlayer({
      is_flex: false,
      role_preferences: ["Damage"],
      all_ratings: { Damage: 2900, Support: 2700 },
    });
    expect(deriveRoleDiscomfort(player, "Support")).toBe(1000);
    expect(deriveRoleDiscomfort(player, "Tank")).toBe(5000);
  });
});

describe("moveBalancePlayer rank + discomfort recompute", () => {
  it("re-rates the player for the new role and keeps original preference order", () => {
    const dps = makePlayer({
      uuid: "50",
      role_preferences: ["Damage", "Tank"],
      all_ratings: { Damage: 2900, Tank: 2800 },
      all_discomforts: { Damage: 0, Tank: 100 },
      assigned_rating: 2900,
      role_discomfort: 0,
    });
    const payload = makePayload([{ Damage: [dps] }, {}]);
    const target: BalanceDropTarget = { kind: "role-container", teamIndex: 1, roleKey: "Tank" };

    const next = moveBalancePlayer(payload, "50", target);
    expect(next).not.toBeNull();
    const moved = next?.teams[1].roster.Tank[0];
    expect(moved?.assigned_rating).toBe(2800);
    expect(moved?.role_discomfort).toBe(100);
    // Preferences are NOT reordered (true primary remains first).
    expect(moved?.role_preferences).toEqual(["Damage", "Tank"]);
    expect(next?.teams[1].average_mmr).toBeCloseTo(2800, 5);
    expect(next?.teams[0].average_mmr).toBeCloseTo(0, 5);
  });

  it("derives discomfort when all_discomforts is absent (legacy payload)", () => {
    const dps = makePlayer({
      uuid: "51",
      role_preferences: ["Damage"],
      all_ratings: { Damage: 2900, Tank: 2800 },
      all_discomforts: undefined,
      assigned_rating: 2900,
    });
    const payload = makePayload([{ Damage: [dps] }, {}]);
    const target: BalanceDropTarget = { kind: "role-container", teamIndex: 1, roleKey: "Tank" };

    const next = moveBalancePlayer(payload, "51", target);
    const moved = next?.teams[1].roster.Tank[0];
    expect(moved?.assigned_rating).toBe(2800);
    expect(moved?.role_discomfort).toBe(1000); // playable off-preference
  });
});

describe("team variance + discomfort recompute", () => {
  it("computes sample stdev of assigned ratings and discomfort total/max", () => {
    const payload = makePayload([
      {
        Tank: [makePlayer({ uuid: "60", assigned_rating: 3000, role_discomfort: 0 })],
        Damage: [
          makePlayer({ uuid: "61", assigned_rating: 2800, role_discomfort: 0 }),
          makePlayer({ uuid: "62", assigned_rating: 2600, role_discomfort: 100 }),
        ],
        Support: [
          makePlayer({ uuid: "63", assigned_rating: 2700, role_discomfort: 0 }),
          makePlayer({ uuid: "64", assigned_rating: 2500, role_discomfort: 1000 }),
        ],
      },
    ]);
    const team = payload.teams[0];

    // ratings [3000,2800,2600,2700,2500], mean 2720, sample variance 37000 -> stdev ~192.354
    expect(calculateTeamVarianceFromPayload(team)).toBeCloseTo(192.35, 1);

    const discomfort = calculateTeamDiscomfortFromPayload(team);
    expect(discomfort.total).toBe(1100);
    expect(discomfort.max).toBe(1000);
  });

  it("returns 0 variance for a single-player team", () => {
    const payload = makePayload([{ Tank: [makePlayer({ uuid: "70", assigned_rating: 3000 })] }]);
    expect(calculateTeamVarianceFromPayload(payload.teams[0])).toBe(0);
  });
});

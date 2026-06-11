import {
  derivePoolLane,
  formatBattleTagsForClipboard,
  formatSmurfCount,
  getRegistrationBattleTags,
  getPoolDropPatch,
  type PlayerValidationState,
  type PoolLane,
} from "@/app/balancer/components/balancer-page-helpers";
import {
  createSyntheticApplicationFromRegistration,
  createSyntheticPlayerFromRegistration,
  getPlayerValidationIssues,
  isRegistrationIncludedInBalancer,
  type PlayerValidationIssue,
} from "@/app/balancer/components/workspace-helpers";
import type { AdminRegistration, BalancerApplication, BalancerPlayerRecord, StatusMeta, StatusScope } from "@/types/balancer-admin.types";

type TestFunction = () => void | Promise<void>;
type Expectation<T> = {
  toBe: (expected: T) => void;
  toEqual: (expected: unknown) => void;
  toBeNull: () => void;
  toBeUndefined: () => void;
};

declare const describe: (name: string, fn: TestFunction) => void;
declare const it: {
  (name: string, fn: TestFunction): void;
  each<TArgs extends readonly unknown[]>(cases: readonly TArgs[]): (name: string, fn: (...args: TArgs) => void | Promise<void>) => void;
};
declare const expect: <T>(actual: T) => Expectation<T>;

function createPlayer(overrides: Partial<BalancerPlayerRecord>): BalancerPlayerRecord {
  return {
    id: 1,
    tournament_id: 60,
    application_id: 10,
    battle_tag: "player#1234",
    battle_tag_normalized: "player#1234",
    user_id: 1,
    role_entries_json: [],
    is_flex: false,
    is_in_pool: true,
    admin_notes: null,
    ...overrides,
  };
}

function createApplication(overrides: Partial<BalancerApplication>): BalancerApplication {
  return {
    id: 10,
    tournament_id: 60,
    tournament_sheet_id: 1,
    battle_tag: "player#1234",
    battle_tag_normalized: "player#1234",
    smurf_tags_json: [],
    twitch_nick: null,
    discord_nick: null,
    stream_pov: false,
    last_tournament_text: null,
    primary_role: "support",
    additional_roles_json: ["dps"],
    notes: null,
    submitted_at: null,
    synced_at: "2026-03-14T00:00:00Z",
    is_active: true,
    player: null,
    ...overrides,
  };
}

function createStatusMeta(value: string, scope: StatusScope, name: string): StatusMeta {
  return {
    value,
    scope,
    is_builtin: true,
    kind: "builtin",
    is_override: false,
    can_edit: false,
    can_delete: false,
    can_reset: false,
    icon_slug: null,
    icon_color: null,
    name,
    description: null,
  };
}

function createRegistration(overrides: Partial<AdminRegistration> = {}): AdminRegistration {
  return {
    id: 10,
    tournament_id: 60,
    workspace_id: 3,
    auth_user_id: null,
    user_id: 1,
    display_name: "Player",
    battle_tag: "player#1234",
    battle_tag_normalized: "player#1234",
    source: "manual",
    source_record_key: null,
    smurf_tags_json: [],
    discord_nick: null,
    twitch_nick: null,
    stream_pov: false,
    roles: [
      {
        role: "support",
        subrole: null,
        is_primary: true,
        priority: 0,
        rank_value: 900,
        is_active: true,
      },
      {
        role: "dps",
        subrole: null,
        is_primary: false,
        priority: 1,
        rank_value: 700,
        is_active: true,
      },
    ],
    notes: null,
    admin_notes: null,
    custom_fields_json: null,
    is_flex: false,
    status: "approved",
    status_meta: createStatusMeta("approved", "registration", "Approved"),
    balancer_status: "ready",
    balancer_status_meta: createStatusMeta("ready", "balancer", "Ready"),
    exclude_from_balancer: false,
    exclude_reason: null,
    checked_in: false,
    checked_in_at: null,
    checked_in_by_username: null,
    deleted_at: null,
    submitted_at: null,
    reviewed_at: null,
    reviewed_by_username: null,
    balancer_profile_overridden_at: null,
    ...overrides,
  };
}

describe("getPlayerValidationIssues", () => {
  it("does not flag support main-heal plus dps as mismatch", () => {
    const player = createPlayer({
      role_entries_json: [
        {
          role: "support",
          subtype: "main_heal",
          priority: 1,
          division_number: 12,
          rank_value: 900,
          is_active: true,
        },
        {
          role: "dps",
          subtype: null,
          priority: 2,
          division_number: 14,
          rank_value: 700,
          is_active: true,
        },
      ],
    });
    const application = createApplication({
      primary_role: "support",
      additional_roles_json: ["dps"],
    });

    const issues = getPlayerValidationIssues(player, application);

    expect(issues.find((issue) => issue.code === "application_role_mismatch")).toBeUndefined();
  });

  it("does not flag missing optional secondary role when primary role matches", () => {
    const player = createPlayer({
      role_entries_json: [
        {
          role: "dps",
          subtype: "hitscan",
          priority: 1,
          division_number: 12,
          rank_value: 900,
          is_active: true,
        },
      ],
    });
    const application = createApplication({
      primary_role: "dps",
      additional_roles_json: ["support"],
    });

    const issues = getPlayerValidationIssues(player, application);

    expect(issues.find((issue) => issue.code === "application_role_mismatch")).toBeUndefined();
  });

  it("does not flag flex secondary subrole gaps as mismatch when main roles match", () => {
    const player = createPlayer({
      role_entries_json: [
        {
          role: "support",
          subtype: "main_heal",
          priority: 1,
          division_number: 12,
          rank_value: 900,
          is_active: true,
        },
        {
          role: "dps",
          subtype: null,
          priority: 2,
          division_number: 14,
          rank_value: 700,
          is_active: true,
        },
      ],
      is_flex: true,
    });
    const application = createApplication({
      primary_role: "support",
      additional_roles_json: ["dps"],
    });

    const issues = getPlayerValidationIssues(player, application);

    expect(issues.find((issue) => issue.code === "application_role_mismatch")).toBeUndefined();
  });

  it("emits a rank-delta warning for every role that exceeds the threshold", () => {
    const player = createPlayer({
      role_entries_json: [
        { role: "support", subtype: null, priority: 0, division_number: null, rank_value: 900, is_active: true, ow_rank_value: 2000 },
        { role: "dps", subtype: null, priority: 1, division_number: null, rank_value: 700, is_active: true, ow_rank_value: 1900 },
      ],
    });

    const issues = getPlayerValidationIssues(player, null, { rank_delta_threshold: 100 });
    const deltaIssues = issues.filter(
      (issue): issue is Extract<PlayerValidationIssue, { code: "rank_delta_warning" }> =>
        issue.code === "rank_delta_warning",
    );

    expect(deltaIssues.length).toBe(2);
    // Worst delta first: dps (Δ1200) before support (Δ1100).
    expect(deltaIssues.map((issue) => issue.role).join(",")).toBe("dps,support");
  });
});

describe("pool lane helpers", () => {
  function createState(playerOverrides: Partial<BalancerPlayerRecord>, issues: PlayerValidationState["issues"] = []): PlayerValidationState {
    return {
      player: createPlayer(playerOverrides),
      issues,
    };
  }

  it.each([
    ["excluded", createState({ is_in_pool: false })],
    ["needs_fix", createState({ is_in_pool: true }, [{ code: "missing_ranked_role", message: "No ranked roles configured" }])],
    ["ready", createState({ is_in_pool: true })],
  ] satisfies Array<[PoolLane, PlayerValidationState]>)("derives %s from pool membership and validation issues", (expectedLane, state) => {
    expect(derivePoolLane(state)).toBe(expectedLane);
  });

  it.each([
    ["excluded", false],
    ["needs_fix", true],
    ["ready", true],
  ] satisfies Array<[PoolLane, boolean]>)("maps a drop into %s to the correct pool membership patch", (targetLane, expectedInPool) => {
    expect(getPoolDropPatch(targetLane)).toEqual({ is_in_pool: expectedInPool });
  });

  it("auto-classifies an included roleless player back into Need Fix", () => {
    const patch = getPoolDropPatch("ready");
    const player = createPlayer({ is_in_pool: patch.is_in_pool });

    expect(derivePoolLane({ player, issues: getPlayerValidationIssues(player, null) })).toBe("needs_fix");
  });

  it("auto-classifies an included valid player into Ready", () => {
    const patch = getPoolDropPatch("needs_fix");
    const player = createPlayer({
      is_in_pool: patch.is_in_pool,
      role_entries_json: [
        {
          role: "support",
          subtype: null,
          priority: 1,
          division_number: 12,
          rank_value: 900,
          is_active: true,
        },
      ],
    });

    expect(derivePoolLane({ player, issues: getPlayerValidationIssues(player, null) })).toBe("ready");
  });
});

describe("battle tag clipboard helpers", () => {
  it("returns the primary BattleTag followed by unique non-empty smurf tags", () => {
    const registration = createRegistration({
      battle_tag: "Main#1111",
      smurf_tags_json: ["Alt#2222", " ", "Main#1111", "alt#2222", "Pocket#3333"],
    });

    expect(getRegistrationBattleTags(registration, "Fallback#0000")).toEqual([
      "Main#1111",
      "Alt#2222",
      "Pocket#3333",
    ]);
  });

  it("falls back to the player BattleTag and formats tags for clipboard", () => {
    const registration = createRegistration({
      battle_tag: null,
      smurf_tags_json: ["Practice#4444"],
    });

    const battleTags = getRegistrationBattleTags(registration, "Player#1234");

    expect(battleTags).toEqual(["Player#1234", "Practice#4444"]);
    expect(formatBattleTagsForClipboard(battleTags)).toBe("Player#1234\nPractice#4444");
  });

  it("formats smurf count labels for collapsed UI", () => {
    expect(formatSmurfCount(1)).toBe("1 smurf");
    expect(formatSmurfCount(3)).toBe("3 smurfs");
  });
});

describe("synthetic registration helpers", () => {
  it("keeps incomplete approved non-excluded registrations in the pool", () => {
    const registration = createRegistration({
      balancer_status: "incomplete",
      exclude_from_balancer: false,
    });

    expect(isRegistrationIncludedInBalancer(registration)).toBe(true);

    const player = createSyntheticPlayerFromRegistration(registration);

    expect(player.is_in_pool).toBe(true);
  });

  it("excludes registrations marked out of balancer even if status is ready", () => {
    const registration = createRegistration({
      balancer_status: "ready",
      exclude_from_balancer: true,
    });

    expect(isRegistrationIncludedInBalancer(registration)).toBe(false);

    const player = createSyntheticPlayerFromRegistration(registration);

    expect(player.is_in_pool).toBe(false);
  });

  it("derives flex only when all roles are primary", () => {
    const flexRegistration = createRegistration({
      roles: [
        {
          role: "tank",
          subrole: null,
          is_primary: true,
          priority: 0,
          rank_value: 1100,
          is_active: true,
        },
        {
          role: "support",
          subrole: null,
          is_primary: true,
          priority: 1,
          rank_value: 1200,
          is_active: true,
        },
      ],
    });
    const strictRegistration = createRegistration();

    expect(createSyntheticPlayerFromRegistration(flexRegistration).is_flex).toBe(true);
    expect(createSyntheticPlayerFromRegistration(strictRegistration).is_flex).toBe(false);
  });

  it("builds flex applications without a primary role", () => {
    const registration = createRegistration({
      roles: [
        {
          role: "tank",
          subrole: null,
          is_primary: true,
          priority: 0,
          rank_value: 1100,
          is_active: true,
        },
        {
          role: "support",
          subrole: null,
          is_primary: true,
          priority: 1,
          rank_value: 1200,
          is_active: true,
        },
      ],
    });

    const player = createSyntheticPlayerFromRegistration(registration);
    const application = createSyntheticApplicationFromRegistration(registration, player);

    expect(application.primary_role).toBeNull();
    expect(application.additional_roles_json).toEqual(["tank", "support"]);
    expect(application.player).toBe(player);
  });
});

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
  convertBalanceResponseToInternalPayload,
  createSyntheticApplicationFromRegistration,
  createSyntheticPlayerFromRegistration,
  getPlayerValidationIssues,
  isRegistrationIncludedInBalancer,
  type PlayerValidationIssue,
} from "@/app/balancer/components/workspace-helpers";
import { buildRegistrationUpdateFromPlayerPayload } from "@/app/balancer/components/useBalancerMutations";
import type {
  AdminRegistration,
  AdminRegistrationRole,
  BalancerApplication,
  BalancerPlayerRecord,
} from "@/types/balancer-admin.types";
import type { BalanceResponse, PlayerData } from "@/types/balancer.types";
import { DEFAULT_DIVISION_GRID } from "@/lib/division-grid";
import type { StatusMeta, StatusScope } from "@/types/registration.types";

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
    ready_blocked: false,
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

function createStatusMeta(
  value: string,
  scope: StatusScope,
  name: string,
  excludesFromBalancer = false,
  excludesFromReady = false
): StatusMeta {
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
    excludes_from_balancer: excludesFromBalancer,
    excludes_from_ready: excludesFromReady,
  };
}

function createRegistration(overrides: Partial<AdminRegistration> = {}): AdminRegistration {
  return {
    id: 10,
    tournament_id: 60,
    workspace_id: 3,
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
    best_rank: 900,
    roles: [
      {
        role: "support",
        subrole: null,
        is_primary: true,
        priority: 0,
        rank_value: 900,
        is_active: true,
        is_declared_active: true,
      },
      {
        role: "dps",
        subrole: null,
        is_primary: false,
        priority: 1,
        rank_value: 700,
        is_active: true,
        is_declared_active: true,
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

  it("flags a player blocked by a status-level ready gate even with fully ranked roles", () => {
    const player = createPlayer({
      role_entries_json: [
        { role: "support", subtype: null, priority: 0, division_number: 12, rank_value: 900, is_active: true },
      ],
      ready_blocked: true,
    });

    const issues = getPlayerValidationIssues(player, null);

    expect(issues.find((issue) => issue.code === "status_blocks_ready")).toBeDefined();
  });

  it("does not flag a player as ready-blocked by default", () => {
    const player = createPlayer({
      role_entries_json: [
        { role: "support", subtype: null, priority: 0, division_number: 12, rank_value: 900, is_active: true },
      ],
    });

    const issues = getPlayerValidationIssues(player, null);

    expect(issues.find((issue) => issue.code === "status_blocks_ready")).toBeUndefined();
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

  it("keeps a player whose only issue is a rank-delta warning in Ready", () => {
    const player = createPlayer({
      role_entries_json: [
        { role: "support", subtype: null, priority: 1, division_number: 12, rank_value: 900, is_active: true, ow_rank_value: 2000 },
      ],
    });
    const issues = getPlayerValidationIssues(player, null, { rank_delta_threshold: 100 });

    // The advisory rank-delta chip is still emitted as informational context...
    expect(issues.some((issue) => issue.code === "rank_delta_warning")).toBe(true);
    // ...but a rank delta on its own must not push the player into Need Fix.
    expect(derivePoolLane({ player, issues })).toBe("ready");
  });

  it("still routes a rank-delta player into Need Fix when a blocking issue is also present", () => {
    const player = createPlayer({
      role_entries_json: [
        { role: "support", subtype: null, priority: 1, division_number: 12, rank_value: 900, is_active: true, ow_rank_value: 2000 },
      ],
    });
    const application = createApplication({ primary_role: "tank", additional_roles_json: [] });
    const issues = getPlayerValidationIssues(player, application, { rank_delta_threshold: 100 });

    expect(issues.some((issue) => issue.code === "rank_delta_warning")).toBe(true);
    expect(issues.some((issue) => issue.code === "application_role_mismatch")).toBe(true);
    expect(derivePoolLane({ player, issues })).toBe("needs_fix");
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
      balancer_status_meta: createStatusMeta("incomplete", "balancer", "Incomplete"),
    });

    expect(isRegistrationIncludedInBalancer(registration)).toBe(true);

    const player = createSyntheticPlayerFromRegistration(registration);

    expect(player.is_in_pool).toBe(true);
  });

  it("excludes registrations whose current status excludes them from the pool", () => {
    const registration = createRegistration({
      balancer_status: "excluded",
      balancer_status_meta: createStatusMeta("excluded", "balancer", "Excluded", true),
    });

    expect(isRegistrationIncludedInBalancer(registration)).toBe(false);

    const player = createSyntheticPlayerFromRegistration(registration);

    expect(player.is_in_pool).toBe(false);
  });

  it("excludes registrations held by a custom status configured to exclude from the pool", () => {
    const registration = createRegistration({
      balancer_status: "injured",
      balancer_status_meta: createStatusMeta("injured", "balancer", "Injured", true),
    });

    expect(isRegistrationIncludedInBalancer(registration)).toBe(false);
  });

  it("blocks Ready when the current custom status has excludes_from_ready set, without excluding the pool", () => {
    const registration = createRegistration({
      balancer_status: "injured",
      balancer_status_meta: createStatusMeta("injured", "balancer", "Injured", false, true),
      roles: [
        {
          role: "support",
          subrole: null,
          is_primary: true,
          priority: 0,
          rank_value: 900,
          is_active: true,
        },
      ],
    });

    const player = createSyntheticPlayerFromRegistration(registration);

    expect(player.is_in_pool).toBe(true);
    expect(player.ready_blocked).toBe(true);
    expect(
      derivePoolLane({ player, issues: getPlayerValidationIssues(player, null) }),
    ).toBe("needs_fix");
  });

  it("carries the API's flex flag onto the synthetic player", () => {
    const flexRegistration = createRegistration({
      is_flex: true,
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
      is_flex: true,
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

  it("copies rank_source onto synthetic role entries", () => {
    const registration = createRegistration({
      roles: [
        {
          role: "support",
          subrole: null,
          is_primary: true,
          priority: 0,
          rank_value: 900,
          is_active: true,
          rank_source: "registration",
        },
      ],
    });

    const player = createSyntheticPlayerFromRegistration(registration);

    expect(player.role_entries_json[0]?.rank_source).toBe("registration");
  });
});

describe("registration role pass-through", () => {
  const role = (
    roleCode: "tank" | "dps" | "support",
    rank: number | null,
    ow: number | null = null,
    extra: {
      is_active?: boolean;
      is_declared_active?: boolean;
      subrole?: string | null;
      priority?: number;
    } = {},
  ): AdminRegistrationRole => ({
    role: roleCode,
    subrole: extra.subrole ?? null,
    is_primary: true,
    priority: extra.priority ?? 0,
    rank_value: rank,
    is_active: extra.is_active ?? true,
    is_declared_active: extra.is_declared_active ?? true,
    ow_rank_value: ow,
  });

  const built = (roles: AdminRegistrationRole[]) =>
    createSyntheticPlayerFromRegistration(createRegistration({ roles }), DEFAULT_DIVISION_GRID);

  // The roster engine already applied every flex rule server-side, so the
  // client copies the rows it was given instead of re-deriving them. A second
  // opinion here is exactly the drift this replaced.
  it("copies the API's resolved roles verbatim", () => {
    const player = built([role("dps", 3900, 4100), role("support", 2400, 2000, { priority: 1 })]);

    expect(player.role_entries_json.map((entry) => entry.role)).toEqual(["dps", "support"]);
    expect(player.role_entries_json.map((entry) => entry.rank_value)).toEqual([3900, 2400]);
    expect(player.role_entries_json.map((entry) => entry.ow_rank_value)).toEqual([4100, 2000]);
    expect(player.role_entries_json.map((entry) => entry.subtype)).toEqual([null, null]);
  });

  it("keeps each role's own specialization", () => {
    const player = built([
      role("dps", 3900, null, { subrole: "hitscan" }),
      role("support", 2400, null, { subrole: "main_heal", priority: 1 }),
    ]);

    expect(player.role_entries_json.map((entry) => entry.subtype)).toEqual([
      "hitscan",
      "main_heal",
    ]);
  });

  it("leaves an inactive role inactive — playability is the server's call", () => {
    const player = built([role("tank", 3100, null, { is_active: false })]);

    expect(player.role_entries_json.map((entry) => entry.is_active)).toEqual([false]);
  });

  it("carries the resolved and the declared flag separately", () => {
    // A role the organizer ticked on but the resolver could not rate: the
    // editor needs the tick, the pool needs the verdict, and collapsing the two
    // is what makes the checkbox flip itself off.
    const player = built([role("tank", null, null, { is_active: false, is_declared_active: true })]);

    expect(player.role_entries_json.map((entry) => entry.is_active)).toEqual([false]);
    expect(player.role_entries_json.map((entry) => entry.is_declared_active)).toEqual([true]);
  });

  it("keeps a rankless registration out of a balance run", () => {
    const player = built([role("dps", null)]);

    expect(
      getPlayerValidationIssues(player, null).some((issue) => issue.code === "missing_ranked_role"),
    ).toBe(true);
  });
});

describe("registration rank pin save", () => {
  // `is_active` on the entry is the resolver's "in play" verdict, so the patch
  // must carry `is_declared_active` — the organizer's checkbox — instead. This
  // fixture pins them apart on purpose: declared ON, resolved OFF.
  const roleEntries = [
    {
      role: "support" as const,
      subtype: null,
      priority: 1,
      division_number: 1,
      rank_value: 900,
      is_active: false,
      is_declared_active: true,
      ow_rank_value: null,
    },
  ];

  it("does not send pin:true when the editor pin is off", () => {
    const patch = buildRegistrationUpdateFromPlayerPayload({
      role_entries_json: roleEntries,
      is_flex: false,
    });
    expect(patch.pin).toBe(undefined);
    expect(patch.clear_pin).toBe(undefined);
  });

  it("sends pin:true when the editor pin is on", () => {
    const patch = buildRegistrationUpdateFromPlayerPayload({
      role_entries_json: roleEntries,
      is_flex: false,
      pin: true,
    });
    expect(patch.pin).toBe(true);
  });

  it("keeps roles when clear_pin is requested", () => {
    const patch = buildRegistrationUpdateFromPlayerPayload({
      role_entries_json: roleEntries,
      is_flex: false,
      clear_pin: true,
    });
    expect(patch.clear_pin).toBe(true);
    expect(patch.roles).toEqual([
      {
        role: "support",
        subrole: null,
        priority: 1,
        is_primary: true,
        rank_value: 900,
        is_active: true,
      },
    ]);
  });

  it("writes the declared flag, never the resolved one", () => {
    const patch = buildRegistrationUpdateFromPlayerPayload({
      role_entries_json: [{ ...roleEntries[0], is_active: true, is_declared_active: false }],
      is_flex: false,
    });
    expect(patch.roles?.[0]?.is_active).toBe(false);
  });
});


describe("convertBalanceResponseToInternalPayload", () => {
  const player = (overrides: Partial<PlayerData> = {}): PlayerData => ({
    uuid: "p1",
    name: "player#1234",
    assigned_rating: 3000,
    role_discomfort: 0,
    is_captain: false,
    role_preferences: ["tank", "dps"],
    all_ratings: { tank: 3000, dps: 2800 },
    all_discomforts: { tank: 0, dps: 100, support: 5000 },
    ...overrides,
  });

  const response = (roster: Record<string, PlayerData[]>): BalanceResponse =>
    ({
      teams: [
        {
          id: 1,
          name: "player#1234",
          average_mmr: 3000,
          rating_variance: 0,
          total_discomfort: 0,
          max_discomfort: 0,
          roster,
        },
      ],
      statistics: {},
    }) as unknown as BalanceResponse;

  it("re-keys the solver's canonical roster codes onto the editor's buckets", () => {
    // The solver keys the response by the tournament roster shape's slot codes,
    // so a run whose roster arrives as tank/dps/support must still land in the
    // Tank/Damage/Support buckets the editor and result_json use.
    const payload = convertBalanceResponseToInternalPayload(
      response({ tank: [player({ uuid: "t" })], dps: [player({ uuid: "d" })], support: [player({ uuid: "s" })] }),
    );

    const roster = payload.teams[0].roster;
    expect(roster.Tank.map((entry) => entry.uuid)).toEqual(["t"]);
    expect(roster.Damage.map((entry) => entry.uuid)).toEqual(["d"]);
    expect(roster.Support.map((entry) => entry.uuid)).toEqual(["s"]);
  });

  it("re-keys the per-role player maps the editor compares against roster keys", () => {
    const payload = convertBalanceResponseToInternalPayload(response({ tank: [player()] }));

    const entry = payload.teams[0].roster.Tank[0];
    expect(entry.role_preferences).toEqual(["Tank", "Damage"]);
    expect(entry.all_ratings).toEqual({ Tank: 3000, Damage: 2800 });
    expect(entry.all_discomforts).toEqual({ Tank: 0, Damage: 100, Support: 5000 });
  });

  it("keeps display-name payloads unchanged", () => {
    // Saved balances and pre-roster-shape runs carry the display names already.
    const legacy = player({
      role_preferences: ["Damage"],
      all_ratings: { Damage: 2800 },
      all_discomforts: { Damage: 0 },
    });

    const payload = convertBalanceResponseToInternalPayload(response({ Damage: [legacy] }));

    const entry = payload.teams[0].roster.Damage[0];
    expect(entry.role_preferences).toEqual(["Damage"]);
    expect(entry.all_ratings).toEqual({ Damage: 2800 });
  });

  it("normalizes benched players the same way", () => {
    const benched = { ...response({}), benched_players: [player({ uuid: "b" })] };

    const payload = convertBalanceResponseToInternalPayload(benched);

    expect(payload.benched_players?.[0].all_ratings).toEqual({ Tank: 3000, Damage: 2800 });
  });
});

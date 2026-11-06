import { describe, expect, it, vi } from "vitest";

import {
  derivePoolLane,
  formatHandlesForClipboard,
  getPoolDropPatch,
  type PlayerValidationState,
  type PoolLane,
} from "@/components/balancer/balancer-page-helpers";
import {
  buildVariantFromSavedBalance,
  convertBalanceResponseToInternalPayload,
  createSyntheticApplicationFromRegistration,
  createSyntheticPlayerFromRegistration as createSynthetic,
  fetchPlayerRankHistoryPreview,
  getRegistrationHandles,
  getPlayerValidationIssues as validationIssues,
  isRegistrationIncludedInBalancer,
  type PlayerValidationIssue,
  type SlotLabeler,
} from "@/components/balancer/workspace-helpers";
import { buildRegistrationUpdateFromPlayerPayload } from "@/components/balancer/registration-update-payload";
import type {
  AdminRegistration,
  AdminRegistrationRole,
  BalancerApplication,
  BalancerPlayerRecord,
} from "@/types/balancer-admin.types";
import type { BalanceResponse, PlayerData } from "@/types/balancer.types";
import { OW_REFERENCE_GRID } from "@/disciplines/overwatch/ladder/ow-reference-grid";
import { apiFetch } from "@/lib/api/fetch";
import { slotLabel } from "@/lib/roster/ontology";
import balancerAdminService from "@/services/balancer-admin.service";
import userService from "@/services/user.service";
import { LOL_METADATA, OW_METADATA } from "@/test/discipline-metadata";
import type { StatusMeta, StatusScope } from "@/types/registration.types";
import type { DivisionGrid } from "@/types/workspace.types";

vi.mock("@/lib/api/fetch", () => ({ apiFetch: vi.fn() }));

// The helpers take the owner's grid and role names. Most of this file pins Overwatch behavior, so it reads them
// through these two OW-bound entry points; the League cases below pass League's own.
const owLabel: SlotLabeler = (code) => slotLabel(OW_METADATA, code, "Flex");
const lolLabel: SlotLabeler = (code) => slotLabel(LOL_METADATA, code, "Flex");

function getPlayerValidationIssues(
  player: BalancerPlayerRecord,
  application: BalancerApplication | null,
  workspaceConfig?: { rank_delta_threshold: number | null } | null,
) {
  return validationIssues(player, application, workspaceConfig ?? null, OW_REFERENCE_GRID, owLabel);
}

function createSyntheticPlayerFromRegistration(
  registration: AdminRegistration,
  grid: DivisionGrid = OW_REFERENCE_GRID,
  identityProvider: string | null = "battlenet",
) {
  return createSynthetic(registration, grid, identityProvider);
}

function createPlayer(overrides: Partial<BalancerPlayerRecord>): BalancerPlayerRecord {
  return {
    id: 1,
    tournament_id: 60,
    application_id: 10,
    identity: "player#1234",
    identity_key: "player#1234",
    additional_handles: [],
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
    identity: "player#1234",
    identity_key: "player#1234",
    additional_handles: [],
    twitch_nick: null,
    discord_nick: null,
    stream_pov: false,
    last_tournament_text: null,
    primary_role: "support",
    additional_roles_json: ["damage"],
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
    primary_handle: "player#1234",
    source: "manual",
    source_record_key: null,
    answers: {},
    form_version_id: 5,
    form_version_stale: false,
    best_rank: 900,
    roles: [
      { role: {dimension: "player_role", role: "support"}, is_primary: true,
      priority: 0,
      rank_value: 900,
      is_active: true,
      is_declared_active: true, },
      { role: {dimension: "player_role", role: "damage"}, is_primary: false,
      priority: 1,
      rank_value: 700,
      is_active: true,
      is_declared_active: true, },
    ],
    admin_notes: null,
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
  it("does not flag support main-heal plus damage as mismatch", () => {
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
          role: "damage",
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
      additional_roles_json: ["damage"],
    });

    const issues = getPlayerValidationIssues(player, application);

    expect(issues.find((issue) => issue.code === "application_role_mismatch")).toBeUndefined();
  });

  it("does not flag missing optional secondary role when primary role matches", () => {
    const player = createPlayer({
      role_entries_json: [
        {
          role: "damage",
          subtype: "hitscan",
          priority: 1,
          division_number: 12,
          rank_value: 900,
          is_active: true,
        },
      ],
    });
    const application = createApplication({
      primary_role: "damage",
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
          role: "damage",
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
      additional_roles_json: ["damage"],
    });

    const issues = getPlayerValidationIssues(player, application);

    expect(issues.find((issue) => issue.code === "application_role_mismatch")).toBeUndefined();
  });

  it("emits a rank-delta warning for every role that exceeds the threshold", () => {
    const player = createPlayer({
      role_entries_json: [
        { role: "support", subtype: null, priority: 0, division_number: null, rank_value: 900, is_active: true, ow_rank_value: 2000 },
        { role: "damage", subtype: null, priority: 1, division_number: null, rank_value: 700, is_active: true, ow_rank_value: 1900 },
      ],
    });

    const issues = getPlayerValidationIssues(player, null, { rank_delta_threshold: 100 });
    const deltaIssues = issues.filter(
      (issue): issue is Extract<PlayerValidationIssue, { code: "rank_delta_warning" }> =>
        issue.code === "rank_delta_warning",
    );

    expect(deltaIssues.length).toBe(2);
    // Worst delta first: damage (Δ1200) before support (Δ1100).
    expect(deltaIssues.map((issue) => issue.role).join(",")).toBe("damage,support");
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
    ["needs_fix", createState({ is_in_pool: true }, [{ code: "missing_ranked_role" }])],
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

describe("game handle helpers", () => {
  it("returns the primary handle followed by unique non-empty extra accounts", () => {
    const registration = createRegistration({
      answers: {
        identity_battlenet: ["Main#1111", " ", "Main#1111", "Alt#2222", "alt#2222", "Pocket#3333"],
      },
    });

    expect(getRegistrationHandles(registration, "battlenet", "Fallback#0000")).toEqual([
      "Main#1111",
      "Alt#2222",
      "Pocket#3333",
    ]);
  });

  it("falls back to the player's handle when the row answered none for the game's provider", () => {
    const registration = createRegistration({ answers: {} });

    const handles = getRegistrationHandles(registration, "battlenet", "Player#1234");

    expect(handles).toEqual(["Player#1234"]);
    expect(formatHandlesForClipboard(handles)).toBe("Player#1234");
  });

  it("reads the answer of the owner game's provider only", () => {
    const registration = createRegistration({
      answers: { identity_battlenet: ["Main#1111", "Alt#2222"], identity_riot: ["Faker#KR1"] },
    });

    expect(getRegistrationHandles(registration, "riot", "Fallback")).toEqual(["Faker#KR1"]);
    // A game with no identity provider has no handle answer to read.
    expect(getRegistrationHandles(registration, null, "Fallback")).toEqual(["Fallback"]);
  });
});

describe("synthetic player identity", () => {
  it("names a League registration by its Riot ID answers, extras apart, keyed by the Riot grammar", () => {
    const registration = createRegistration({
      primary_handle: "Faker # KR1",
      answers: { identity_riot: ["Faker # KR1", "Alt#EUW"], identity_battlenet: ["Wrong#1111"] },
    });

    const player = createSyntheticPlayerFromRegistration(registration, OW_REFERENCE_GRID, "riot");

    expect(player.identity).toBe("Faker # KR1");
    expect(player.identity_key).toBe("faker#kr1");
    expect(player.additional_handles).toEqual(["Alt#EUW"]);
  });

  it("keeps a registration with no game identity nameable by its own name", () => {
    const registration = createRegistration({ primary_handle: null, display_name: "Walk In", answers: {} });

    const player = createSyntheticPlayerFromRegistration(registration, OW_REFERENCE_GRID, null);
    const application = createSyntheticApplicationFromRegistration(registration, player, null);

    expect(player).toMatchObject({ identity: "Walk In", identity_key: "walk in", additional_handles: [] });
    expect(application).toMatchObject({ identity: "Walk In", additional_handles: [] });
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
        { role: {dimension: "player_role", role: "support"}, is_primary: true,
        priority: 0,
        rank_value: 900,
        is_active: true, },
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
        { role: {dimension: "player_role", role: "tank"}, is_primary: true,
        priority: 0,
        rank_value: 1100,
        is_active: true, },
        { role: {dimension: "player_role", role: "support"}, is_primary: true,
        priority: 1,
        rank_value: 1200,
        is_active: true, },
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
        { role: {dimension: "player_role", role: "tank"}, is_primary: true,
        priority: 0,
        rank_value: 1100,
        is_active: true, },
        { role: {dimension: "player_role", role: "support"}, is_primary: true,
        priority: 1,
        rank_value: 1200,
        is_active: true, },
      ],
    });

    const player = createSyntheticPlayerFromRegistration(registration);
    const application = createSyntheticApplicationFromRegistration(registration, player, "battlenet");

    expect(application.primary_role).toBeNull();
    expect(application.additional_roles_json).toEqual(["tank", "support"]);
    expect(application.player).toBe(player);
  });

  it("copies rank_source onto synthetic role entries", () => {
    const registration = createRegistration({
      roles: [
        { role: {dimension: "player_role", role: "support"}, is_primary: true,
        priority: 0,
        rank_value: 900,
        is_active: true,
        rank_source: "registration", },
      ],
    });

    const player = createSyntheticPlayerFromRegistration(registration);

    expect(player.role_entries_json[0]?.rank_source).toBe("registration");
  });
});

describe("registration role pass-through", () => {
  const role = (
    roleCode: "tank" | "damage" | "support",
    rank: number | null,
    ow: number | null = null,
    extra: {
      is_active?: boolean;
      is_declared_active?: boolean;
      subrole?: string | null;
      priority?: number;
    } = {},
  ): AdminRegistrationRole => ({
    role: { dimension: "player_role", role: extra.subrole ? `${roleCode}_${extra.subrole}` : roleCode, parent: extra.subrole ? roleCode : null },
    is_primary: true,
    priority: extra.priority ?? 0,
    rank_value: rank,
    is_active: extra.is_active ?? true,
    is_declared_active: extra.is_declared_active ?? true,
    ow_rank_value: ow,
  });

  const built = (roles: AdminRegistrationRole[]) =>
    createSyntheticPlayerFromRegistration(createRegistration({ roles }), OW_REFERENCE_GRID);

  // The roster engine already applied every flex rule server-side, so the
  // client copies the rows it was given instead of re-deriving them. A second
  // opinion here is exactly the drift this replaced.
  it("copies the API's resolved roles verbatim", () => {
    const player = built([role("damage", 3900, 4100), role("support", 2400, 2000, { priority: 1 })]);

    expect(player.role_entries_json.map((entry) => entry.role)).toEqual(["damage", "support"]);
    expect(player.role_entries_json.map((entry) => entry.rank_value)).toEqual([3900, 2400]);
    expect(player.role_entries_json.map((entry) => entry.ow_rank_value)).toEqual([4100, 2000]);
    expect(player.role_entries_json.map((entry) => entry.subtype)).toEqual([null, null]);
  });

  it("keeps each role's own specialization", () => {
    const player = built([
      role("damage", 3900, null, { subrole: "hitscan" }),
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
    const player = built([role("damage", null)]);

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

  it("edits a LoL registration without converting its position into an OW role", () => {
    const registration = createRegistration({
      roles: [
        {
          role: { dimension: "position", role: "support" },
          is_primary: true,
          priority: 0,
          rank_value: 100,
          is_active: true,
          is_declared_active: true,
          ow_rank_value: null
        }
      ]
    });
    const player = createSyntheticPlayerFromRegistration(registration);
    const patch = buildRegistrationUpdateFromPlayerPayload(
      {
        role_entries_json: player.role_entries_json.map((entry) => ({
          ...entry,
          rank_value: 1500
        })),
        is_flex: player.is_flex
      },
      registration.roles,
      "position"
    );
    expect(patch.roles?.[0]).toMatchObject({
      role: { dimension: "position", role: "support" },
      rank_value: 1500
    });
  });

  it("writes a League registration that has no roles yet in the game's rated dimension", () => {
    const patch = buildRegistrationUpdateFromPlayerPayload(
      {
        role_entries_json: [{ ...roleEntries[0], role: "jungle" }, { ...roleEntries[0], role: "mid", priority: 2 }],
        is_flex: false
      },
      [],
      "position"
    );
    expect(patch.roles?.map((entry) => entry.role)).toEqual([
      { dimension: "position", role: "jungle" },
      { dimension: "position", role: "mid" }
    ]);
  });

  it("uses the rated dimension of the owner over a stale existing role's", () => {
    const registration = createRegistration({
      roles: [
        {
          role: { dimension: "legacy", role: "support" },
          is_primary: true,
          priority: 0,
          rank_value: 100,
          is_active: true,
          is_declared_active: true,
          ow_rank_value: null
        }
      ]
    });
    const patch = buildRegistrationUpdateFromPlayerPayload(
      { role_entries_json: roleEntries, is_flex: false },
      registration.roles,
      "position"
    );
    expect(patch.roles?.[0]?.role).toEqual({ dimension: "position", role: "support" });
  });

  it("falls back to the existing roles' dimension while the owner's roles load", () => {
    const registration = createRegistration({
      roles: [
        {
          role: { dimension: "position", role: "support" },
          is_primary: true,
          priority: 0,
          rank_value: 100,
          is_active: true,
          is_declared_active: true,
          ow_rank_value: null
        }
      ]
    });
    const patch = buildRegistrationUpdateFromPlayerPayload(
      { role_entries_json: roleEntries, is_flex: false },
      registration.roles,
      null
    );
    expect(patch.roles?.[0]?.role).toEqual({ dimension: "position", role: "support" });
  });

  it("refuses to guess a dimension for a role write when neither the game nor the registration names one", () => {
    expect(() =>
      buildRegistrationUpdateFromPlayerPayload(
        { role_entries_json: roleEntries, is_flex: false },
        [],
        null
      )
    ).toThrow(/rated role dimension/);
    // A write that touches no role entry needs no dimension.
    expect(
      buildRegistrationUpdateFromPlayerPayload({ admin_notes: "n" } as never, [], null)
    ).toEqual({ admin_notes: "n" });
  });

  it("carries a role's saved character picks as `top_characters`, never the persisted-form spelling", () => {
    const registration = createRegistration({
      roles: [
        {
          role: { dimension: "position", role: "mid" },
          is_primary: true,
          priority: 0,
          rank_value: 100,
          is_active: true,
          is_declared_active: true,
          top_characters: ["ahri", "syndra"],
          ow_rank_value: null
        }
      ]
    });
    const player = createSyntheticPlayerFromRegistration(registration);
    const patch = buildRegistrationUpdateFromPlayerPayload(
      { role_entries_json: player.role_entries_json, is_flex: player.is_flex },
      registration.roles,
      "position"
    );
    expect(patch.roles?.[0]).toMatchObject({ top_characters: ["ahri", "syndra"] });
    expect(patch.roles?.[0]).not.toHaveProperty("top_heroes");
  });

  it("does not send pin:true when the editor pin is off", () => {
    const patch = buildRegistrationUpdateFromPlayerPayload({
      role_entries_json: roleEntries,
      is_flex: false,
    }, undefined, "player_role");
    expect(patch.pin).toBe(undefined);
    expect(patch.clear_pin).toBe(undefined);
  });

  it("sends pin:true when the editor pin is on", () => {
    const patch = buildRegistrationUpdateFromPlayerPayload({
      role_entries_json: roleEntries,
      is_flex: false,
      pin: true,
    }, undefined, "player_role");
    expect(patch.pin).toBe(true);
  });

  it("keeps roles when clear_pin is requested", () => {
    const patch = buildRegistrationUpdateFromPlayerPayload({
      role_entries_json: roleEntries,
      is_flex: false,
      clear_pin: true,
    }, undefined, "player_role");
    expect(patch.clear_pin).toBe(true);
    expect(patch.roles).toEqual([
      { role: {dimension: "player_role", role: "support"}, priority: 1,
      is_primary: true,
      rank_value: 900,
      is_active: true, },
    ]);
  });

  it("writes the declared flag, never the resolved one", () => {
    const patch = buildRegistrationUpdateFromPlayerPayload({
      role_entries_json: [{ ...roleEntries[0], is_active: true, is_declared_active: false }],
      is_flex: false,
    }, undefined, "player_role");
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
    role_preferences: ["tank", "damage"],
    all_ratings: { tank: 3000, damage: 2800 },
    all_discomforts: { tank: 0, damage: 100, support: 5000 },
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

  it("keys the editor's buckets by the solver's lower-case slot codes", () => {
    // The solver keys the response by the tournament roster shape's slot codes, and the editor, result_json and
    // the save endpoint speak the same codes: tank/damage/support stay tank/damage/support.
    const payload = convertBalanceResponseToInternalPayload(
      response({ tank: [player({ uuid: "t" })], damage: [player({ uuid: "d" })], support: [player({ uuid: "s" })] }),
    );

    const roster = payload.teams[0].roster;
    expect(roster.tank.map((entry) => entry.uuid)).toEqual(["t"]);
    expect(roster.damage.map((entry) => entry.uuid)).toEqual(["d"]);
    expect(roster.support.map((entry) => entry.uuid)).toEqual(["s"]);
  });

  it("preserves format findings from the solver through the save request", async () => {
    const generated = response({ tank: [player()] });
    const findings = {
      format_violations: ["role_below_hard_min"],
      format_advisories: ["role_below_recommended_min"],
    };
    Object.assign(generated.teams[0], findings);
    vi.mocked(apiFetch).mockResolvedValueOnce(new Response("{}"));

    await balancerAdminService.saveBalance(17, 9, {
      config_json: null,
      result_json: convertBalanceResponseToInternalPayload(generated),
    });

    expect(apiFetch).toHaveBeenLastCalledWith("/api/v1/balancer/tournaments/17/balance", {
      method: "PUT",
      query: { formation_node_id: 9 },
      body: {
        config_json: null,
        result_json: expect.objectContaining({
          teams: [expect.objectContaining(findings)],
        }),
      },
    });
  });

  it("keeps the per-role player maps keyed like the roster buckets", () => {
    const payload = convertBalanceResponseToInternalPayload(response({ tank: [player()] }));

    const entry = payload.teams[0].roster.tank[0];
    expect(entry.role_preferences).toEqual(["tank", "damage"]);
    expect(entry.all_ratings).toEqual({ tank: 3000, damage: 2800 });
    expect(entry.all_discomforts).toEqual({ tank: 0, damage: 100, support: 5000 });
  });

  it("re-keys display-name payloads onto the slot codes", () => {
    // The solver echoes the spelling of the mask it was given; runs from before the roster shape say `Damage`.
    const legacy = player({
      role_preferences: ["Damage"],
      all_ratings: { Damage: 2800 },
      all_discomforts: { Damage: 0 },
    });

    const payload = convertBalanceResponseToInternalPayload(response({ Damage: [legacy] }));

    const entry = payload.teams[0].roster.damage[0];
    expect(entry.role_preferences).toEqual(["damage"]);
    expect(entry.all_ratings).toEqual({ damage: 2800 });
  });

  it("normalizes benched players the same way", () => {
    const benched = { ...response({}), benched_players: [player({ uuid: "b" })] };

    const payload = convertBalanceResponseToInternalPayload(benched);

    expect(payload.benched_players?.[0].all_ratings).toEqual({ tank: 3000, damage: 2800, });
  });

  it("keeps every bucket of another game: a League balance loses no player", () => {
    const seats = ["top", "jungle", "mid", "bot", "support"];
    const payload = convertBalanceResponseToInternalPayload(
      response(
        Object.fromEntries(
          seats.map((seat) => [seat, [player({ uuid: seat, role_preferences: [seat], all_ratings: { [seat]: 2500 } })]]),
        ),
      ),
    );

    const roster = payload.teams[0].roster;
    expect(Object.keys(roster)).toEqual(seats);
    expect(Object.values(roster).flat().map((entry) => entry.uuid)).toEqual(seats);
    expect(roster.jungle[0].role_preferences).toEqual(["jungle"]);
  });

  it("keeps the open slot and a bucket the game does not know instead of dropping their players", () => {
    const payload = convertBalanceResponseToInternalPayload(
      response({ flex: [player({ uuid: "f" })], retired: [player({ uuid: "r" })] }),
    );

    expect(Object.values(payload.teams[0].roster).flat().map((entry) => entry.uuid)).toEqual(["f", "r"]);
  });
});

describe("buildVariantFromSavedBalance", () => {
  it("re-keys a balance saved under display names; both spellings are one bucket on every team", () => {
    const seat = (uuid: string): PlayerData => ({
      uuid,
      name: uuid,
      assigned_rating: 2000,
      role_discomfort: 0,
      is_captain: false,
      role_preferences: ["Tank", "Damage"],
      all_ratings: { Tank: 2000 },
    });
    const saved = {
      id: 5,
      config_json: null,
      result_json: {
        teams: [
          { id: 1, name: "A", average_mmr: 1, roster: { Tank: [seat("a")], tank: [seat("b")], Flex: [] } },
          { id: 2, name: "B", average_mmr: 1, roster: { Tank: [seat("c")] } },
        ],
        benched_players: [seat("x")],
      },
    } as unknown as Parameters<typeof buildVariantFromSavedBalance>[0];

    const { payload } = buildVariantFromSavedBalance(saved);

    expect(payload.teams[0].roster.tank.map((entry) => entry.uuid)).toEqual(["a", "b"]);
    expect(Object.keys(payload.teams[1].roster)).toEqual(["tank", "flex"]);
    expect(payload.teams[0].roster.tank[0].role_preferences).toEqual(["tank", "damage"]);
    expect(payload.teams[0].roster.tank[0].all_ratings).toEqual({ tank: 2000 });
    expect(payload.benched_players?.[0].role_preferences).toEqual(["tank", "damage"]);
  });
});

describe("a League roster", () => {
  const NO_TIERS: DivisionGrid = { tiers: [] };
  const entry = (role: string, rank: number | null, extra: Partial<BalancerPlayerRecord["role_entries_json"][number]> = {}) => ({
    role,
    subtype: null,
    priority: 1,
    division_number: null,
    rank_value: rank,
    is_active: true,
    is_declared_active: true,
    ow_rank_value: null,
    ...extra,
  });

  it("matches the application's positions against the player's own", () => {
    const player = createPlayer({ role_entries_json: [entry("top", 900), entry("jungle", 900, { priority: 2 })] });
    const application = createApplication({ primary_role: "Top", additional_roles_json: ["jungle"] });

    expect(validationIssues(player, application, null, NO_TIERS, lolLabel)).toEqual([]);
  });

  it("names a position mismatch in League's own roles", () => {
    const player = createPlayer({ role_entries_json: [entry("bot", 900)] });
    const application = createApplication({ primary_role: "mid", additional_roles_json: [] });

    const [issue] = validationIssues(player, application, null, NO_TIERS, lolLabel);

    expect(issue).toMatchObject({
      code: "application_role_mismatch",
      applicationRoleCodes: ["mid"],
      playerRoleCodes: ["bot"],
      applicationRoleLabels: ["Mid"],
      playerRoleLabels: ["Bot"],
    });
  });

  it("quotes a rank-delta warning with the position's own name", () => {
    const player = createPlayer({ role_entries_json: [entry("jungle", 2000, { ow_rank_value: 2500 })] });

    const [issue] = validationIssues(player, null, { rank_delta_threshold: 100 }, NO_TIERS, lolLabel);

    // Off the grid, the warning quotes the raw ranks.
    expect(issue).toMatchObject({
      code: "rank_delta_warning",
      role: "jungle",
      roleLabel: "Jungle",
      currentLabel: "2000",
      owLabel: "2500",
      delta: 500,
    });
  });

  it("reads the owner game's roles from history, in declared order, and never a flex or unranked participation", async () => {
    const tournament = (id: number, discipline: string, role: { dimension: string; role: string } | null, rank: number | null) => ({
      id,
      name: `T${id}`,
      discipline,
      role,
      division_grid_version_id: null,
      players: [{ user_id: 7, rank }],
    });
    const byName = vi.spyOn(userService, "getUserByName").mockResolvedValue({ id: 7 } as never);
    const tournaments = vi.spyOn(userService, "getUserTournaments").mockResolvedValue({
      results: [
        // The newest jungle event recorded no rank: the role's rank comes from the one before it.
        tournament(5, "lol", { dimension: "position", role: "jungle" }, null),
        tournament(3, "lol", { dimension: "position", role: "jungle" }, 2400),
        tournament(2, "lol", { dimension: "position", role: "top" }, 1800),
        tournament(1, "lol", null, 3000),
        tournament(4, "overwatch", { dimension: "player_role", role: "tank" }, 4000),
      ],
      division_grid_versions: [],
    } as never);

    try {
      const preview = await fetchPlayerRankHistoryPreview(
        "Name#EUW",
        null,
        NO_TIERS,
        undefined,
        null,
        "lol",
        ["top", "jungle", "mid", "bot", "support"],
        "position",
      );

      expect(preview?.entries.map((row) => [row.role, row.rank_value])).toEqual([
        ["top", 1800],
        ["jungle", 2400],
      ]);
      expect(preview?.average_rank_value).toBe(2100);
    } finally {
      byName.mockRestore();
      tournaments.mockRestore();
    }
  });

  describe("the balancer-history step", () => {
    const LOL_ROLES = ["top", "jungle", "mid", "bot", "support"];
    const entry = (tournament_id: number, dimension: string, role: string, rank_value: number) => ({
      tournament_id,
      tournament_name: `T${tournament_id}`,
      role: { dimension, role },
      rank_value,
    });

    it("asks for the previewed game's history in the chosen workspace and keeps its own rank", async () => {
      const byName = vi.spyOn(userService, "getUserByName").mockResolvedValue({ id: 7 } as never);
      const history = vi
        .spyOn(balancerAdminService, "getUserBalancerRankHistory")
        .mockResolvedValue([entry(9, "position", "support", 2200), entry(8, "position", "support", 1000)]);
      const tournaments = vi
        .spyOn(userService, "getUserTournaments")
        .mockResolvedValue({ results: [], division_grid_versions: [] } as never);

      try {
        const preview = await fetchPlayerRankHistoryPreview(
          "Name#EUW", null, NO_TIERS, 3, null, "lol", LOL_ROLES, "position",
        );

        expect(history).toHaveBeenCalledWith(7, 3, "lol");
        expect(preview?.entries).toMatchObject([
          { role: "support", rank_value: 2200, tournament_id: 9, source: "balancer" },
        ]);
      } finally {
        byName.mockRestore();
        history.mockRestore();
        tournaments.mockRestore();
      }
    });

    it("never lets another game's rank under the same role code stand in for a position, or hide its fallback", async () => {
      const byName = vi.spyOn(userService, "getUserByName").mockResolvedValue({ id: 7 } as never);
      // A response that still carries Overwatch's `support` (same code, other dimension).
      const history = vi
        .spyOn(balancerAdminService, "getUserBalancerRankHistory")
        .mockResolvedValue([entry(9, "player_role", "support", 4100)]);
      const tournaments = vi.spyOn(userService, "getUserTournaments").mockResolvedValue({
        results: [
          { id: 5, name: "T5", discipline: "lol", role: { dimension: "position", role: "support" }, division_grid_version_id: null, players: [{ user_id: 7, rank: 1700 }] },
        ],
        division_grid_versions: [],
      } as never);

      try {
        const preview = await fetchPlayerRankHistoryPreview(
          "Name#EUW", null, NO_TIERS, 3, null, "lol", LOL_ROLES, "position",
        );

        // The League analytics rank fills `support`; Overwatch's 4100 is nowhere in the preview.
        expect(preview?.entries).toMatchObject([{ role: "support", rank_value: 1700, source: "analytics" }]);
      } finally {
        byName.mockRestore();
        history.mockRestore();
        tournaments.mockRestore();
      }
    });
  });
});

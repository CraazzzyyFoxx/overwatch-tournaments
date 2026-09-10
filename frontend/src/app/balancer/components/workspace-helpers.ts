import {
  AdminRegistration,
  BalancerApplication,
  BalancerPlayerExportResponse,
  BalancerPlayerRecord,
  BalancerPlayerRoleEntry,
  BalancerRoleCode,
  BalancerRosterKey,
  InternalBalancePayload,
  InternalBalancePlayer,
  RegistrationRankAutofillResponse,
  SavedBalance
} from "@/types/balancer-admin.types";
import { BalanceResponse, BalancerConfig, PlayerData } from "@/types/balancer.types";
import { playerRoleSlotCode } from "@/lib/player-role";
import { UserRoleType } from "@/types/user.types";
import type { DivisionGrid, DivisionGridVersion } from "@/types/workspace.types";
import { DEFAULT_DIVISION_GRID, getDivisionLabel, resolveDivisionFromRank } from "@/lib/division-grid";
import userService from "@/services/user.service";
import balancerAdminService from "@/services/balancer-admin.service";
import { DivisionGridNormalizer } from "@/lib/division-grid-normalizer";

const ROLE_ORDER: BalancerRoleCode[] = ["tank", "dps", "support"];
const API_ROLE_KEYS: Record<BalancerRoleCode, "Tank" | "Damage" | "Support"> = {
  tank: "Tank",
  dps: "Damage",
  support: "Support"
};

export type BalanceVariant = {
  id: string;
  label: string;
  payload: InternalBalancePayload;
  source: "saved" | "generated" | "imported";
  config?: BalancerConfig | null;
  /** Number of pool players excluded from this run due to validation issues */
  skippedCount?: number;
  /**
   * Payload edited in the editor since the variant was built. Only meaningful for
   * `source: "saved"`, where it separates "this is exactly what is persisted" from
   * "there is new work to save/export".
   */
  dirty?: boolean;
};

export type PlayerValidationIssue =
  | {
      code: "missing_ranked_role";
      message: string;
    }
  | {
      code: "application_role_mismatch";
      message: string;
      applicationRoleCodes: BalancerRoleCode[];
      playerRoleCodes: BalancerRoleCode[];
    }
  | {
      code: "rank_delta_warning";
      message: string;
      role: BalancerRoleCode;
      /** Division number of the balancer rank, in the workspace grid (for the icon). */
      currentDivision: number | null;
      /** Division number of the OW2 rank converted into the workspace grid (for the icon). */
      owDivision: number | null;
      /** Absolute rank-point delta between the two. */
      delta: number;
    }
  | {
      code: "status_blocks_ready";
      message: string;
    };

export type PlayerRankHistoryPreviewEntry = {
  role: BalancerRoleCode;
  rank_value: number;
  /** Division number in the workspace-default (target) grid — after cross-version normalisation. */
  division_number: number | null;
  /** Division number in the source tournament's own grid — before normalisation. */
  original_division_number: number | null;
  tournament_id: number | null;
  tournament_name: string | null;
  source_role: UserRoleType | null;
  tournament_grid_version: DivisionGridVersion | null;
  /** Where this entry came from: balancer history or analytics (getUserTournaments). */
  source: "balancer" | "analytics";
};

export type PlayerRankHistoryPreview = {
  user_id: number;
  entries: PlayerRankHistoryPreviewEntry[];
  average_rank_value: number | null;
};

export const ROLE_LABELS: Record<BalancerRoleCode, string> = {
  tank: "Tank",
  dps: "Damage",
  support: "Support"
};

function sortRoleEntries(entries: BalancerPlayerRoleEntry[]): BalancerPlayerRoleEntry[] {
  return [...entries].sort((a, b) => a.priority - b.priority);
}

export function isRoleEntryActive(entry: BalancerPlayerRoleEntry): boolean {
  return entry.is_active;
}

export function getActiveRoleEntries(
  entries: BalancerPlayerRoleEntry[]
): BalancerPlayerRoleEntry[] {
  return sortRoleEntries(entries).filter((entry) => isRoleEntryActive(entry));
}

function playerHasRankedRole(player: BalancerPlayerRecord): boolean {
  return player.role_entries_json.some(
    (entry) => isRoleEntryActive(entry) && entry.rank_value !== null
  );
}

function normalizeApplicationRole(role: string | null | undefined): BalancerRoleCode | null {
  const normalized = role?.trim().toLowerCase();

  if (!normalized) {
    return null;
  }

  if (normalized === "tank") {
    return "tank";
  }

  if (normalized === "dps" || normalized === "damage") {
    return "dps";
  }

  if (normalized === "support") {
    return "support";
  }

  return null;
}

function uniqueRoleCodesInOrder(roleCodes: Iterable<BalancerRoleCode>): BalancerRoleCode[] {
  const seen = new Set<BalancerRoleCode>();
  const ordered: BalancerRoleCode[] = [];

  for (const roleCode of roleCodes) {
    if (seen.has(roleCode)) {
      continue;
    }
    seen.add(roleCode);
    ordered.push(roleCode);
  }

  return ordered;
}

function formatRoleCodes(roleCodes: Iterable<BalancerRoleCode>): string {
  const orderedRoleCodes = uniqueRoleCodesInOrder(roleCodes);

  if (orderedRoleCodes.length === 0) {
    return "None";
  }

  return orderedRoleCodes.map((roleCode) => ROLE_LABELS[roleCode]).join(" / ");
}

function getPlayerRoleCodes(player: BalancerPlayerRecord): BalancerRoleCode[] {
  return uniqueRoleCodesInOrder(
    getActiveRoleEntries(player.role_entries_json).map((entry) => entry.role)
  );
}

function getApplicationRoleCodes(
  application: BalancerApplication | null | undefined
): BalancerRoleCode[] {
  if (!application) {
    return [];
  }

  return uniqueRoleCodesInOrder(
    [application.primary_role, ...application.additional_roles_json]
      .map((role) => normalizeApplicationRole(role))
      .filter((role): role is BalancerRoleCode => role !== null)
  );
}

export function buildPlayerSearchIndex(
  player: BalancerPlayerRecord,
  application: BalancerApplication | null | undefined
): string {
  const roleEntries = sortRoleEntries(player.role_entries_json);
  const activeRoleEntries = roleEntries.filter((entry) => isRoleEntryActive(entry));
  const playerRoleLabels = activeRoleEntries.map((entry) => ROLE_LABELS[entry.role]);
  const playerRoleCodes = activeRoleEntries.map((entry) => entry.role);
  const divisions = activeRoleEntries
    .map((entry) => entry.division_number)
    .filter((division): division is number => division !== null);
  const applicationRoleLabels = getApplicationRoleCodes(application).map(
    (roleCode) => ROLE_LABELS[roleCode]
  );

  return [
    player.battle_tag,
    player.battle_tag_normalized,
    player.is_flex ? "flex" : "",
    playerRoleLabels.join(" "),
    playerRoleCodes.join(" "),
    divisions.join(" "),
    application?.battle_tag ?? "",
    applicationRoleLabels.join(" ")
  ]
    .join(" ")
    .trim()
    .toLowerCase();
}

export function buildApplicationSearchIndex(application: BalancerApplication): string {
  const applicationRoleLabels = getApplicationRoleCodes(application).map(
    (roleCode) => ROLE_LABELS[roleCode]
  );

  return [
    application.battle_tag,
    application.battle_tag_normalized,
    application.discord_nick ?? "",
    application.twitch_nick ?? "",
    applicationRoleLabels.join(" ")
  ]
    .join(" ")
    .trim()
    .toLowerCase();
}

function isFlexApplication(
  application: BalancerApplication | null | undefined,
  applicationRoleCodes: BalancerRoleCode[]
): boolean {
  return application?.primary_role == null && applicationRoleCodes.length > 0;
}

function roleSequencesMatch(
  application: BalancerApplication | null | undefined,
  isFlexPlayer: boolean,
  left: BalancerRoleCode[],
  right: BalancerRoleCode[]
): boolean {
  if (left.length === 0) {
    return false;
  }

  const primaryApplicationRole = normalizeApplicationRole(application?.primary_role);
  if (primaryApplicationRole) {
    return left.includes(primaryApplicationRole);
  }

  if (right.length === 0) {
    return true;
  }

  if (isFlexPlayer || isFlexApplication(application, right)) {
    return left.every((roleCode) => right.includes(roleCode));
  }

  return left.every((roleCode) => right.includes(roleCode));
}

interface RoleRankDelta {
  role: BalancerRoleCode;
  delta: number;
  /** Balancer rank for the role (workspace-grid points). */
  currentRank: number;
  /** OW2 rank converted into the workspace grid (points). */
  owRank: number;
}

/**
 * Absolute rank-point delta between the balancer rank and the (grid-normalised) OW rank for
 * every active ranked role that has both values. `ow_rank_value` is normalised to the workspace
 * grid server-side, so it shares the same scale as `rank_value` and subtraction is valid.
 */
function computeRankDeltasByRole(player: BalancerPlayerRecord): RoleRankDelta[] {
  return getActiveRoleEntries(player.role_entries_json)
    .filter((entry) => entry.rank_value !== null && entry.ow_rank_value !== null)
    .map((entry) => ({
      role: entry.role,
      delta: Math.abs((entry.rank_value as number) - (entry.ow_rank_value as number)),
      currentRank: entry.rank_value as number,
      owRank: entry.ow_rank_value as number
    }));
}

export function getPlayerValidationIssues(
  player: BalancerPlayerRecord,
  application: BalancerApplication | null | undefined,
  workspaceConfig?: { rank_delta_threshold: number | null } | null,
  grid: DivisionGrid = DEFAULT_DIVISION_GRID
): PlayerValidationIssue[] {
  const issues: PlayerValidationIssue[] = [];

  if (!playerHasRankedRole(player)) {
    issues.push({
      code: "missing_ranked_role",
      message: "No ranked roles configured"
    });
  }

  if (player.ready_blocked) {
    issues.push({
      code: "status_blocks_ready",
      message: "Current status blocks Ready"
    });
  }

  if (application) {
    const playerRoleCodes = getPlayerRoleCodes(player);
    const applicationRoleCodes = getApplicationRoleCodes(application);

    if (!roleSequencesMatch(application, player.is_flex, playerRoleCodes, applicationRoleCodes)) {
      issues.push({
        code: "application_role_mismatch",
        message: `Application: ${formatRoleCodes(applicationRoleCodes)}; balancer: ${formatRoleCodes(playerRoleCodes)}`,
        applicationRoleCodes,
        playerRoleCodes
      });
    }
  }

  if (workspaceConfig?.rank_delta_threshold != null) {
    const threshold = workspaceConfig.rank_delta_threshold;
    const violating = computeRankDeltasByRole(player)
      .filter((entry) => entry.delta > threshold)
      .sort((a, b) => b.delta - a.delta);
    // One chip per violating role, worst delta first.
    for (const entry of violating) {
      const currentDivision = resolveDivisionFromRank(grid, entry.currentRank);
      const owDivision = resolveDivisionFromRank(grid, entry.owRank);
      const currentLabel = getDivisionLabel(grid, currentDivision) ?? String(entry.currentRank);
      const owLabel = getDivisionLabel(grid, owDivision) ?? String(entry.owRank);
      issues.push({
        code: "rank_delta_warning",
        role: entry.role,
        currentDivision,
        owDivision,
        delta: entry.delta,
        message: `${ROLE_LABELS[entry.role]}: ${currentLabel} → ${owLabel} (Δ${entry.delta} pts)`
      });
    }
  }

  return issues;
}

function normalizeInternalPayload(payload: InternalBalancePayload): InternalBalancePayload {
  return {
    ...payload,
    teams: payload.teams.map((team, index) => ({
      ...team,
      id: team.id ?? index + 1,
      roster: {
        Tank: team.roster.Tank ?? [],
        Damage: team.roster.Damage ?? [],
        Support: team.roster.Support ?? []
      }
    }))
  };
}

export function buildVariantFromSavedBalance(balance: SavedBalance): BalanceVariant {
  return {
    id: `saved-${balance.id}`,
    label: `Saved balance #${balance.id}`,
    payload: normalizeInternalPayload(balance.result_json),
    source: "saved",
    config: balance.config_json as BalancerConfig | null
  };
}

/**
 * Solver role spelling -> the editor's roster key.
 *
 * A balance response is keyed by the canonical roster slot codes of
 * `shared/domain/roster_shape.py` (`tank`/`dps`/`support`), because the solver's
 * role mask is now a projection of the tournament roster shape. The editor and
 * every persisted `result_json` are keyed by the display names, so the response
 * is re-keyed on the way in. Both spellings are accepted: runs and saved
 * balances produced before the roster shape landed carry the display names.
 *
 * `flex` is deliberately absent — the three-column editor has no bucket for it,
 * so a flex roster shape is unsupported here rather than half-rendered.
 */
const ROSTER_KEY_BY_SOLVER_ROLE: Record<string, BalancerRosterKey> = {
  ...API_ROLE_KEYS,
  Tank: "Tank",
  Damage: "Damage",
  Support: "Support"
};

/**
 * A response player carries three role-keyed fields besides its bucket, and all
 * three are compared against roster keys downstream (drop eligibility, off-role
 * badges, re-rating on move), so they are re-keyed together with the bucket.
 */
function normalizeBalanceResponsePlayer(player: PlayerData): InternalBalancePlayer {
  const normalized: InternalBalancePlayer = {
    ...player,
    role_preferences: player.role_preferences.map(
      (role) => ROSTER_KEY_BY_SOLVER_ROLE[role] ?? role
    )
  };
  for (const field of ["all_ratings", "all_discomforts"] as const) {
    const map = player[field];
    if (map) {
      normalized[field] = Object.fromEntries(
        Object.entries(map).map(([role, value]) => [ROSTER_KEY_BY_SOLVER_ROLE[role] ?? role, value])
      );
    }
  }
  return normalized;
}

export function convertBalanceResponseToInternalPayload(
  response: BalanceResponse
): InternalBalancePayload {
  return normalizeInternalPayload({
    teams: response.teams.map((team) => {
      const roster: Record<BalancerRosterKey, InternalBalancePlayer[]> = {
        Tank: [],
        Damage: [],
        Support: []
      };
      for (const [role, players] of Object.entries(team.roster)) {
        const rosterKey = ROSTER_KEY_BY_SOLVER_ROLE[role];
        if (rosterKey === undefined) {
          continue;
        }
        roster[rosterKey].push(...players.map(normalizeBalanceResponsePlayer));
      }
      return {
        id: team.id,
        name: team.name,
        average_mmr: team.average_mmr,
        rating_variance: team.rating_variance,
        total_discomfort: team.total_discomfort,
        max_discomfort: team.max_discomfort,
        roster
      };
    }),
    statistics: response.statistics,
    benched_players: (response.benched_players ?? []).map(normalizeBalanceResponsePlayer)
  });
}

function getRegistrationDisplayName(registration: AdminRegistration): string {
  return registration.battle_tag ?? registration.display_name ?? `registration-${registration.id}`;
}

function isRegistrationFlex(registration: AdminRegistration): boolean {
  return registration.roles.length > 0 && registration.roles.every((role) => role.is_primary);
}

export function isRegistrationIncludedInBalancer(registration: AdminRegistration): boolean {
  return !registration.deleted_at && !registration.balancer_status_meta.excludes_from_balancer;
}

/** Whether the registration's current custom status blocks it from counting as "ready", independent of pool inclusion. */
function isRegistrationReadyBlocked(registration: AdminRegistration): boolean {
  return registration.balancer_status_meta.excludes_from_ready;
}

export function isRegistrationAvailableForBalancer(registration: AdminRegistration): boolean {
  return registration.status === "approved" && !registration.deleted_at;
}

export function createSyntheticPlayerFromRegistration(
  registration: AdminRegistration,
  grid: DivisionGrid = DEFAULT_DIVISION_GRID
): BalancerPlayerRecord {
  const battleTag = getRegistrationDisplayName(registration);
  const isFlex = isRegistrationFlex(registration);
  return {
    id: registration.id,
    tournament_id: registration.tournament_id,
    application_id: registration.id,
    battle_tag: battleTag,
    battle_tag_normalized: registration.battle_tag_normalized ?? battleTag.toLowerCase(),
    user_id: registration.user_id,
    // Roles come from the API exactly as the roster engine resolved them:
    // `is_active` IS "playable" and `rank_value` IS the resolved rank, flex
    // modes included. Nothing is re-derived here.
    role_entries_json: registration.roles.map((role) => ({
      role: role.role,
      subtype: role.subrole,
      priority: role.priority,
      division_number: resolveDivisionFromRankHelper(role.rank_value, grid),
      rank_value: role.rank_value,
      is_active: role.is_active,
      is_declared_active: role.is_declared_active,
      ow_rank_value: role.ow_rank_value ?? null,
      rank_source: role.rank_source
    })),
    is_flex: isFlex,
    is_in_pool: isRegistrationIncludedInBalancer(registration),
    ready_blocked: isRegistrationReadyBlocked(registration),
    admin_notes: registration.admin_notes
  };
}

export function createSyntheticApplicationFromRegistration(
  registration: AdminRegistration,
  player: BalancerPlayerRecord | null = null
): BalancerApplication {
  const sortedRoles = [...registration.roles].sort((left, right) => left.priority - right.priority);
  const isFlex = isRegistrationFlex(registration);
  const primaryRole = isFlex
    ? null
    : (sortedRoles.find((role) => role.is_primary)?.role ?? sortedRoles[0]?.role ?? null);
  const additionalRoles = isFlex
    ? sortedRoles.map((role) => role.role)
    : sortedRoles.filter((role) => role.role !== primaryRole).map((role) => role.role);
  const battleTag = getRegistrationDisplayName(registration);

  return {
    id: registration.id,
    tournament_id: registration.tournament_id,
    tournament_sheet_id: 0,
    battle_tag: battleTag,
    battle_tag_normalized: registration.battle_tag_normalized ?? battleTag.toLowerCase(),
    smurf_tags_json: registration.smurf_tags_json ?? [],
    twitch_nick: registration.twitch_nick,
    discord_nick: registration.discord_nick,
    stream_pov: registration.stream_pov,
    last_tournament_text: null,
    primary_role: primaryRole,
    additional_roles_json: additionalRoles,
    notes: registration.notes,
    submitted_at: registration.submitted_at,
    synced_at: registration.submitted_at ?? registration.reviewed_at ?? new Date(0).toISOString(),
    is_active: isRegistrationAvailableForBalancer(registration),
    player
  };
}

export function buildTeamNamesText(payload: InternalBalancePayload | null): string {
  if (!payload) {
    return "";
  }
  return payload.teams.map((team) => team.name.split("#")[0]).join("\n");
}

export function downloadPayload(payload: InternalBalancePayload, tournamentId: number | null) {
  const blob = new Blob([JSON.stringify(payload, null, 2)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = `balancer-${tournamentId ?? "draft"}.json`;
  anchor.click();
  URL.revokeObjectURL(url);
}

export function downloadPlayersExport(
  payload: BalancerPlayerExportResponse,
  tournamentId: number | null
) {
  const blob = new Blob([JSON.stringify(payload, null, 2)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  // The two formats are not interchangeable, so the file says which one it is:
  // `xv-1` keeps its historical name, ours is prefixed by the format.
  anchor.download =
    payload.format === "owt-1"
      ? `owt-players-${tournamentId ?? "export"}.json`
      : `balancer-players-${tournamentId ?? "export"}.json`;
  anchor.click();
  URL.revokeObjectURL(url);
}

/**
 * Resolve division number from a rank value using the workspace division grid.
 * Falls back to DEFAULT_DIVISION_GRID when no grid is provided.
 */
function resolveDivisionFromRankHelper(
  rankValue: number | null,
  grid: DivisionGrid = DEFAULT_DIVISION_GRID
): number | null {
  return resolveDivisionFromRank(grid, rankValue);
}

/**
 * A past tournament role -> the balancer registration role it seeds, or
 * `null` for `Flex`: a flex roster row carries ONE rank that stands for no
 * particular role (the player's maximum), so attributing it to tank, dps or
 * support would invent per-role history the tournament never recorded — the
 * same call the backend makes in
 * `registration/rank_sources.py::HERO_CLASS_TO_REGISTRATION_ROLE`.
 */
function toBalancerRoleCode(role: UserRoleType): BalancerRoleCode | null {
  const code = playerRoleSlotCode(role);
  return code === "flex" ? null : code;
}

/**
 * Looks up a player's rank history using a two-step search:
 * 1. Balancer history — ranks from past balancer registrations (source "balancer"),
 *    scoped to `workspaceId` when numeric, otherwise `currentWorkspaceId`.
 * 2. Analytics fallback — past tournament ranks via getUserTournaments (source "analytics")
 *    for roles not found in step 1.
 *
 * Division numbers are normalized to the target grid version when provided. Returns null if
 * the user cannot be found or has no history.
 */
export async function fetchPlayerRankHistoryPreview(
  battleTag: string,
  targetGridVersion: DivisionGridVersion | null = null,
  grid: DivisionGrid = DEFAULT_DIVISION_GRID,
  workspaceId?: number | null,
  currentWorkspaceId?: number | null
): Promise<PlayerRankHistoryPreview | null> {
  try {
    const lookupName = battleTag.replace("#", "-");
    const user = await userService.getUserByName(lookupName);
    if (!user?.id) return null;

    const latestPerRole = new Map<BalancerRoleCode, PlayerRankHistoryPreviewEntry>();

    // Step 1: Balancer history — ranks from past balancer registrations (newest first).
    // Scoped to a concrete workspace (the chosen one, else the current workspace).
    const balancerWorkspaceId =
      typeof workspaceId === "number" ? workspaceId : currentWorkspaceId ?? null;
    if (balancerWorkspaceId != null) {
      try {
        const balancerHistory = await balancerAdminService.getUserBalancerRankHistory(
          user.id,
          balancerWorkspaceId
        );
        for (const entry of balancerHistory) {
          if (latestPerRole.has(entry.role)) continue; // newest already kept
          latestPerRole.set(entry.role, {
            role: entry.role,
            rank_value: entry.rank_value,
            division_number: resolveDivisionFromRankHelper(entry.rank_value, grid),
            original_division_number: null,
            tournament_id: entry.tournament_id,
            tournament_name: entry.tournament_name,
            source_role: null,
            tournament_grid_version: null,
            source: "balancer"
          });
        }
      } catch {
        // Non-fatal: fall through to the analytics step.
      }
    }

    // Step 2: Analytics fallback — past tournament ranks for roles not found in step 1,
    // most recent tournaments first.
    const missingRoles = ROLE_ORDER.filter((role) => !latestPerRole.has(role));
    if (missingRoles.length > 0) {
      const tournaments = await userService.getUserTournaments(user.id, workspaceId);
      if (tournaments?.length) {
        const sorted = [...tournaments].sort((a, b) => b.id - a.id);

        const sourceVersionsById = new Map<number, DivisionGridVersion>();
        for (const tournament of sorted) {
          const v = tournament.division_grid_version;
          if (v) sourceVersionsById.set(v.id, v);
        }

        let normalizer: DivisionGridNormalizer | null = null;
        if (targetGridVersion) {
          normalizer = await DivisionGridNormalizer.build(targetGridVersion, [
            ...sourceVersionsById.values()
          ]);
        }

        for (const tournament of sorted) {
          const roleName = tournament.role as UserRoleType;
          const roleCode = toBalancerRoleCode(roleName);
          if (!roleCode) continue;
          if (latestPerRole.has(roleCode)) continue;
          const playerRecord = tournament.players.find((p) => p.user_id === user.id);
          const rankValue = playerRecord?.rank ?? null;
          if (rankValue !== null && rankValue > 0) {
            const originalDivisionNumber = resolveDivisionFromRankHelper(
              rankValue,
              tournament.division_grid_version ?? grid
            );

            let divisionNumber: number | null;
            if (normalizer && tournament.division_grid_version) {
              divisionNumber = normalizer.safeNormalize(tournament.division_grid_version.id, rankValue);
            } else {
              divisionNumber = originalDivisionNumber;
            }

            latestPerRole.set(roleCode, {
              role: roleCode,
              rank_value: rankValue,
              division_number: divisionNumber,
              original_division_number: originalDivisionNumber,
              tournament_id: tournament.id,
              tournament_name: tournament.name,
              source_role: roleName,
              tournament_grid_version: tournament.division_grid_version ?? null,
              source: "analytics"
            });
          }
        }
      }
    }

    if (latestPerRole.size === 0) {
      return null;
    }

    const entries = ROLE_ORDER.map((role) => latestPerRole.get(role)).filter(
      (entry): entry is PlayerRankHistoryPreviewEntry => entry !== undefined
    );

    const average_rank_value =
      entries.length > 0
        ? Math.round(entries.reduce((sum, entry) => sum + entry.rank_value, 0) / entries.length)
        : null;

    return {
      user_id: user.id,
      entries,
      average_rank_value
    };
  } catch {
    return null;
  }
}

/**
 * Build a per-role rank map from a single registration's autofill preview. The backend already
 * applied the priority chain (e.g. balancer → analytics → OW for the balancer-first mode), so we
 * just collect the resolved `parsed_rank_value` per role. Returns null when nothing was resolved.
 */
export function buildRankHistoryFromAutofillPreview(
  preview: RegistrationRankAutofillResponse,
  registrationId: number
): Partial<Record<BalancerRoleCode, number>> | null {
  const player = preview.players.find((entry) => entry.registration_id === registrationId);
  if (!player) {
    return null;
  }

  const history: Partial<Record<BalancerRoleCode, number>> = {};
  for (const role of player.roles) {
    if (role.parsed_rank_value != null) {
      history[role.role] = role.parsed_rank_value;
    }
  }

  return Object.keys(history).length > 0 ? history : null;
}

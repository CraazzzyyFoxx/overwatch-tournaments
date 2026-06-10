import {
  AdminRegistration,
  BalancerApplication,
  BalancerPlayerExportResponse,
  BalancerPlayerHistoryRecord,
  BalancerPlayerRecord,
  BalancerPlayerRoleEntry,
  BalancerRoleCode,
  InternalBalancePayload,
  SavedBalance
} from "@/types/balancer-admin.types";
import balancerAdminService from "@/services/balancer-admin.service";
import { BalanceResponse, BalancerConfig } from "@/types/balancer.types";
import { UserRoleType } from "@/types/user.types";
import type { DivisionGrid, DivisionGridVersion } from "@/types/workspace.types";
import { DEFAULT_DIVISION_GRID, resolveDivisionFromRank } from "@/lib/division-grid";
import userService from "@/services/user.service";
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
  source: "saved" | "generated";
  config?: BalancerConfig | null;
  /** Number of pool players excluded from this run due to validation issues */
  skippedCount?: number;
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
  tournament_number: number | null;
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

export function sortRoleEntries(entries: BalancerPlayerRoleEntry[]): BalancerPlayerRoleEntry[] {
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

export function playerHasRankedRole(player: BalancerPlayerRecord): boolean {
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

export function getPlayerValidationIssues(
  player: BalancerPlayerRecord,
  application: BalancerApplication | null | undefined
): PlayerValidationIssue[] {
  const issues: PlayerValidationIssue[] = [];

  if (!playerHasRankedRole(player)) {
    issues.push({
      code: "missing_ranked_role",
      message: "No ranked roles configured"
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

  return issues;
}

export function normalizeInternalPayload(payload: InternalBalancePayload): InternalBalancePayload {
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

export function convertBalanceResponseToInternalPayload(
  response: BalanceResponse
): InternalBalancePayload {
  return normalizeInternalPayload({
    teams: response.teams.map((team) => ({
      id: team.id,
      name: team.name,
      average_mmr: team.average_mmr,
      rating_variance: team.rating_variance,
      total_discomfort: team.total_discomfort,
      max_discomfort: team.max_discomfort,
      roster: {
        Tank: team.roster.Tank ?? [],
        Damage: team.roster.Damage ?? [],
        Support: team.roster.Support ?? []
      }
    })),
    statistics: response.statistics,
    benched_players: response.benched_players ?? []
  });
}

export function buildBalancerInput(players: BalancerPlayerRecord[]): Record<string, unknown> {
  const payload = players.reduce<Record<string, unknown>>((accumulator, player) => {
    const roleEntries = getActiveRoleEntries(player.role_entries_json);
    const hasRankedRole = roleEntries.some((entry) => entry.rank_value !== null);
    if (!hasRankedRole) {
      return accumulator;
    }

    const toClassConfig = (role: "tank" | "dps" | "support") => {
      const roleEntry = roleEntries.find((entry) => entry.role === role);
      return {
        isActive: Boolean(roleEntry?.is_active && roleEntry?.rank_value),
        rank: roleEntry?.rank_value ?? 0,
        priority: roleEntry?.priority ?? 99,
        subtype: roleEntry?.subtype ?? null
      };
    };

    accumulator[String(player.id)] = {
      identity: {
        name: player.battle_tag,
        isFullFlex: player.is_flex
      },
      stats: {
        classes: Object.fromEntries(
          ROLE_ORDER.map((role) => [API_ROLE_KEYS[role], toClassConfig(role)])
        )
      }
    };
    return accumulator;
  }, {});

  return {
    format: "xv-1",
    players: payload
  };
}

function getRegistrationDisplayName(registration: AdminRegistration): string {
  return registration.battle_tag ?? registration.display_name ?? `registration-${registration.id}`;
}

function isRegistrationFlex(registration: AdminRegistration): boolean {
  return registration.roles.length > 0 && registration.roles.every((role) => role.is_primary);
}

export function isRegistrationIncludedInBalancer(registration: AdminRegistration): boolean {
  return (
    registration.status === "approved" &&
    !registration.deleted_at &&
    !registration.exclude_from_balancer &&
    registration.balancer_status !== "not_in_balancer"
  );
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
    role_entries_json: registration.roles.map((role) => ({
      role: role.role,
      subtype: role.subrole,
      priority: role.priority,
      division_number: resolveDivisionFromRankHelper(role.rank_value, grid),
      rank_value: role.rank_value,
      is_active: role.is_active
    })),
    is_flex: isFlex,
    is_in_pool: isRegistrationIncludedInBalancer(registration),
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
  anchor.download = `balancer-players-${tournamentId ?? "export"}.json`;
  anchor.click();
  URL.revokeObjectURL(url);
}

/**
 * Resolve division number from a rank value using the workspace division grid.
 * Falls back to DEFAULT_DIVISION_GRID when no grid is provided.
 */
export function resolveDivisionFromRankHelper(
  rankValue: number | null,
  grid: DivisionGrid = DEFAULT_DIVISION_GRID
): number | null {
  return resolveDivisionFromRank(grid, rankValue);
}

/**
 * Converts a map of { role -> SR rank } to a sorted BalancerPlayerRoleEntry[].
 * Priority is assigned in ROLE_ORDER order: tank=1, dps=2, support=3.
 */
export function buildRoleEntriesFromRankHistory(
  history: Partial<Record<BalancerRoleCode, number>>,
  grid: DivisionGrid = DEFAULT_DIVISION_GRID
): BalancerPlayerRoleEntry[] {
  const entries: BalancerPlayerRoleEntry[] = [];
  let priority = 1;
  for (const role of ROLE_ORDER) {
    const rankValue = history[role] ?? null;
    if (rankValue === null) continue;
    entries.push({
      role,
      subtype: null,
      priority: priority++,
      rank_value: rankValue,
      division_number: resolveDivisionFromRankHelper(rankValue, grid),
      is_active: true
    });
  }
  return entries;
}

const USER_ROLE_TO_BALANCER: Record<UserRoleType, BalancerRoleCode> = {
  Tank: "tank",
  Damage: "dps",
  Support: "support"
};

/**
 * Looks up a player's rank history from past tournaments using a two-step search:
 * 1. Balancer history (BalancerPlayerRoleEntry records from past assignments)
 * 2. Analytics fallback (getUserTournaments) for roles not found in step 1
 *
 * Division numbers are normalized to the target grid version when provided.
 * Returns null if the user cannot be found or has no history.
 */
export async function fetchPlayerRankHistoryPreview(
  battleTag: string,
  targetGridVersion: DivisionGridVersion | null = null,
  grid: DivisionGrid = DEFAULT_DIVISION_GRID,
  workspaceId?: number | null
): Promise<PlayerRankHistoryPreview | null> {
  try {
    const lookupName = battleTag.replace("#", "-");
    const user = await userService.getUserByName(lookupName);
    if (!user?.id) return null;

    const latestPerRole = new Map<BalancerRoleCode, PlayerRankHistoryPreviewEntry>();

    // Step 1: Balancer history — ranked role entries from past balancer assignments.
    // Records are ordered by tournament number DESC from the API.
    let balancerHistory: BalancerPlayerHistoryRecord[] = [];
    try {
      balancerHistory = await balancerAdminService.getUserBalancerHistory(user.id, workspaceId);
    } catch {
      // Non-fatal: fall through to analytics
    }

    for (const player of balancerHistory) {
      for (const entry of player.role_entries_json) {
        if (!entry.is_active || entry.rank_value === null) continue;
        if (latestPerRole.has(entry.role)) continue; // already have newer
        latestPerRole.set(entry.role, {
          role: entry.role,
          rank_value: entry.rank_value,
          division_number: entry.division_number ?? resolveDivisionFromRankHelper(entry.rank_value, grid),
          original_division_number: entry.division_number ?? null,
          tournament_id: player.tournament_id,
          tournament_name: null,
          tournament_number: player.tournament_number ?? null,
          source_role: null,
          tournament_grid_version: null,
          source: "balancer"
        });
      }
    }

    // Step 2: Analytics fallback — only for roles not yet found in balancer history.
    const missingRoles = ROLE_ORDER.filter((role) => !latestPerRole.has(role));
    if (missingRoles.length > 0) {
      const tournaments = await userService.getUserTournaments(user.id, workspaceId);
      if (tournaments?.length) {
        const sorted = [...tournaments].sort((a, b) => b.number - a.number);

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
          const roleCode = USER_ROLE_TO_BALANCER[roleName];
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
              tournament_number: tournament.number,
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

export async function fetchPlayerRankHistory(
  battleTag: string
): Promise<Partial<Record<BalancerRoleCode, number>> | null> {
  const preview = await fetchPlayerRankHistoryPreview(battleTag);
  if (!preview) {
    return null;
  }

  return Object.fromEntries(
    preview.entries.map((entry) => [entry.role, entry.rank_value])
  ) as Partial<Record<BalancerRoleCode, number>>;
}

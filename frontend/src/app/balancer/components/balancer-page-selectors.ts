import type {
  AdminRegistration,
  BalancerApplication,
  BalancerPlayerRecord,
  InternalBalancePayload,
} from "@/types/balancer-admin.types";
import type { DivisionGrid } from "@/types/workspace.types";

import {
  createSyntheticApplicationFromRegistration,
  createSyntheticPlayerFromRegistration,
  getPlayerValidationIssues,
  isRegistrationAvailableForBalancer,
  type BalanceVariant,
  type SlotLabeler,
} from "@/components/balancer/workspace-helpers";
import { type PlayerValidationState } from "@/components/balancer/balancer-page-helpers";

export type BalancerPageCollections = {
  registrationsById: Map<number, AdminRegistration>;
  players: BalancerPlayerRecord[];
  playersById: Map<number, BalancerPlayerRecord>;
  applications: BalancerApplication[];
  applicationsById: Map<number, BalancerApplication>;
  poolPlayers: BalancerPlayerRecord[];
  allPlayerValidationStates: PlayerValidationState[];
  playerValidationStates: PlayerValidationState[];
  readyPlayers: BalancerPlayerRecord[];
  invalidPlayerStates: PlayerValidationState[];
  flexPoolCount: number;
};

export function buildBalancerPageCollections(
  allRegistrations: AdminRegistration[],
  divisionGrid: DivisionGrid,
  slotLabel: SlotLabeler,
  /** The owner game's identity provider: whose handle answers name each player (`null`: the game has none). */
  identityProvider: string | null,
): BalancerPageCollections {
  // Only approved registrations belong to the balancer, the same rule the
  // backend pool uses (`pool_only`): pending, rejected and withdrawn rows are
  // neither pool candidates nor "excluded" rows to triage, so they never list.
  const registrations = allRegistrations.filter(isRegistrationAvailableForBalancer);
  const registrationsById = new Map(
    registrations.map((registration) => [registration.id, registration]),
  );
  const players = registrations.map((registration) =>
    createSyntheticPlayerFromRegistration(registration, divisionGrid, identityProvider),
  );
  const playersById = new Map(players.map((player) => [player.id, player]));
  const applications = registrations.map((registration) =>
    createSyntheticApplicationFromRegistration(
      registration,
      playersById.get(registration.id)?.is_in_pool
        ? playersById.get(registration.id) ?? null
        : null,
      identityProvider,
    ),
  );
  const applicationsById = new Map(
    applications.map((application) => [application.id, application]),
  );
  const poolPlayers = players.filter((player) => player.is_in_pool);
  const allPlayerValidationStates = buildPlayerValidationStates(
    players,
    applicationsById,
    divisionGrid,
    slotLabel,
  );
  const playerValidationStates = buildPlayerValidationStates(
    poolPlayers,
    applicationsById,
    divisionGrid,
    slotLabel,
  );
  const readyPlayers = playerValidationStates
    .filter((state) => state.issues.length === 0)
    .map((state) => state.player);
  const invalidPlayerStates = playerValidationStates.filter((state) => state.issues.length > 0);
  const flexPoolCount = poolPlayers.filter((player) => player.is_flex).length;

  return {
    registrationsById,
    players,
    playersById,
    applications,
    applicationsById,
    poolPlayers,
    allPlayerValidationStates,
    playerValidationStates,
    readyPlayers,
    invalidPlayerStates,
    flexPoolCount,
  };
}

function buildPlayerValidationStates(
  players: BalancerPlayerRecord[],
  applicationsById: Map<number, BalancerApplication>,
  divisionGrid: DivisionGrid,
  slotLabel: SlotLabeler,
): PlayerValidationState[] {
  return players.map((player) => ({
    player,
    issues: getPlayerValidationIssues(
      player,
      applicationsById.get(player.application_id) ?? null,
      null,
      divisionGrid,
      slotLabel,
    ),
  }));
}

export function getDefaultCollapsedTeamIds(variant: BalanceVariant | null): number[] {
  if (!variant?.payload.teams.length) {
    return [];
  }

  const teamIds = variant.payload.teams.map((team) => team.id);
  const expandedByDefault = new Set(teamIds.slice(0, 4));
  return teamIds.filter((teamId) => !expandedByDefault.has(teamId));
}

export function getCanRunBalance(options: {
  isRunPending: boolean;
  poolPlayerCount: number;
  invalidPlayerCount: number;
  readyPlayerCount: number;
  excludeInvalidPlayers: boolean;
}): boolean {
  const {
    isRunPending,
    poolPlayerCount,
    invalidPlayerCount,
    readyPlayerCount,
    excludeInvalidPlayers,
  } = options;

  return (
    !isRunPending &&
    poolPlayerCount > 0 &&
    (!excludeInvalidPlayers ? invalidPlayerCount === 0 : readyPlayerCount > 0)
  );
}

export function getPresetOptions(
  presets: Record<string, unknown> | null | undefined,
): string[] {
  const options = Object.keys(presets ?? {});
  return options.length > 0 ? options : ["DEFAULT"];
}

export function toggleCollapsedTeamId(
  collapsedTeamIds: number[],
  teamId: number,
): number[] {
  return collapsedTeamIds.includes(teamId)
    ? collapsedTeamIds.filter((id) => id !== teamId)
    : [...collapsedTeamIds, teamId];
}

export function replaceVariantPayload(
  variants: BalanceVariant[],
  activeVariantId: string,
  payload: InternalBalancePayload,
): BalanceVariant[] {
  return variants.map((variant) =>
    variant.id === activeVariantId ? { ...variant, payload, dirty: true } : variant,
  );
}

export function upsertSavedVariant(
  variants: BalanceVariant[],
  savedVariant: BalanceVariant,
): BalanceVariant[] {
  return [savedVariant, ...variants.filter((variant) => variant.source !== "saved")];
}

export type PoolMismatch = {
  /** Ready pool players the balance holds nowhere (no team, not spare). */
  missing: BalancerPlayerRecord[];
  /** Players the balance holds that the pool does not (excluded or gone since), by their name in the balance. */
  outside: string[];
};

/**
 * Where a balance and the pool on screen disagree, or null when they agree. A ready player missing from it, or a player
 * in it the pool no longer holds, means the balance was built from another pool (an older run, or a stale server read):
 * worth saying before it is exported. Players with blocking issues may be skipped on purpose, so they never count.
 */
export function poolMismatch(
  payload: InternalBalancePayload,
  readyPlayers: readonly BalancerPlayerRecord[],
  poolPlayers: readonly BalancerPlayerRecord[]
): PoolMismatch | null {
  const placed = [...payload.teams.flatMap((team) => Object.values(team.roster).flat()), ...(payload.benched_players ?? [])];
  const placedIds = new Set(placed.map((player) => Number(player.uuid)));
  const poolIds = new Set(poolPlayers.map((player) => player.id));
  const missing = readyPlayers.filter((player) => !placedIds.has(player.id));
  const outside = placed.filter((player) => !poolIds.has(Number(player.uuid))).map((player) => player.name);
  return missing.length > 0 || outside.length > 0 ? { missing, outside } : null;
}

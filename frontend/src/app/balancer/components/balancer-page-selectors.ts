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
} from "./workspace-helpers";
import { countTeamPlayers, type PlayerValidationState } from "./balancer-page-helpers";

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
  missingRankPlayerStates: PlayerValidationState[];
  addableApplications: BalancerApplication[];
  flexPoolCount: number;
};

export function buildBalancerPageCollections(
  registrations: AdminRegistration[],
  divisionGrid: DivisionGrid,
): BalancerPageCollections {
  const registrationsById = new Map(
    registrations.map((registration) => [registration.id, registration]),
  );
  const players = registrations.map((registration) =>
    createSyntheticPlayerFromRegistration(registration, divisionGrid),
  );
  const playersById = new Map(players.map((player) => [player.id, player]));
  const applications = registrations
    .filter((registration) => isRegistrationAvailableForBalancer(registration))
    .map((registration) =>
      createSyntheticApplicationFromRegistration(
        registration,
        playersById.get(registration.id)?.is_in_pool
          ? playersById.get(registration.id) ?? null
          : null,
      ),
    );
  const applicationsById = new Map(
    applications.map((application) => [application.id, application]),
  );
  const poolPlayers = players.filter((player) => player.is_in_pool);
  const allPlayerValidationStates = buildPlayerValidationStates(players, applicationsById);
  const playerValidationStates = buildPlayerValidationStates(poolPlayers, applicationsById);
  const readyPlayers = playerValidationStates
    .filter((state) => state.issues.length === 0)
    .map((state) => state.player);
  const invalidPlayerStates = playerValidationStates.filter((state) => state.issues.length > 0);
  const missingRankPlayerStates = invalidPlayerStates.filter((state) =>
    state.issues.some((issue) => issue.code === "missing_ranked_role"),
  );
  const addableApplications = applications.filter(
    (application) => application.is_active && application.player === null,
  );
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
    missingRankPlayerStates,
    addableApplications,
    flexPoolCount,
  };
}

export function buildPlayerValidationStates(
  players: BalancerPlayerRecord[],
  applicationsById: Map<number, BalancerApplication>,
): PlayerValidationState[] {
  return players.map((player) => ({
    player,
    issues: getPlayerValidationIssues(
      player,
      applicationsById.get(player.application_id) ?? null,
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

export function getVariantPlayerCount(
  payload: InternalBalancePayload | null | undefined,
): number {
  if (!payload) {
    return 0;
  }

  return payload.teams.reduce((sum, team) => sum + countTeamPlayers(team), 0);
}

export function getActiveVariantSummary(activeVariant: BalanceVariant | null): {
  hasActiveVariant: boolean;
  activeVariantTeamCount: number;
  activeVariantPlayerCount: number;
} {
  return {
    hasActiveVariant: activeVariant !== null,
    activeVariantTeamCount: activeVariant?.payload.teams.length ?? 0,
    activeVariantPlayerCount: getVariantPlayerCount(activeVariant?.payload),
  };
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
    variant.id === activeVariantId ? { ...variant, payload } : variant,
  );
}

export function upsertSavedVariant(
  variants: BalanceVariant[],
  savedVariant: BalanceVariant,
): BalanceVariant[] {
  return [savedVariant, ...variants.filter((variant) => variant.source !== "saved")];
}

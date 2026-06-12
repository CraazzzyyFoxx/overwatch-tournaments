import type {
  BalancerRosterKey,
  InternalBalancePayload,
  InternalBalancePlayer,
} from "@/types/balancer-admin.types";

import {
  calculateOffRoleCountFromPayload,
  calculateSubRoleCollisionsFromPayload,
  calculateTeamAverageValueFromPayload,
  calculateTeamDiscomfortFromPayload,
  calculateTeamTotalFromPayload,
  calculateTeamVarianceFromPayload,
  countTeamPlayers,
  sampleStdDev,
} from "@/app/balancer/components/balancer-page-helpers";

export const BALANCE_EDITOR_ROLE_CAPACITY: Record<BalancerRosterKey, number> = {
  Tank: 1,
  Damage: 2,
  Support: 2,
};

export const BALANCE_EDITOR_ROLE_LABELS: Record<BalancerRosterKey, string> = {
  Tank: "Tank",
  Damage: "Damage",
  Support: "Support",
};

export const BALANCE_EDITOR_ROLE_ACCENTS: Record<BalancerRosterKey, { text: string }> = {
  Tank: { text: "text-sky-300" },
  Damage: { text: "text-orange-300" },
  Support: { text: "text-emerald-300" },
};

export type BalancePlayerLocation = {
  teamIndex: number;
  roleKey: BalancerRosterKey;
  playerIndex: number;
};

/** The currently dragged player's role context, used to gate drop targets in the UI. */
export type BalanceActiveDrag = {
  currentRole: BalancerRosterKey;
  playableRoles: BalancerRosterKey[];
};

/**
 * Whether dropping the active drag onto `roleKey` is allowed: the player's own
 * role is always valid (same-role / cross-team move), any other role only if
 * the player can play it.
 */
export function isRoleDropAllowed(
  activeDrag: BalanceActiveDrag | null,
  roleKey: BalancerRosterKey,
): boolean {
  if (!activeDrag) {
    return true;
  }
  return roleKey === activeDrag.currentRole || activeDrag.playableRoles.includes(roleKey);
}

export type BalanceDropTarget =
  | {
      kind: "role-container";
      teamIndex: number;
      roleKey: BalancerRosterKey;
    }
  | {
      kind: "insert-slot";
      teamIndex: number;
      roleKey: BalancerRosterKey;
      insertIndex: number;
    }
  | {
      kind: "player-row";
      teamIndex: number;
      roleKey: BalancerRosterKey;
      playerIndex: number;
      playerId: string;
    };

export function cloneBalancePayload(payload: InternalBalancePayload): InternalBalancePayload {
  return JSON.parse(JSON.stringify(payload)) as InternalBalancePayload;
}

export function findBalancePlayerLocation(
  payload: InternalBalancePayload,
  playerId: string,
): BalancePlayerLocation | null {
  for (const [teamIndex, team] of payload.teams.entries()) {
    for (const roleKey of Object.keys(team.roster) as BalancerRosterKey[]) {
      const playerIndex = team.roster[roleKey].findIndex((player) => player.uuid === playerId);
      if (playerIndex >= 0) {
        return { teamIndex, roleKey, playerIndex };
      }
    }
  }

  return null;
}

export function parseBalanceDropContainerId(
  containerId: string,
): { teamIndex: number; roleKey: BalancerRosterKey } | null {
  const [teamIndexRaw, roleKeyRaw] = containerId.split(":");
  if (!teamIndexRaw || !roleKeyRaw) {
    return null;
  }
  if (!["Tank", "Damage", "Support"].includes(roleKeyRaw)) {
    return null;
  }

  return {
    teamIndex: Number(teamIndexRaw),
    roleKey: roleKeyRaw as BalancerRosterKey,
  };
}

export function resolveBalanceDropTarget(
  overId: string | null,
  data: unknown,
): BalanceDropTarget | null {
  if (typeof data === "object" && data !== null && "kind" in data) {
    if (
      data.kind === "role-container" &&
      "teamIndex" in data &&
      "roleKey" in data
    ) {
      return data as BalanceDropTarget;
    }

    if (
      data.kind === "insert-slot" &&
      "teamIndex" in data &&
      "roleKey" in data &&
      "insertIndex" in data
    ) {
      return data as BalanceDropTarget;
    }

    if (
      data.kind === "player-row" &&
      "teamIndex" in data &&
      "roleKey" in data &&
      "playerIndex" in data &&
      "playerId" in data
    ) {
      return data as BalanceDropTarget;
    }
  }

  if (!overId) {
    return null;
  }

  const parsedContainer = parseBalanceDropContainerId(overId);
  if (!parsedContainer) {
    return null;
  }

  return {
    kind: "role-container",
    teamIndex: parsedContainer.teamIndex,
    roleKey: parsedContainer.roleKey,
  };
}

export function parseInternalBalancePlayerId(player: InternalBalancePlayer): number | null {
  const parsed = Number(player.uuid);
  return Number.isFinite(parsed) ? parsed : null;
}

export function getDraggedBalancePlayer(
  payload: InternalBalancePayload,
  playerId: string,
): { player: InternalBalancePlayer; roleKey: BalancerRosterKey } | null {
  const location = findBalancePlayerLocation(payload, playerId);
  if (!location) {
    return null;
  }

  return {
    player: payload.teams[location.teamIndex].roster[location.roleKey][location.playerIndex],
    roleKey: location.roleKey,
  };
}

/**
 * Whether a player is eligible to occupy a given role slot. Mirrors the
 * backend `Player.can_play` (a role is playable iff the player has a positive
 * rating for it). Falls back to declared `role_preferences` for legacy payloads
 * that predate `all_ratings`.
 */
export function canPlayerPlayRole(
  player: InternalBalancePlayer,
  roleKey: BalancerRosterKey,
): boolean {
  const ratings = player.all_ratings;
  if (ratings && Object.keys(ratings).length > 0) {
    return (ratings[roleKey] ?? 0) > 0;
  }
  return player.role_preferences.includes(roleKey);
}

export function moveBalancePlayer(
  payload: InternalBalancePayload,
  activeId: string,
  target: BalanceDropTarget | null,
): InternalBalancePayload | null {
  if (!target) {
    return null;
  }

  const from = findBalancePlayerLocation(payload, activeId);
  if (!from) {
    return null;
  }

  const next = cloneBalancePayload(payload);
  const sourcePlayers = next.teams[from.teamIndex].roster[from.roleKey];
  const [player] = sourcePlayers.splice(from.playerIndex, 1);
  if (!player) {
    return null;
  }

  const targetPlayers = next.teams[target.teamIndex].roster[target.roleKey];

  if (target.kind === "insert-slot") {
    const insertIndex =
      from.teamIndex === target.teamIndex &&
      from.roleKey === target.roleKey &&
      target.insertIndex > from.playerIndex
        ? target.insertIndex - 1
        : target.insertIndex;

    if (
      from.teamIndex === target.teamIndex &&
      from.roleKey === target.roleKey &&
      insertIndex === from.playerIndex
    ) {
      return null;
    }

    if (
      from.teamIndex !== target.teamIndex ||
      from.roleKey !== target.roleKey
    ) {
      if (targetPlayers.length >= BALANCE_EDITOR_ROLE_CAPACITY[target.roleKey]) {
        return null;
      }

      if (from.roleKey !== target.roleKey && !canPlayerPlayRole(player, target.roleKey)) {
        return null;
      }

      assignPlayerToRole(player, target.roleKey);
    }

    targetPlayers.splice(Math.min(insertIndex, targetPlayers.length), 0, player);
    return recalculateBalancePayloadStats(next);
  }

  if (target.kind === "player-row") {
    if (
      from.teamIndex === target.teamIndex &&
      from.roleKey === target.roleKey &&
      from.playerIndex === target.playerIndex
    ) {
      return null;
    }

    if (from.teamIndex === target.teamIndex && from.roleKey === target.roleKey) {
      const insertIndex = Math.min(target.playerIndex, sourcePlayers.length);
      sourcePlayers.splice(insertIndex, 0, player);
      return recalculateBalancePayloadStats(next);
    }

    if (targetPlayers.length < BALANCE_EDITOR_ROLE_CAPACITY[target.roleKey]) {
      if (from.roleKey !== target.roleKey && !canPlayerPlayRole(player, target.roleKey)) {
        return null;
      }

      assignPlayerToRole(player, target.roleKey);
      targetPlayers.splice(Math.min(target.playerIndex, targetPlayers.length), 0, player);
      return recalculateBalancePayloadStats(next);
    }

    const targetPlayer = targetPlayers[target.playerIndex];
    if (!targetPlayer) {
      return null;
    }

    // Swap across different roles: both players change role, so both must be
    // eligible for the role they land in.
    if (
      from.roleKey !== target.roleKey &&
      (!canPlayerPlayRole(player, target.roleKey) ||
        !canPlayerPlayRole(targetPlayer, from.roleKey))
    ) {
      return null;
    }

    targetPlayers.splice(target.playerIndex, 1, player);
    sourcePlayers.splice(from.playerIndex, 0, targetPlayer);
    assignPlayerToRole(player, target.roleKey);
    assignPlayerToRole(targetPlayer, from.roleKey);
    return recalculateBalancePayloadStats(next);
  }

  if (from.teamIndex === target.teamIndex && from.roleKey === target.roleKey) {
    if (from.playerIndex === sourcePlayers.length) {
      return null;
    }

    sourcePlayers.push(player);
    return recalculateBalancePayloadStats(next);
  }

  if (targetPlayers.length >= BALANCE_EDITOR_ROLE_CAPACITY[target.roleKey]) {
    return null;
  }

  if (from.roleKey !== target.roleKey && !canPlayerPlayRole(player, target.roleKey)) {
    return null;
  }

  assignPlayerToRole(player, target.roleKey);
  targetPlayers.push(player);

  return recalculateBalancePayloadStats(next);
}

/**
 * Per-role discomfort, derived the same way the backend builds `discomfort_map`
 * (entities.py): flex players are comfortable on any role they can play; an
 * in-preference role costs 100 per step down the list; an off-preference role
 * costs 1000 if playable, 5000 if not. Used as a fallback when the solver's
 * `all_discomforts` snapshot is absent (legacy payloads).
 */
export function deriveRoleDiscomfort(
  player: InternalBalancePlayer,
  roleKey: BalancerRosterKey,
): number {
  const playable = canPlayerPlayRole(player, roleKey);
  if (player.is_flex && playable) {
    return 0;
  }
  const preferenceIndex = player.role_preferences.indexOf(roleKey);
  if (preferenceIndex >= 0) {
    return preferenceIndex * 100;
  }
  return playable ? 1000 : 5000;
}

/**
 * Re-rate a player for the role bucket they now occupy. Unlike the previous
 * `applyAssignedRolePreference`, this does NOT reorder `role_preferences`
 * (the original order is the source of truth for primary role + discomfort);
 * the assigned role is implied by the roster bucket. `assigned_rating` and
 * `role_discomfort` are snapped to the new role's values.
 */
function assignPlayerToRole(player: InternalBalancePlayer, roleKey: BalancerRosterKey): void {
  const rating = player.all_ratings?.[roleKey];
  if (typeof rating === "number" && rating > 0) {
    player.assigned_rating = rating;
  }
  player.role_discomfort = player.all_discomforts?.[roleKey] ?? deriveRoleDiscomfort(player, roleKey);
}

function recalculateBalancePayloadStats(
  next: InternalBalancePayload,
): InternalBalancePayload {
  next.teams = next.teams.map((team) => {
    const discomfort = calculateTeamDiscomfortFromPayload(team);
    return {
      ...team,
      average_mmr: calculateTeamAverageValueFromPayload(team),
      rating_variance: calculateTeamVarianceFromPayload(team),
      total_discomfort: discomfort.total,
      max_discomfort: discomfort.max,
    };
  });

  next.statistics = recalculateBalanceStatistics(next);
  return next;
}

/**
 * Recompute the aggregate statistics block from the current rosters, mirroring
 * `result_serializer.teams_to_json`. Solver-only objective scores
 * (balance/comfort/composite) cannot be recomputed client-side and are
 * preserved from the previous statistics (they reflect the original solve).
 */
function recalculateBalanceStatistics(
  payload: InternalBalancePayload,
): InternalBalancePayload["statistics"] {
  const previous = payload.statistics ?? {};
  const teams = payload.teams;
  if (teams.length === 0) {
    return previous;
  }

  const teamAverages = teams.map((team) => calculateTeamAverageValueFromPayload(team));
  const teamTotals = teams.map((team) => calculateTeamTotalFromPayload(team));
  const totalPlaced = teams.reduce((sum, team) => sum + countTeamPlayers(team), 0);
  const offRoleCount = teams.reduce(
    (sum, team) => sum + calculateOffRoleCountFromPayload(team),
    0,
  );
  const subRoleCollisions = teams.reduce(
    (sum, team) => sum + calculateSubRoleCollisionsFromPayload(team),
    0,
  );

  return {
    ...previous,
    average_mmr: mean(teamAverages),
    mmr_std_dev: sampleStdDev(teamAverages),
    average_total_rating: mean(teamTotals),
    total_rating_std_dev: sampleStdDev(teamTotals),
    max_total_rating_gap: teamTotals.length > 0 ? Math.max(...teamTotals) - Math.min(...teamTotals) : 0,
    off_role_count: offRoleCount,
    off_role_rate: totalPlaced > 0 ? offRoleCount / totalPlaced : 0,
    sub_role_collision_count: subRoleCollisions,
  };
}

function mean(values: number[]): number {
  if (values.length === 0) {
    return 0;
  }
  return values.reduce((sum, value) => sum + value, 0) / values.length;
}

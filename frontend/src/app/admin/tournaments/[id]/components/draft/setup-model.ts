import type { DraftCaptainOrder, DraftFormat, DraftRole } from "@/types/draft.types";

export const SETUP_STEPS = [
  "config",
  "pool",
  "captains",
  "order",
  "review",
  "ready"
] as const;

export type DraftSetupStep = (typeof SETUP_STEPS)[number];

export interface DraftPoolCandidate {
  id: number;
  roles: DraftRole[];
  rank: number | null;
  hasAccount: boolean;
  excluded: boolean;
}

export interface DraftPoolReadiness {
  requiredPlayers: number;
  actualPlayers: number;
  missingRanks: number;
  missingAccounts: number;
  excludedPlayers: number;
  roleCoverage: Record<DraftRole, number>;
  blockers: string[];
}

export interface DraftScheduleRound {
  round: number;
  teamIds: number[];
  rule: string;
}

export interface DraftSetupValidationState {
  teamSize: number;
  pickTimeSeconds: number;
  captainIds: number[];
  poolReady: boolean;
  previewFeasible: boolean;
}

export function roundsForTeamSize(teamSize: number): number {
  return Math.max(1, Math.min(8, teamSize - 1));
}

function roleTargets(teamSize: number): Record<DraftRole, number> {
  if (teamSize >= 5) {
    return { tank: 1, dps: 2, support: Math.max(2, teamSize - 3) };
  }
  const tank = Math.min(1, Math.max(0, teamSize));
  const dps = Math.min(2, Math.max(0, teamSize - tank));
  return { tank, dps, support: Math.max(0, teamSize - tank - dps) };
}

export function derivePoolReadiness(
  candidates: DraftPoolCandidate[],
  teamCount: number,
  teamSize: number
): DraftPoolReadiness {
  const included = candidates.filter((candidate) => !candidate.excluded);
  const roleCoverage: Record<DraftRole, number> = { tank: 0, dps: 0, support: 0 };
  for (const candidate of included) {
    for (const role of new Set(candidate.roles)) {
      roleCoverage[role] += 1;
    }
  }
  const requiredPlayers = Math.max(0, teamCount) * Math.max(0, teamSize);
  const blockers: string[] = [];
  if (included.length < requiredPlayers) blockers.push("not_enough_players");
  const targets = roleTargets(teamSize);
  for (const role of ["tank", "dps", "support"] as const) {
    if (roleCoverage[role] < targets[role] * teamCount) {
      blockers.push(`role_shortage:${role}`);
    }
  }
  return {
    requiredPlayers,
    actualPlayers: included.length,
    missingRanks: included.filter((candidate) => candidate.rank == null).length,
    missingAccounts: included.filter((candidate) => !candidate.hasAccount).length,
    excludedPlayers: candidates.length - included.length,
    roleCoverage,
    blockers
  };
}

export function moveCaptain(ids: number[], activeId: number, overId: number): number[] {
  const from = ids.indexOf(activeId);
  const to = ids.indexOf(overId);
  if (from < 0 || to < 0 || from === to) return ids;
  const next = [...ids];
  const [moved] = next.splice(from, 1);
  next.splice(to, 0, moved);
  return next;
}

export function orderCaptainIds(
  ids: number[],
  order: DraftCaptainOrder,
  ranks: ReadonlyMap<number, number | null>,
  seed: number
): number[] {
  if (order === "manual") return [...ids];
  if (order === "weakest_first" || order === "strongest_first") {
    const direction = order === "weakest_first" ? 1 : -1;
    return [...ids].sort((left, right) => {
      const leftRank = ranks.get(left) ?? -1;
      const rightRank = ranks.get(right) ?? -1;
      return ((leftRank - rightRank) || left - right) * direction;
    });
  }

  // Mulberry32 keeps the UI preview stable and sends the same seed to the server.
  let state = seed >>> 0;
  const random = () => {
    state += 0x6d2b79f5;
    let value = state;
    value = Math.imul(value ^ (value >>> 15), value | 1);
    value ^= value + Math.imul(value ^ (value >>> 7), value | 61);
    return ((value ^ (value >>> 14)) >>> 0) / 4294967296;
  };
  const shuffled = [...ids];
  for (let index = shuffled.length - 1; index > 0; index -= 1) {
    const target = Math.floor(random() * (index + 1));
    [shuffled[index], shuffled[target]] = [shuffled[target], shuffled[index]];
  }
  return shuffled;
}

export function buildDraftSchedule(
  teamIds: number[],
  rounds: number,
  format: DraftFormat,
  roundRules: string[]
): DraftScheduleRound[] {
  return Array.from({ length: rounds }, (_, index) => {
    const round = index + 1;
    const customRule = roundRules[index] ?? "linear";
    const reverse =
      format === "snake" ? index % 2 === 1 : format === "custom" && customRule === "reverse";
    return {
      round,
      teamIds: reverse ? [...teamIds].reverse() : [...teamIds],
      rule: format === "snake" ? (reverse ? "reverse" : "linear") : format === "custom" ? customRule : "linear"
    };
  });
}

export function validateSetupStep(
  step: DraftSetupStep,
  state: DraftSetupValidationState
): string[] {
  const errors: string[] = [];
  if (step === "config") {
    if (state.teamSize < 2 || state.teamSize > 9) errors.push("team_size_out_of_range");
    if (state.pickTimeSeconds < 10 || state.pickTimeSeconds > 600) {
      errors.push("pick_time_out_of_range");
    }
  }
  if (step === "pool" && !state.poolReady) errors.push("pool_not_ready");
  if (step === "captains" && state.captainIds.length === 0) errors.push("captains_required");
  if (step === "review" && !state.previewFeasible) errors.push("preview_infeasible");
  return errors;
}

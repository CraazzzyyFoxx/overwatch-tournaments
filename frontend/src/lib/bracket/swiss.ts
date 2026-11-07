import { duelSeats, duelWinner } from "@/lib/encounter/seats";
import { isEncounterCompleted } from "@/lib/encounter/status";

import type { Encounter } from "@/types/encounter.types";
import type { StageSummary } from "@/types/tournament.types";

import type { BracketMatch, RoundGroup } from "./view";

/** The two seats' team ids, slot 1 first; 0 while a seat is empty or has no source team. */
function teamIdsOf(match: BracketMatch): [number, number] {
  const [one, two] = duelSeats(match.teams);
  return [one?.team_id ?? 0, two?.team_id ?? 0];
}

function scoresOf(match: BracketMatch) {
  const [one, two] = duelSeats(match.teams);
  return { one: one?.score ?? 0, two: two?.score ?? 0 };
}

interface SwissRecord {
  wins: number;
  draws: number;
  losses: number;
}

interface SwissPool {
  /** "1-0", or "1-0-0" (W-D-L) once the stage has a draw anywhere. */
  label: string;
  matches: BracketMatch[];
}

interface SwissRound {
  round: number;
  /** Best record first: 2-0, 1-1, 0-2. */
  pools: SwissPool[];
}

export interface SwissPools {
  rounds: SwissRound[];
  /**
   * Match id → the seat whose record differs from its pool's (a Monrad float
   * down), and that record. The match sits in its better team's pool.
   */
  floats: Map<number, { slot: 1 | 2; label: string }>;
}

const ZERO: SwissRecord = { wins: 0, draws: 0, losses: 0 };

/** Positive: `left` is the better record. */
function compareRecords(left: SwissRecord, right: SwissRecord) {
  return left.wins - right.wins || left.draws - right.draws || right.losses - left.losses;
}

/**
 * A Swiss stage's rounds, each split into pools by the record its teams
 * brought into it — the HLTV / major view of a Swiss stage.
 *
 * A team that is in the stage (it plays some round) but not in this one sat
 * the round out on a bye, scored as a win.
 * ponytail: a bye always counts as a win; read `swiss_bye_points` here if a
 * stage ever pays a bye less than a win.
 */
export function swissPools(groups: RoundGroup[]): SwissPools {
  const ordered = [...groups].sort((left, right) => left.round - right.round);
  const stageTeams = new Set<number>();
  let hasDraw = false;
  for (const group of ordered) {
    for (const match of group.matches) {
      for (const teamId of teamIdsOf(match)) if (teamId > 0) stageTeams.add(teamId);
      if (isEncounterCompleted(match) && duelWinner(scoresOf(match)) == null) hasDraw = true;
    }
  }
  const format = ({ wins, draws, losses }: SwissRecord) =>
    hasDraw ? `${wins}-${draws}-${losses}` : `${wins}-${losses}`;

  const records = new Map<number, SwissRecord>();
  const recordOf = (teamId: number) => records.get(teamId) ?? ZERO;
  const add = (teamId: number, key: keyof SwissRecord) => {
    const record = recordOf(teamId);
    records.set(teamId, { ...record, [key]: record[key] + 1 });
  };

  const floats: SwissPools["floats"] = new Map();
  const rounds = ordered.map((group) => {
    const pools = new Map<string, { record: SwissRecord; matches: BracketMatch[] }>();
    for (const match of group.matches) {
      const [oneId, twoId] = teamIdsOf(match);
      const one = recordOf(oneId);
      const two = recordOf(twoId);
      const oneBetter = compareRecords(one, two) >= 0;
      const record = oneBetter ? one : two;
      const label = format(record);
      if (compareRecords(one, two) !== 0) {
        floats.set(
          match.id,
          oneBetter ? { slot: 2, label: format(two) } : { slot: 1, label: format(one) }
        );
      }
      const pool = pools.get(label) ?? { record, matches: [] };
      pool.matches.push(match);
      pools.set(label, pool);
    }

    const played = new Set<number>();
    for (const match of group.matches) {
      const [oneId, twoId] = teamIdsOf(match);
      played.add(oneId);
      played.add(twoId);
      if (!isEncounterCompleted(match)) continue;
      const winner = duelWinner(scoresOf(match));
      if (winner == null) {
        add(oneId, "draws");
        add(twoId, "draws");
      } else {
        add(oneId, winner === 1 ? "wins" : "losses");
        add(twoId, winner === 1 ? "losses" : "wins");
      }
    }
    for (const teamId of stageTeams) {
      if (!played.has(teamId)) add(teamId, "wins");
    }

    return {
      round: group.round,
      pools: [...pools.entries()]
        .sort((left, right) => compareRecords(right[1].record, left[1].record))
        .map(([label, pool]) => ({ label, matches: pool.matches }))
    };
  });

  return { rounds, floats };
}

/**
 * How many encounters a Swiss scope of `teamCount` teams plays in all. Mirror
 * of tournament-service `swiss.projected_encounters`: exact without thresholds;
 * with them the record groups are replayed, exact while every group is even (a
 * float down goes to the better record, the bye to the last team, no draws).
 */
export function projectedSwissEncounters(
  teamCount: number,
  maxRounds: number,
  qualifyWins: number | null,
  eliminateLosses: number | null
): number {
  if (qualifyWins == null && eliminateLosses == null) {
    // A bye is no encounter; as many rounds as a full circle is a round robin.
    const circle = teamCount % 2 ? teamCount : teamCount - 1;
    return Math.max(0, Math.min(maxRounds, circle)) * Math.floor(teamCount / 2);
  }
  const records: SwissRecord[] = Array.from({ length: teamCount }, () => ({ ...ZERO }));
  let total = 0;
  for (let round = 0; round < maxRounds; round++) {
    // Every undecided team has played as many rounds, so its wins alone rank it.
    const field = records
      .filter(
        (r) =>
          !(qualifyWins != null && r.wins >= qualifyWins) &&
          !(eliminateLosses != null && r.losses >= eliminateLosses)
      )
      .sort((a, b) => b.wins - a.wins);
    if (field.length < 2) break;
    if (field.length % 2) field.pop()!.wins += 1;
    for (let i = 0; i < field.length; i += 2) {
      field[i].wins += 1;
      field[i + 1].losses += 1;
    }
    total += field.length / 2;
  }
  return total;
}

/**
 * The encounters the started scopes of every unfinished Swiss stage have not
 * drawn yet: a Swiss draws a round at a time, so the encounter list undercounts
 * it. Twin of the admin dashboard's `_swiss_encounters_to_come`.
 *
 * shortcut: a scope's teams are the ones its encounters seat (the overview loads
 * no stage inputs), so an odd field misses its round-1 bye team until round 2,
 * and a scope out of pairings is projected until its stage completes; read the
 * stage inputs if that ever shows.
 */
export function swissEncountersToCome(
  stages: readonly StageSummary[],
  encounters: readonly Encounter[]
): number {
  const swissStages = new Map(
    stages
      .filter(
        (stage) =>
          (stage.stage_type === "swiss" || stage.stage_type === "individual_swiss") &&
          stage.status !== "completed"
      )
      .map((stage) => [stage.id, stage])
  );
  const scopes = new Map<
    string,
    { stage: StageSummary; drawn: number; firstRound: number; teams: Set<number> }
  >();
  for (const encounter of encounters) {
    const stage = encounter.stage_id == null ? undefined : swissStages.get(encounter.stage_id);
    if (!stage) continue;
    const key = `${stage.id}:${encounter.stage_item_id ?? ""}`;
    let scope = scopes.get(key);
    if (!scope) {
      scope = { stage, drawn: 0, firstRound: 0, teams: new Set() };
      scopes.set(key, scope);
    }
    scope.drawn += 1;
    if (encounter.round === 1) scope.firstRound += 1;
    for (const seat of encounter.teams) if (seat.team_id != null) scope.teams.add(seat.team_id);
  }

  let toCome = 0;
  for (const { stage, drawn, firstRound, teams } of scopes.values()) {
    const total =
      stage.stage_type === "individual_swiss"
        ? stage.max_rounds * firstRound
        : projectedSwissEncounters(
            teams.size,
            stage.max_rounds,
            stage.swiss_qualify_wins,
            stage.swiss_eliminate_losses
          );
    toCome += Math.max(0, total - drawn);
  }
  return toCome;
}

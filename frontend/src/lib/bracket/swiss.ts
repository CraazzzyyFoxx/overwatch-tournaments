import { isEncounterCompleted } from "@/lib/encounter/status";

import type { BracketMatch, RoundGroup } from "./view";

interface SwissRecord {
  wins: number;
  draws: number;
  losses: number;
}

export interface SwissPool {
  /** "1-0", or "1-0-0" (W-D-L) once the stage has a draw anywhere. */
  label: string;
  matches: BracketMatch[];
}

export interface SwissRound {
  round: number;
  /** Best record first: 2-0, 1-1, 0-2. */
  pools: SwissPool[];
}

export interface SwissPools {
  rounds: SwissRound[];
  /**
   * Match id → the side whose record differs from its pool's (a Monrad float
   * down), and that record. The match sits in its better team's pool.
   */
  floats: Map<number, { side: "home" | "away"; label: string }>;
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
      if (match.home_team_id > 0) stageTeams.add(match.home_team_id);
      if (match.away_team_id > 0) stageTeams.add(match.away_team_id);
      if (isEncounterCompleted(match) && match.score.home === match.score.away) hasDraw = true;
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
      const home = recordOf(match.home_team_id);
      const away = recordOf(match.away_team_id);
      const homeBetter = compareRecords(home, away) >= 0;
      const record = homeBetter ? home : away;
      const label = format(record);
      if (compareRecords(home, away) !== 0) {
        floats.set(
          match.id,
          homeBetter ? { side: "away", label: format(away) } : { side: "home", label: format(home) }
        );
      }
      const pool = pools.get(label) ?? { record, matches: [] };
      pool.matches.push(match);
      pools.set(label, pool);
    }

    const played = new Set<number>();
    for (const match of group.matches) {
      played.add(match.home_team_id);
      played.add(match.away_team_id);
      if (!isEncounterCompleted(match)) continue;
      const { home, away } = match.score;
      if (home === away) {
        add(match.home_team_id, "draws");
        add(match.away_team_id, "draws");
      } else {
        add(match.home_team_id, home > away ? "wins" : "losses");
        add(match.away_team_id, home > away ? "losses" : "wins");
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

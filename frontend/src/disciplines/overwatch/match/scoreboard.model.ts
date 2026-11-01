import { LogStatsName } from "../stat-names";
import {
  STAT_META,
  activePlayers,
  compareByClass,
  playerStat,
  resolveMatchMvpPlacement,
  type MatchStatsPlayer,
  type MatchStatsTeam
} from "./stats";

/** The sort key of the MVP column; every other key is a stat code. */
export const MVP_SORT = "mvp";
export type SortKey = LogStatsName | typeof MVP_SORT;

/** Lower is better for the MVP place and for `reverted` stats: they sort ascending first. */
export function sortsAscending(key: SortKey): boolean {
  return key === MVP_SORT || Boolean(STAT_META[key]?.reverted);
}

/** Whether the player has a value to draw: a stat the round never reported, or a percentage past 1, is absent. */
export function hasStat(player: Pick<MatchStatsPlayer, "stats">, round: number, name: LogStatsName): boolean {
  const value = player.stats?.[round]?.[name];
  if (typeof value !== "number" || !Number.isFinite(value)) return false;
  return !(STAT_META[name]?.format === "percent" && value > 1);
}

/**
 * Per column, the best value across the active players of both teams (the highest, the lowest for a `reverted`
 * stat); `null` when nobody has a value or every value is zero (a best of nothing is not a best).
 */
export function columnBest(
  home: Pick<MatchStatsTeam, "players"> | null,
  away: Pick<MatchStatsTeam, "players"> | null,
  round: number,
  names: LogStatsName[]
): Record<string, number | null> {
  const players = [...activePlayers(home, round), ...activePlayers(away, round)];
  const out: Record<string, number | null> = {};
  for (const name of names) {
    const values = players.filter((player) => hasStat(player, round, name)).map((player) => playerStat(player, round, name));
    const reach = Math.max(0, ...values.map(Math.abs));
    out[name] = values.length === 0 || reach === 0 ? null : STAT_META[name]?.reverted ? Math.min(...values) : Math.max(...values);
  }
  return out;
}

/** A team's active players: by class then MVP place, or by the sorted column (ties keep the class order). */
export function orderPlayers(team: MatchStatsTeam, round: number, sort: SortKey | null): MatchStatsPlayer[] {
  const byClass = compareByClass(round);
  const players = activePlayers(team, round);
  if (sort === null) return players.sort(byClass);
  const ascending = sortsAscending(sort);
  const value = (player: MatchStatsPlayer) =>
    sort === MVP_SORT
      ? (resolveMatchMvpPlacement(player, round) ?? Number.POSITIVE_INFINITY)
      : playerStat(player, round, sort);
  return players.sort((a, b) => {
    const [x, y] = [value(a), value(b)];
    if (x === y) return byClass(a, b);
    return ascending ? (x < y ? -1 : 1) : x > y ? -1 : 1;
  });
}

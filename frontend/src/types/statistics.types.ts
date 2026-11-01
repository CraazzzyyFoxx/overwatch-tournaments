import type { Schema } from "@/types/api";

export interface TournamentStatistics {
  id: number;
  name: string;
  players_count: number;
  avg_sr: number;
  avg_closeness: number;
}

/** One tournament's average division per top-level role code of its game's rated dimension (unplayed roles absent). */
export type TournamentDivisionStatistics = Schema<"tournament.DivisionStatistics">;

export interface PlayerStatistics {
  id: number;
  name: string;
  value: number;
}

/** `/statistics/players` orderings (always descending); `titles` is the default and never written to the URL. */
export const PLAYER_SORTS = ["titles", "tournaments", "maps_won", "winrate"] as const;
export type PlayerSort = (typeof PLAYER_SORTS)[number];

/** One row of the all-time players table. `rank` is over the whole population; a search never renumbers it. */
export type PlayerLeaderboardRow = Schema<"stats.PlayerLeaderboardRow">;

/** The generated enum, as the literal union every caller already spells. */
export type StatRecordCode = `${Schema<"stats.StatRecord">["code"]}`;

/** One all-time record: its holder, the value and where it happened. A record with no data is absent, never null. */
export type StatRecord = Omit<Schema<"stats.StatRecord">, "code"> & { code: StatRecordCode };

/** One game's finished games per map, grouped by mode (a `null` mode last), most played first. */
export type MapStatsResponse = Schema<"stats.MapStatsResponse">;

export interface TournamentOverall {
  tournaments: number;
  teams: number;
  players: number;
  champions: number;
  /** Encounters (series) with a result. */
  encounters: number;
  /** Maps played (`matches.match` rows). */
  maps: number;
  /** Distinct calendar days covered by the tournaments' start..end dates. */
  days: number;
  /** Total played map time, whole hours. */
  hours: number;
}

export interface UserTournamentStat {
  value: number;
  rank: number;
  total: number;
}

/** One player's row on a character's leaderboard (per-10 averages over the player's eligible matches). */
export type CharacterLeaderboardEntry = Schema<"stats.CharacterLeaderboardEntry">;
/**
 * A leaderboard page plus every division grid its rows' `div` is a number on (`division_grid_version_id`). Across
 * workspaces none: `div` is then a number on the game's native ladder (`null` for a game without one).
 */
export type CharacterLeaderboardResponse = Omit<Schema<"stats.CharacterLeaderboardResponse">, "results"> & {
  results: CharacterLeaderboardEntry[];
};

export interface TournamentStatistics {
  id: number;
  name: string;
  players_count: number;
  avg_sr: number;
  avg_closeness: number;
}

export interface TournamentDivisionStatistics {
  id: number;
  name: string;
  tank_avg_div: number | null;
  damage_avg_div: number | null;
  support_avg_div: number | null;
}

export interface PlayerStatistics {
  id: number;
  name: string;
  value: number;
}

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

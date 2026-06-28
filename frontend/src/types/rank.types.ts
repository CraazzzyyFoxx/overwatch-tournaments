// Rank history (OverFast) — mirrors parser-service src/schemas/rank_history.py

export type RankPlatform = "pc" | "console";
export type RankRoleKey = "tank" | "damage" | "support";

export interface RankHistoryPoint {
  captured_at: string;
  rank_value: number | null;
  division: string | null;
  tier: number | null;
  is_ranked: boolean;
  season: number | null;
}

export interface RankSeries {
  social_account_id: number;
  battle_tag: string;
  role: string;
  platform: string;
  points: RankHistoryPoint[];
  current: RankHistoryPoint | null;
  peak_rank_value: number | null;
  latest_captured_at: string | null;
}

export interface RankHistoryResponse {
  user_id: number | null;
  series: RankSeries[];
  generated_at: string;
}

export interface CurrentRank {
  social_account_id: number;
  battle_tag: string;
  role: string;
  platform: string;
  rank_value: number | null;
  division: string | null;
  tier: number | null;
  is_ranked: boolean;
  season: number | null;
  captured_at: string;
}

export interface CurrentRanksResponse {
  user_id: number | null;
  ranks: CurrentRank[];
  generated_at: string;
}

export interface RankHistoryQuery {
  platform?: RankPlatform;
  role?: RankRoleKey;
  socialAccountId?: number;
  dateFrom?: string;
  dateTo?: string;
  granularity?: "raw" | "daily" | "hourly";
}

import { LogStatsName } from "@/types/stats.types";

export interface Hero {
  id: number;
  created_at: Date;
  updated_at: Date | null;
  name: string;
  slug: string;
  image_path: string;
  // Backend uses `type` (Tank/Damage/Support). Keep `role` for legacy callers.
  type?: string;
  role: string;
  color: string;
}

export interface HeroPlaytime {
  hero: Hero;
  playtime: number;
}

export interface HeroBestStat {
  encounter_id: number;
  map_name: string;
  map_image_path: string;
  value: number;
  tournament_name: string;
  player_name: string;
}

export interface HeroStat {
  name: LogStatsName;
  overall: number;
  best: HeroBestStat;
  avg_10: number;
  best_all: HeroBestStat | null;
  avg_10_all: number;
}

export interface HeroWithUserStats {
  hero: Hero;
  stats: HeroStat[];
}

export interface HeroLeaderboardEntry {
  rank: number;
  user_id: number;
  username: string;
  player_name: string;
  role: string | null;
  div: number;
  games_played: number;
  playtime_seconds: number;
  per10_eliminations: number;
  per10_healing: number;
  per10_deaths: number;
  per10_damage: number;
  per10_final_blows: number;
  per10_damage_blocked: number;
  per10_solo_kills: number;
  per10_obj_kills: number;
  per10_defensive_assists: number;
  per10_offensive_assists: number;
  per10_all_damage: number;
  per10_damage_taken: number;
  per10_self_healing: number;
  per10_ultimates_used: number;
  per10_multikills: number;
  per10_env_kills: number;
  per10_crit_hits: number;
  avg_weapon_accuracy: number;
  avg_crit_accuracy: number;
  kd: number;
  kda: number;
}

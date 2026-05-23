import { Hero, HeroPlaytime } from "@/types/hero.types";
import { Player } from "@/types/team.types";
import { Encounter, Match } from "@/types/encounter.types";
import { MapRead } from "@/types/map.types";
import { LogStatsName } from "@/types/stats.types";
import { UserTournamentStat } from "@/types/statistics.types";
import { Tournament } from "@/types/tournament.types";
import { DivisionGridVersion } from "@/types/workspace.types";

export interface UserDiscord {
  id: number;
  user_id: number;
  created_at: Date;
  updated_at: Date | null;
  name: string;
}

export interface UserBattleTag {
  id: number;
  created_at: Date;
  updated_at: Date | null;
  name: string;
  tag: number;
  battle_tag: string;
}

export interface UserTwitch {
  id: number;
  created_at: Date;
  updated_at: Date | null;
  name: string;
}

export interface User {
  id: number;
  created_at: Date;
  updated_at: Date | null;
  name: string;
  avatar_url: string | null;
  discord: UserDiscord[];
  battle_tag: UserBattleTag[];
  twitch: UserTwitch[];
}

export interface UserRole {
  role: string;
  tournaments: number;
  maps_won: number;
  maps: number;
  division: number;
  division_grid_version: DivisionGridVersion | null;
}

export interface UserTournamentWithStats {
  id: number;
  number: number;
  name: string;
  division: number;
  role: string;
  group_placement: number;
  playoff_placement: number;
  maps_won: number;
  maps: number;
  playtime: number;

  stats: Record<LogStatsName, UserTournamentStat>;
}

export interface MatchWithUserStats extends Match {
  performance: number;
  heroes: Hero[];
}

// @ts-ignore
export interface EncounterWithUserStats extends Encounter {
  matches: MatchWithUserStats[];
}

export interface UserTournament {
  id: number;
  name: string;
  number: number;
  is_league: boolean;
  team_id: number;
  team: string;
  players: Player[];
  closeness: number;
  placement: number;
  count_teams: number;
  won: number;
  lost: number;
  draw: number;
  maps_won: number;
  maps_lost: number;
  division: number;
  division_grid_version: DivisionGridVersion | null;
  role: string;

  encounters: EncounterWithUserStats[];
}

export interface UserProfile {
  tournaments_count: number;
  tournaments_won: number;
  maps_total: number;
  maps_won: number;
  avg_closeness: number | null;
  avg_placement: number | null;
  avg_playoff_placement: number | null;
  avg_group_placement: number | null;
  most_played_hero: Hero;

  roles: UserRole[];
  hero_statistics: HeroPlaytime[];
  tournaments: Tournament[];
}

export interface UserMapRead {
  map: MapRead;
  count: number;
  win: number;
  loss: number;
  draw: number;
  win_rate: number;
  heroes?: HeroPlaytime[];
  hero_stats?: UserMapHeroStats[] | null;
}

export interface UserMapHeroStats {
  hero: Hero;
  games: number;
  win: number;
  loss: number;
  draw: number;
  win_rate: number;
  playtime_seconds: number;
  playtime_share_on_map: number;
}

export interface UserMapHighlight {
  map: MapRead;
  count: number;
  win: number;
  loss: number;
  draw: number;
  win_rate: number;
}

export interface UserMapsOverall {
  total_maps: number;
  total_games: number;
  win: number;
  loss: number;
  draw: number;
  win_rate: number;
}

export interface UserMapsSummary {
  overall: UserMapsOverall;
  most_played: UserMapHighlight | null;
  best: UserMapHighlight | null;
  worst: UserMapHighlight | null;
}

export interface UserBestTeammate {
  user: User;
  tournaments: number;
  winrate: number;
  stats: Record<LogStatsName, number>;
}

export interface MinimizedUser {
  id: number;
  name: string;
}

export type UserRoleType = "Tank" | "Damage" | "Support";

export interface UserOverviewRoleDivision {
  role: UserRoleType;
  division: number;
}

export interface UserOverviewHeroMetric {
  name: LogStatsName;
  avg_10: number;
}

export interface UserOverviewHero {
  hero: Hero;
  playtime_seconds: number;
  metrics: UserOverviewHeroMetric[];
}

export interface UserOverviewAverages {
  avg_closeness: number | null;
  avg_placement: number | null;
  avg_playoff_placement: number | null;
  avg_group_placement: number | null;
}

export interface UserOverviewRow {
  id: number;
  name: string;
  roles: UserOverviewRoleDivision[];
  top_heroes: UserOverviewHero[];
  tournaments_count: number;
  achievements_count: number;
  averages: UserOverviewAverages;
}

export interface UserOverviewStats {
  total_players: number;
  with_logs_count: number;
  with_logs_pct: number;
  avg_tournaments_per_player: number;
  median_tournaments_per_player: number;
  active_last_30d: number;
  active_last_30d_pct: number;
  tank_count: number;
  damage_count: number;
  support_count: number;
  flex_count: number;
}

export interface UserCatalogEntry {
  id: number;
  name: string;
  roles: UserOverviewRoleDivision[];
  top_heroes: UserOverviewHero[];
  tournaments_count: number;
  achievements_count: number;
  avg_placement: number | null;
}

export interface UserCatalogLetter {
  letter: string;
  count: number;
  users: UserCatalogEntry[];
}

export interface UserCatalogResponse {
  letters: UserCatalogLetter[];
  total: number;
  available_letters: string[];
}

export type UserCompareBaselineMode = "target_user" | "global" | "cohort";

export interface UserCompareUser {
  id: number;
  name: string;
}

export interface UserCompareBaselineInfo {
  mode: UserCompareBaselineMode;
  sample_size: number;
  target_user: UserCompareUser | null;
  role: UserRoleType | null;
  div_min: number | null;
  div_max: number | null;
}

export type UserCompareBetterWorse = "better" | "worse" | "equal";

export interface UserCompareMetric {
  key: string;
  label: string;
  subject_value: number | null;
  baseline_value: number | null;
  delta: number | null;
  delta_percent: number | null;
  better_worse: UserCompareBetterWorse | null;
  higher_is_better: boolean;
  subject_rank: number | null;
  subject_percentile: number | null;
}

export interface UserCompareResponse {
  subject: UserCompareUser;
  baseline: UserCompareBaselineInfo;
  metrics: UserCompareMetric[];
}

export interface UserHeroCompareMetric {
  stat: LogStatsName;
  left_value: number;
  right_value: number;
  delta: number;
  delta_percent: number | null;
  better_worse: UserCompareBetterWorse | null;
  higher_is_better: boolean;
}

export interface UserHeroCompareResponse {
  subject: UserCompareUser;
  target: UserCompareUser | null;
  baseline: UserCompareBaselineInfo;
  subject_hero: Hero | null;
  target_hero: Hero | null;
  map: MapRead | null;
  left_playtime_seconds: number;
  right_playtime_seconds: number;
  metrics: UserHeroCompareMetric[];
}

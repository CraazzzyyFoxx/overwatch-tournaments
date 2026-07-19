import { Hero, HeroPlaytime } from "@/types/hero.types";
import { Score } from "@/types/encounter.types";
import { MapRead } from "@/types/map.types";
import { LogStatsName } from "@/types/stats.types";
import { UserTournamentStat } from "@/types/statistics.types";
import { DivisionGridVersion } from "@/types/workspace.types";

export type SocialProvider = "battlenet" | "discord" | "twitch" | "boosty" | "vk" | "youtube";

export interface SocialAccount {
  id: number;
  user_id: number;
  provider: SocialProvider;
  username: string;
  url: string | null;
  is_verified: boolean;
  is_primary: boolean;
  /** Display visibility (populated by the admin profile dialog read). */
  visible_global?: boolean;
  visible_workspace_ids?: number[];
}

export interface User {
  id: number;
  created_at: Date;
  updated_at: Date | null;
  name: string;
  avatar_url: string | null;
  social_accounts: SocialAccount[];
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
  /** Grid the `division` was resolved against — render its icon on this grid,
   * not the workspace default. */
  division_grid_version: DivisionGridVersion | null;
  role: string;
  group_placement: number;
  playoff_placement: number;
  maps_won: number;
  maps: number;
  playtime: number;

  stats: Record<LogStatsName, UserTournamentStat>;
}

/**
 * Narrow projections for user-scoped API responses.
 *
 * After P3-A these shapes are defined by `app-service` and don't reuse the
 * canonical Tournament/Encounter/Match/Player types from tournament-service.
 * They contain only the fields the user pages render.
 */

export interface UserTournamentSummary {
  id: number;
  number: number | null;
  name: string;
  is_league: boolean;
  is_finished?: boolean;
  status?: string | null;
  division_grid_version: DivisionGridVersion | null;
}

export interface UserTournamentPlayer {
  id: number;
  name: string;
  role: string | null;
  sub_role: string | null;
  rank: number;
  division: number;
  user_id: number;
  is_substitution: boolean;
  is_newcomer: boolean;
  is_newcomer_role: boolean;
  related_player_id: number | null;
  relative_player?: number | null;
  /** Average MVP placement across the player's matches (1 = MVP/best). */
  avg_mvp?: number | null;
  /** Player's top signature heroes (same shape as per-match `heroes`). */
  heroes?: Hero[];
}

export interface UserEncounterTournament {
  id: number;
  name: string;
  number: number | null;
  is_league: boolean;
  is_finished?: boolean;
  status?: string | null;
}

export interface UserEncounterStageSummary {
  id: number;
  name: string;
}

export interface UserEncounterStageItemSummary {
  id: number;
  name: string;
}

export interface UserEncounterTeamPlayerRef {
  id: number;
  user_id: number;
  role: string | null;
  name: string;
}

export interface UserEncounterTeamSummary {
  id: number;
  name: string;
  players: UserEncounterTeamPlayerRef[];
}

export interface MatchWithUserStats {
  id: number;
  home_team_id: number | null;
  away_team_id: number | null;
  score: Score;
  time: number;
  log_name: string;
  encounter_id: number;
  map_id: number;
  code: string | null;
  map: MapRead | null;
  performance: number | null;
  impact_rank?: number | null;
  impact_points?: number | null;
  overperformance_score?: number | null;
  overperformance_badge?: boolean;
  heroes: Hero[];
}

export interface EncounterWithUserStats {
  id: number;
  name: string;
  home_team_id: number | null;
  away_team_id: number | null;
  score: Score;
  round: number;
  best_of: number;
  tournament_id: number;
  status: string;
  closeness: number | null;
  has_logs: boolean;
  result_status: string;
  user_team_id: number | null;
  tournament: UserEncounterTournament | null;
  stage: UserEncounterStageSummary | null;
  stage_item: UserEncounterStageItemSummary | null;
  home_team: UserEncounterTeamSummary | null;
  away_team: UserEncounterTeamSummary | null;
  matches: MatchWithUserStats[];
}

export interface UserTournament {
  id: number;
  name: string;
  number: number;
  is_league: boolean;
  team_id: number;
  team: string;
  players: UserTournamentPlayer[];
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
  heroes_count?: number;

  roles: UserRole[];
  hero_statistics: HeroPlaytime[];
  tournaments: UserTournamentSummary[];
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
  maps: number;
  winrate: number;
  stats: Record<LogStatsName, number>;
}

export interface UserOpponentStat {
  name: string;
  wins: number;
  losses: number;
  draws: number;
}

export interface UserStageRecord {
  w: number;
  l: number;
}

export interface UserMatchesSummary {
  opponents: UserOpponentStat[];
  stages: Record<"group" | "playoffs" | "finals", UserStageRecord>;
}

/** One player's standing in a tournament lobby for a single stat. */
export interface LobbyLeaderboardEntry {
  rank: number;
  /** The player's user id (matches the profile route id). */
  player_id: number;
  name: string;
  value: number;
}

/** Full per-stat ranking of every player in a tournament lobby. */
export interface LobbyLeaderboard {
  stat: string;
  total_players: number;
  entries: LobbyLeaderboardEntry[];
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

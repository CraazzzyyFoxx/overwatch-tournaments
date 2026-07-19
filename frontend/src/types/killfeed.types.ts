import { Hero } from "@/types/hero.types";

/** One kill from `matches.kill_feed` (hero = the hero at the moment of the kill). */
export interface KillFeedEntry {
  time: number;
  round: number;
  fight: number;
  ability: string | null;
  damage: number;
  is_critical_hit: boolean;
  is_environmental: boolean;
  killer_user_id: number;
  killer_team_id: number;
  killer_hero: Hero;
  victim_user_id: number;
  victim_team_id: number;
  victim_hero: Hero;
}

/** A non-kill timeline event (ultimate cast / resurrect) from `matches.assists`. */
export interface MatchTimelineEvent {
  time: number;
  round: number;
  /** "ultimate_start" | "mercy_rez" */
  name: string;
  user_id: number;
  team_id: number;
  hero: Hero | null;
  related_user_id: number | null;
  related_team_id: number | null;
}

export interface MatchKillFeed {
  match_id: number;
  kills: KillFeedEntry[];
  events: MatchTimelineEvent[];
}

import type { Schema } from "@/types/api";
import { User } from "@/types/user.types";
import type { CatalogEntityRead } from "@/types/catalog.types";

export type AchievementCategory = "overall" | "hero" | "division" | "team" | "standing" | "match";
type AchievementScope = "global" | "tournament" | "match";

export type ConditionNode =
  | { AND: ConditionNode[] }
  | { OR: ConditionNode[] }
  | { NOT: ConditionNode }
  | { type: string; params: Record<string, unknown> };

export interface Achievement {
  id: number;
  created_at: Date;
  updated_at: Date | null;
  name: string;
  slug: string;
  description_ru: string;
  description_en: string;
  image_url: string | null;
  /** The game the rule belongs to; (discipline, slug) is its public identity. */
  discipline: string;
  entity_id: number | null;
  /** The linked catalog character; present only when `entities=entity` was requested. */
  entity?: CatalogEntityRead | null;

  category: AchievementCategory | null;
  scope: AchievementScope | null;
  condition_tree: ConditionNode | null;

  count: number | null;
  rarity: number;
}

interface AchievementTournamentLink {
  id: number;
  name: string;
}

/** The match an achievement was earned in and every participant of it, in slot order (`score` is `result?.score`/`team_facts.score`). */
export interface AchievementMatchLink {
  id: number;
  encounter_id: number;
  map_id: number;
  log_name: string | null;
  /** Seconds. The link carries no timestamp: a duration is never a date. */
  duration_s: number | null;
  participants: Schema<"stats.MatchParticipantRead">[];
}

export interface AchievementRarity extends Achievement {
  count: number;
  /** Where it was earned: filled only when the read names `tournaments` / `matches` in `entities`. */
  tournaments: AchievementTournamentLink[];
  matches: AchievementMatchLink[];
}

export interface AchievementEarned {
  user: User;
  count: number;
  last_tournament: AchievementTournamentLink | null;
  last_match: AchievementMatchLink | null;
}

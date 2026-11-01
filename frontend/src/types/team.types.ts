import type { RoleRef } from "@/lib/roster/role-ref";
import { PersonDisplay, User } from "@/types/user.types";
import { Tournament, TeamGroup } from "@/types/tournament.types";

export interface Player {
  id: number;
  created_at: Date;
  updated_at: Date | null;
  /** The roster snapshot; render `display` instead. */
  name: string;
  /** What this game's surfaces show; `display.canonical` builds the profile link. */
  display: PersonDisplay;
  /** `null` when the tournament recorded no rank for this player. */
  rank: number | null;
  division: number | null;
  role: RoleRef | null;
  tournament_id: number;
  user_id: number;
  team_id: number;
  is_newcomer: boolean;
  is_newcomer_role: boolean;
  is_substitution: boolean;
  related_player_id: number | null;
  relative_player?: number | null;

  /** Linked identity. `null` when the roster row has no resolvable user. */
  user: User | null;
}

export interface Team {
  id: number;
  created_at: Date;
  updated_at: Date | null;
  name: string;
  /** Uploaded team image (S3 URL). `null` means the team has none — render no image. */
  image_url: string | null;
  avg_sr: number;
  total_sr: number;
  captain_id: number;
  tournament_id: number;
  players: Player[];
  tournament: Tournament | null;
  placement: number | null;
  group: TeamGroup | null;
}

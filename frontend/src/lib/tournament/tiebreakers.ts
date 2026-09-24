// Shared tie-breaker metric catalog + helpers.
//
// Keeps the public StandingsTable, the admin standings page, and the admin
// StageManager config editor in sync with the backend engine metrics
// (see backend `RULE_PRESET_DEFAULTS` / `_metric_value`).
import type { StageType } from "@/types/tournament.types";

export type TiebreakerMetricId =
  | "points"
  | "match_wins"
  | "head_to_head"
  | "median_buchholz"
  | "buchholz"
  | "score_differential"
  | "ffa_game_wins"
  | "ffa_score"
  | "ffa_best_placement"
  | "ffa_last_placement"
  | "manual_override";

// Default English labels. Used as a fallback when no i18n resolver is supplied.
const TIEBREAKER_LABELS: Record<string, string> = {
  points: "Points",
  match_wins: "Match Wins",
  head_to_head: "Head-to-Head",
  median_buchholz: "Median Buchholz",
  buchholz: "Buchholz",
  score_differential: "Score Differential",
  ffa_game_wins: "Game Wins",
  ffa_score: "Score",
  ffa_best_placement: "Best Placement",
  ffa_last_placement: "Last Placement",
  manual_override: "Manual Override"
};

// Ordered catalog presented in the StageManager config editor.
export const ALL_TIEBREAKERS: { id: TiebreakerMetricId; label: string }[] = [
  { id: "points", label: TIEBREAKER_LABELS.points },
  { id: "head_to_head", label: TIEBREAKER_LABELS.head_to_head },
  { id: "median_buchholz", label: TIEBREAKER_LABELS.median_buchholz },
  { id: "buchholz", label: TIEBREAKER_LABELS.buchholz },
  { id: "match_wins", label: TIEBREAKER_LABELS.match_wins },
  { id: "score_differential", label: TIEBREAKER_LABELS.score_differential },
  { id: "manual_override", label: TIEBREAKER_LABELS.manual_override }
];

/**
 * The FFA catalog, in `ffa_default` order (backend `RULE_PRESET_DEFAULTS`).
 *
 * Disjoint from the list above on purpose: an FFA lobby has no opponent
 * pairing, so head-to-head and both Buchholz variants compute nothing there,
 * and a duel encounter has no placement or lobby score.
 */
export const FFA_TIEBREAKERS: { id: TiebreakerMetricId; label: string }[] = [
  { id: "points", label: TIEBREAKER_LABELS.points },
  { id: "ffa_game_wins", label: TIEBREAKER_LABELS.ffa_game_wins },
  { id: "ffa_score", label: TIEBREAKER_LABELS.ffa_score },
  { id: "ffa_best_placement", label: TIEBREAKER_LABELS.ffa_best_placement },
  { id: "ffa_last_placement", label: TIEBREAKER_LABELS.ffa_last_placement },
  { id: "manual_override", label: TIEBREAKER_LABELS.manual_override }
];

/** The metrics the engine can actually compute for `stageType`. */
export function tiebreakersForStageType(
  stageType: StageType
): { id: TiebreakerMetricId; label: string }[] {
  return stageType === "ffa_league" ? FFA_TIEBREAKERS : ALL_TIEBREAKERS;
}

/** Resolve a single metric id to a human label, optionally via an i18n resolver. */
export function tiebreakerLabel(
  id: string,
  labelFor?: (id: string) => string | undefined
): string {
  return labelFor?.(id) ?? TIEBREAKER_LABELS[id] ?? id;
}

/**
 * Render an ordered tie-break list as "Points → Head-to-Head → …".
 * `labelFor` lets callers plug in their i18n translator.
 */
export function formatTiebreakOrder(
  order: string[] | null | undefined,
  labelFor?: (id: string) => string | undefined
): string {
  if (!order || order.length === 0) return "";
  return order.map((id) => tiebreakerLabel(id, labelFor)).join(" → ");
}

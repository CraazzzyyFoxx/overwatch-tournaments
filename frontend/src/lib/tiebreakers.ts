// Shared tie-breaker metric catalog + helpers.
//
// Keeps the public StandingsTable, the admin standings page, and the admin
// StageManager config editor in sync with the backend engine metrics
// (see backend `RULE_PRESET_DEFAULTS` / `_metric_value`).

export type TiebreakerMetricId =
  | "points"
  | "match_wins"
  | "head_to_head"
  | "median_buchholz"
  | "buchholz"
  | "score_differential"
  | "manual_override";

// Default English labels. Used as a fallback when no i18n resolver is supplied.
export const TIEBREAKER_LABELS: Record<string, string> = {
  points: "Points",
  match_wins: "Match Wins",
  head_to_head: "Head-to-Head",
  median_buchholz: "Median Buchholz",
  buchholz: "Buchholz",
  score_differential: "Score Differential",
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

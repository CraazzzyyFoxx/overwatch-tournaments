// Shared tie-breaker metric catalog + helpers.
//
// Keeps the public StandingsTable, the admin standings page, and the admin
// stage editor in sync with the backend engine metrics (see backend
// `RULE_PRESET_DEFAULTS` / `_metric_value`).
import type { StageType } from "@/types/tournament.types";

/**
 * The metric "the sum of one FFA column", prefixed with the column's key.
 *
 * An FFA stage's columns are the organizer's, so this half of the catalogue is
 * not a list: it is built from the columns THAT stage records
 * (`shared.domain.ffa_scoring.FfaRules.columns`), and the direction is the
 * column's own `better`, decided server-side.
 */
export const FFA_STAT_PREFIX = "ffa_stat:";

export type TiebreakerMetricId =
  | "points"
  | "match_wins"
  | "head_to_head"
  | "median_buchholz"
  | "buchholz"
  | "score_differential"
  | "ffa_game_wins"
  | "ffa_best_placement"
  | "ffa_last_placement";

/** A metric a saved order can hold: a fixed one, or one column's sum. */
export type TiebreakerId = TiebreakerMetricId | `ffa_stat:${string}`;

/** What a column sum needs to be named: nothing else of an `FfaColumn`. */
export type TiebreakerColumn = Readonly<{ key: string; label: string }>;

// Default English labels. Used as a fallback when no i18n resolver is supplied.
const TIEBREAKER_LABELS: Record<string, string> = {
  points: "Points",
  match_wins: "Match Wins",
  head_to_head: "Head-to-Head",
  median_buchholz: "Median Buchholz",
  buchholz: "Buchholz",
  score_differential: "Score Differential",
  ffa_game_wins: "Game Wins",
  ffa_best_placement: "Best Placement",
  ffa_last_placement: "Last Placement"
};

// Ordered catalog presented in the stage editor.
export const ALL_TIEBREAKERS: { id: TiebreakerId; label: string }[] = [
  { id: "points", label: TIEBREAKER_LABELS.points },
  { id: "head_to_head", label: TIEBREAKER_LABELS.head_to_head },
  { id: "median_buchholz", label: TIEBREAKER_LABELS.median_buchholz },
  { id: "buchholz", label: TIEBREAKER_LABELS.buchholz },
  { id: "match_wins", label: TIEBREAKER_LABELS.match_wins },
  { id: "score_differential", label: TIEBREAKER_LABELS.score_differential }
];

/**
 * The fixed part of the FFA catalog, in `ffa_default` order (backend
 * `RULE_PRESET_DEFAULTS`).
 *
 * Disjoint from the list above on purpose: an FFA lobby has no opponent
 * pairing, so head-to-head and both Buchholz variants compute nothing there,
 * and a duel encounter has no placement.
 */
export const FFA_TIEBREAKERS: { id: TiebreakerId; label: string }[] = [
  { id: "points", label: TIEBREAKER_LABELS.points },
  { id: "ffa_game_wins", label: TIEBREAKER_LABELS.ffa_game_wins },
  { id: "ffa_best_placement", label: TIEBREAKER_LABELS.ffa_best_placement },
  { id: "ffa_last_placement", label: TIEBREAKER_LABELS.ffa_last_placement }
];

/** One "Sum: <label>" metric per column of the stage, in table order. */
export function ffaStatTiebreakers(
  columns: readonly TiebreakerColumn[]
): { id: TiebreakerId; label: string }[] {
  return columns.map((column) => ({
    id: `${FFA_STAT_PREFIX}${column.key}` as TiebreakerId,
    // A column being configured has a key before it has a label; the key is
    // what the organizer typed, so it stands in until the label arrives.
    label: `Sum: ${column.label || column.key}`
  }));
}

/** The metrics the engine can actually compute for `stageType`. */
export function tiebreakersForStageType(
  stageType: StageType,
  ffaColumns: readonly TiebreakerColumn[] = []
): { id: TiebreakerId; label: string }[] {
  return stageType === "ffa_league"
    ? [...FFA_TIEBREAKERS, ...ffaStatTiebreakers(ffaColumns)]
    : ALL_TIEBREAKERS;
}

/**
 * Resolve a single metric id to a human label, optionally via an i18n resolver.
 *
 * `ffaColumns` names a column sum by its label; a reader that has the saved
 * order but not the stage (the public standings footer) passes none, and the
 * key stands in — it still says which column decided the place.
 */
export function tiebreakerLabel(
  id: string,
  labelFor?: (id: string) => string | undefined,
  ffaColumns: readonly TiebreakerColumn[] = []
): string {
  const resolved = labelFor?.(id);
  if (resolved != null) return resolved;
  if (id.startsWith(FFA_STAT_PREFIX)) {
    const key = id.slice(FFA_STAT_PREFIX.length);
    const column = ffaColumns.find((candidate) => candidate.key === key);
    return `Sum: ${column?.label || key}`;
  }
  return TIEBREAKER_LABELS[id] ?? id;
}

/**
 * Render an ordered tie-break list as "Points → Head-to-Head → …".
 * `labelFor` lets callers plug in their i18n translator.
 */
export function formatTiebreakOrder(
  order: string[] | null | undefined,
  labelFor?: (id: string) => string | undefined,
  ffaColumns: readonly TiebreakerColumn[] = []
): string {
  if (!order || order.length === 0) return "";
  return order.map((id) => tiebreakerLabel(id, labelFor, ffaColumns)).join(" → ");
}

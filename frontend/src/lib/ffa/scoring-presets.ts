/**
 * What an FFA league is scored by, as the stage editor offers it.
 *
 * A stage's `ffa_scoring` is read by the points adder
 * (`shared.domain.ffa_scoring.ffa_rules`): `columns` is what the organizer
 * enters for each team in each game, `placement_points[i]` is what place
 * `i + 1` is worth, and `formula` turns both into the points of that game.
 *
 * The presets below are starting points, not rules: the editor writes back
 * whatever the organizer leaves in the fields.
 */
import type { FfaColumn } from "@/types/ffa.types";

export interface FfaScoringPreset {
  value: string;
  label: string;
  columns: FfaColumn[];
  placementPoints: number[];
  formula: string;
}

/** Mirrors `FFA_MAX_LOBBY_SIZE`: a place past the lobby's size pays nobody. */
export const FFA_MAX_PLACES = 100;

/** Mirrors `FFA_MAX_COLUMNS`: what a stage will store. */
export const FFA_MAX_COLUMNS = 10;

/** `^[a-z][a-z0-9_]{0,23}$` — 24 characters, key included. */
export const FFA_COLUMN_KEY_MAX = 24;

/** Longest column label the backend stores. */
export const FFA_COLUMN_LABEL_MAX = 32;

/** `FORMULA_MAX_LENGTH` of `shared/domain/ffa_formula.py`. */
export const FFA_FORMULA_MAX = 500;

/** Names every formula may read on top of the column keys. */
export const FFA_FORMULA_VARIABLES = ["place", "place_pts", "teams"] as const;

/** The functions the parser accepts (`FUNCTIONS` of `ffa_formula.py`). */
export const FFA_FORMULA_FUNCTIONS = ["min", "max", "abs", "round", "if"] as const;

export const FFA_SCORING_PRESETS: readonly FfaScoringPreset[] = [
  {
    value: "score_only",
    label: "Score only",
    columns: [{ key: "score", label: "Score", public: true, better: "higher" }],
    placementPoints: [],
    formula: "score"
  },
  {
    value: "battle_royale",
    label: "Battle royale",
    columns: [{ key: "kills", label: "Kills", public: true, better: "higher" }],
    placementPoints: [10, 6, 5, 4, 3, 2, 1],
    formula: "place_pts + kills"
  }
];

/** The preset a rule still matches, or `"custom"` once it has been edited. */
export function ffaScoringPresetOf(
  columns: readonly FfaColumn[],
  placementPoints: readonly number[],
  formula: string
): string {
  const preset = FFA_SCORING_PRESETS.find(
    (candidate) =>
      candidate.formula === formula.trim() &&
      candidate.placementPoints.length === placementPoints.length &&
      candidate.placementPoints.every((points, index) => points === placementPoints[index]) &&
      candidate.columns.length === columns.length &&
      candidate.columns.every(
        (column, index) =>
          column.key === columns[index]?.key &&
          column.label === columns[index]?.label &&
          column.public === columns[index]?.public &&
          column.better === columns[index]?.better
      )
  );
  return preset?.value ?? "custom";
}

/** 1 -> "1st", 2 -> "2nd", 11 -> "11th". */
export function ordinalPlace(place: number): string {
  const teens = place % 100;
  if (teens >= 11 && teens <= 13) return `${place}th`;
  return `${place}${["th", "st", "nd", "rd"][place % 10] ?? "th"}`;
}

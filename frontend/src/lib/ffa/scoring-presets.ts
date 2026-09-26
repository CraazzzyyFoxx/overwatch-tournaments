/**
 * What an FFA league pays for, as the stage editor offers it.
 *
 * A stage's `ffa_scoring` is read by the points adder
 * (`shared.domain.ffa_scoring.parse_ffa_rules`): `placement_points[i]` is what
 * place `i + 1` is worth, and every unit of raw score — a kill, an elimination,
 * a lap point — is worth `score_points`. An empty table means placement carries
 * nothing, which is the score-only lobby.
 *
 * The presets below are starting points, not rules: the editor writes back
 * whatever the organizer leaves in the table.
 */

export interface FfaScoringPreset {
  value: string;
  label: string;
  placementPoints: number[];
  scorePoints: number;
}

/** Mirrors `FFA_MAX_LOBBY_SIZE`: a place past the lobby's size pays nobody. */
export const FFA_MAX_PLACES = 100;

/** Longest score label the backend stores (`FfaScoring.score_label`). */
export const FFA_SCORE_LABEL_MAX = 32;

export const FFA_SCORING_PRESETS: readonly FfaScoringPreset[] = [
  { value: "score_only", label: "Score only", placementPoints: [], scorePoints: 1 },
  {
    value: "placement_and_score",
    label: "Placement + score",
    placementPoints: [10, 6, 5, 4, 3, 2, 1, 1],
    scorePoints: 1
  }
];

/** The preset a table still matches, or `"custom"` once it has been edited. */
export function ffaScoringPresetOf(placementPoints: number[], scorePoints: number): string {
  const preset = FFA_SCORING_PRESETS.find(
    (candidate) =>
      candidate.scorePoints === scorePoints &&
      candidate.placementPoints.length === placementPoints.length &&
      candidate.placementPoints.every((points, index) => points === placementPoints[index])
  );
  return preset?.value ?? "custom";
}

/** 1 -> "1st", 2 -> "2nd", 11 -> "11th". */
export function ordinalPlace(place: number): string {
  const teens = place % 100;
  if (teens >= 11 && teens <= 13) return `${place}th`;
  return `${place}${["th", "st", "nd", "rd"][place % 10] ?? "th"}`;
}

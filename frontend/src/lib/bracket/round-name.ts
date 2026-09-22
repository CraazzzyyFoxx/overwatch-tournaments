/**
 * What a bracket round is called — the one place that decides it.
 *
 * Every surface that names a round goes through this: the bracket tree and its
 * phone list, the match lists, the map-pool scopes, the pick-ban scope picker,
 * the admin best-of and round-schedule editors. Otherwise the same round reads
 * "Round 2" on one screen and "UB Semifinal" on another, and an organizer
 * cannot tell they are the same round.
 *
 * The vocabulary is the generator's own (`services/bracket/double_elimination`):
 * `UB Round n` / `UB Semifinal` / `UB Final`, `LB Round n` / `LB Final`,
 * `Grand Final` / `Grand Final Reset`. Single elimination, Swiss and round
 * robin play a flat `Round n` — they have no two brackets to tell apart.
 */

/** A stage's round numbers and which of them are its finals. */
export interface BracketRoundShape {
  /**
   * Every signed round the stage plays, in any order. Decides which round is
   * the upper- and lower-bracket final; an empty list names no round a final.
   */
  rounds: number[];
  /**
   * Rounds the Grand Final (and its reset) occupy, ascending — the first entry
   * is the Grand Final and anything after it a reset. Empty for anything but a
   * double elimination. Comes from `stageFinalRounds` / `bracketRoundShape`.
   */
  finalRounds: number[];
}

/**
 * For a screen that holds no round list: every round keeps its plain depth
 * ("Round 3", "LB Round 2"), and none is promoted to a final on a guess.
 */
export const UNKNOWN_ROUND_SHAPE: BracketRoundShape = { rounds: [], finalRounds: [] };

/** A round's name, as a `bracket.*` message key plus the depth it interpolates. */
export interface BracketRoundLabel {
  key:
    | "round"
    | "semifinal"
    | "final"
    | "upperRound"
    | "upperSemifinal"
    | "upperFinal"
    | "lowerRound"
    | "lowerFinal"
    | "grandFinal"
    | "grandFinalReset";
  /** Depth for the keys that interpolate `{n}`; absent for the named rounds. */
  n?: number;
}

/**
 * What the bracket calls this round. Render it with `useBracketRoundLabel` on a
 * translated screen, `bracketRoundLabelEn` on the admin ones.
 *
 * A shape that knows no rounds still names the finals it was given and falls
 * back to the plain depth elsewhere — a round is never called a final on a
 * guess.
 */
export function bracketRoundLabel(round: number, shape: BracketRoundShape): BracketRoundLabel {
  const { rounds, finalRounds } = shape;

  if (round < 0) {
    const lowerFinal = Math.min(...rounds.filter((entry) => entry < 0), 0);
    return { key: round === lowerFinal ? "lowerFinal" : "lowerRound", n: -round };
  }

  const finalIndex = finalRounds.indexOf(round);
  if (finalIndex === 0) return { key: "grandFinal" };
  if (finalIndex > 0) return { key: "grandFinalReset" };

  // No grand final: single elimination, Swiss, round robin. One bracket, so its
  // rounds carry no side prefix.
  if (finalRounds.length === 0) return { key: "round", n: round };

  // A positive round the shape does not know — a stale `by_round` key past the
  // bracket's depth — belongs to neither bracket, so it keeps its bare number.
  if (!rounds.includes(round)) return { key: "round", n: round };

  const upperFinal = Math.max(
    ...rounds.filter((entry) => entry > 0 && !finalRounds.includes(entry)),
    0
  );
  if (round === upperFinal) return { key: "upperFinal" };
  if (round === upperFinal - 1) return { key: "upperSemifinal" };
  return { key: "upperRound", n: round };
}

/**
 * The bracket's own name for a round, minus the upper bracket's `UB` prefix.
 *
 * For the bracket tree only: its upper rounds are a labelled row of columns, so
 * the prefix repeats what the drawing already says. The lower bracket keeps
 * `LB` — it sits under the same columns, and a bare "Final" twice in one
 * picture names two different matches.
 */
export function withoutUpperPrefix(label: BracketRoundLabel): BracketRoundLabel {
  switch (label.key) {
    case "upperRound":
      return { key: "round", n: label.n };
    case "upperSemifinal":
      return { key: "semifinal" };
    case "upperFinal":
      return { key: "final" };
    default:
      return label;
  }
}

/** English names, for the admin screens that are not translated. */
const ROUND_NAMES_EN: Record<BracketRoundLabel["key"], string> = {
  round: "Round {n}",
  semifinal: "Semifinal",
  final: "Final",
  upperRound: "UB Round {n}",
  upperSemifinal: "UB Semifinal",
  upperFinal: "UB Final",
  lowerRound: "LB Round {n}",
  lowerFinal: "LB Final",
  grandFinal: "Grand Final",
  grandFinalReset: "Grand Final Reset"
};

/** `bracketRoundLabel` rendered in English — the admin editors' round names. */
export function bracketRoundLabelEn(round: number, shape: BracketRoundShape): string {
  const label = bracketRoundLabel(round, shape);
  return ROUND_NAMES_EN[label.key].replace("{n}", String(label.n ?? ""));
}

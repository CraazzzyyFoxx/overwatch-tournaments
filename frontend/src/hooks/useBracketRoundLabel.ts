import { useTranslations } from "next-intl";
import { useCallback } from "react";

import {
  bracketRoundLabel,
  withoutUpperPrefix,
  type BracketRoundShape
} from "@/lib/bracket/round-name";

/** Renders a signed round number as the name the bracket shows for it. */
export type BracketRoundLabelFormatter = (round: number, shape: BracketRoundShape) => string;

/**
 * The single renderer for a bracket round's name.
 *
 * Every translated screen that names a round goes through this, so the bracket,
 * the match lists and the pick-ban scope picker cannot drift into calling the
 * same round "Round 3" in one place and "UB Final" in another. The admin
 * editors render the same names through `bracketRoundLabelEn`.
 *
 * `bareUpper` drops the upper bracket's `UB` prefix — for the bracket tree,
 * whose upper rounds are already a labelled row of columns.
 */
export function useBracketRoundLabel(
  options: { bareUpper?: boolean } = {}
): BracketRoundLabelFormatter {
  const t = useTranslations("bracket");
  const { bareUpper = false } = options;

  return useCallback(
    (round, shape) => {
      const label = bracketRoundLabel(round, shape);
      const { key, n } = bareUpper ? withoutUpperPrefix(label) : label;
      return n === undefined ? t(key) : t(key, { n: String(n) });
    },
    [t, bareUpper]
  );
}

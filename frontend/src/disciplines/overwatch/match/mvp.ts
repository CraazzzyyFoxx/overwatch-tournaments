import type { MatchWithUserStats } from "@/types/user.types";

export type MvpRank = "gold" | "silver" | "bronze" | "default";

/** Map a 1-based per-match performance placement to an MVP medal rank. */
export const mvpRank = (place: number | null | undefined): MvpRank => {
  if (place === 1) return "gold";
  if (place === 2) return "silver";
  if (place === 3) return "bronze";
  return "default";
};

/** Official MVP placement from a member's whole-match facts: `impact_rank`. An absent fact is missing, never a placement. */
export const resolveMvpPlacement = (
  facts: Readonly<Record<string, number>> | null | undefined
): number | null => facts?.impact_rank ?? null;

/** Whether the viewer earned the overperformance badge: the backend stores it as the `overperformance_badge` fact. */
export const overperformanceBadge = (match: Pick<MatchWithUserStats, "viewer">): boolean =>
  match.viewer?.facts.overperformance_badge === 1;

/**
 * Signed display (1 decimal unless `digits` says otherwise) for the overperformance score (map quality vs the
 * expectation for the player's role and rank quintile) and for impact contributions. `raised` drives the up/down +
 * positive/negative styling. Returns null when there is no score (no rank quintile / not computed).
 */
export const formatOverperformance = (
  score: number | null | undefined,
  digits = 1
): { text: string; raised: boolean } | null => {
  if (score == null || Number.isNaN(score)) return null;
  const raised = score >= 0;
  return { text: `${raised ? "+" : "−"}${Math.abs(score).toFixed(digits)}`, raised };
};

const ORDINAL_PLURAL_RULES = new Intl.PluralRules("en-US", { type: "ordinal" });
const ORDINAL_SUFFIXES: Partial<Record<Intl.LDMLPluralRule, string>> = {
  one: "st",
  two: "nd",
  few: "rd"
};

/** Ordinal for a positive integer ("1st", "2nd", "13th"), shown in every locale. */
export const ordinal = (n: number): string => {
  if (!Number.isFinite(n)) return String(n);
  return `${n}${ORDINAL_SUFFIXES[ORDINAL_PLURAL_RULES.select(n)] ?? "th"}`;
};

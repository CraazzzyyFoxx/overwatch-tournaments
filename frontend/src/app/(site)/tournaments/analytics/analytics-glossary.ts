/**
 * Glossary term registry for the analytics page.
 *
 * The user-facing label and one-sentence explanation for each term live in the
 * i18n message files under the `analytics.glossary.<term>` namespace
 * (en.ts / ru.ts), so this module only owns the term *identifiers*. Consumers
 * render them via `MetricTooltip`, which translates `label` / `plain`.
 */

export type GlossaryTerm =
  | "confidence"
  | "shift"
  | "impact"
  | "vs_local"
  | "points"
  | "recent_moves"
  | "forecast_place"
  | "likely_range"
  | "prob_top"
  | "competitiveness"
  | "predictability"
  | "skill_balance"
  | "match_quality"
  | "forecast_miss"
  | "evidence"
  | "newcomer"
  | "why_score"
  | "smurf"
  | "throw"
  | "troll"
  | "sandbag";

/** Anomaly ``kind`` values that have a glossary entry. */
export const ANOMALY_GLOSSARY_TERMS: ReadonlySet<GlossaryTerm> = new Set([
  "smurf",
  "throw",
  "troll",
  "sandbag",
]);

export function isAnomalyGlossaryTerm(kind: string): kind is GlossaryTerm {
  return ANOMALY_GLOSSARY_TERMS.has(kind as GlossaryTerm);
}

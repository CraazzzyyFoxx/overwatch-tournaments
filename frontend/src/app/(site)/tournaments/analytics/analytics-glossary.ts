/**
 * Plain-language glossary for the analytics page.
 *
 * Every ML / stats term shown to an organizer maps to a short, jargon-free
 * label and a one-sentence explanation. The raw numbers still live in the UI
 * (usually inside a tooltip), but nobody has to already know what "local
 * z-score" or "P(top 3)" means to read the page.
 */

export interface GlossaryEntry {
  /** Short, human label shown in the UI. */
  label: string;
  /** One-sentence plain explanation surfaced in the ⓘ tooltip. */
  plain: string;
}

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

export const ANALYTICS_GLOSSARY: Record<GlossaryTerm, GlossaryEntry> = {
  confidence: {
    label: "Confidence",
    plain:
      "How sure the model is about this forecast, based on how much history and match data it had.",
  },
  shift: {
    label: "Division adjustment",
    plain:
      "Suggested change to a player's division for the next tournament (＋ moves up, − moves down).",
  },
  impact: {
    label: "Impact",
    plain:
      "How much better or worse the player did than expected for the match-up — 0–100 within their role.",
  },
  vs_local: {
    label: "vs similar players",
    plain:
      "Performance compared to players of the same role and nearby division (0 = average, ＋ above, − below).",
  },
  points: {
    label: "Move signal",
    plain:
      "The raw signal driving the division forecast — the larger it is, the stronger the up/down push.",
  },
  recent_moves: {
    label: "Recent moves",
    plain: "Division changes in the player's last two tournaments.",
  },
  forecast_place: {
    label: "Forecast place",
    plain: "Where the model expects the team to finish.",
  },
  likely_range: {
    label: "Likely finish",
    plain: "Where the team lands in 80% of simulated tournaments (10th–90th percentile).",
  },
  prob_top: {
    label: "Chance for top finish",
    plain: "Share of simulated tournaments where the team finished in the top N.",
  },
  competitiveness: {
    label: "How close",
    plain: "How back-and-forth the match was — 100 is a nail-biter, 0 is a blowout.",
  },
  predictability: {
    label: "How expected",
    plain: "How well the result matched the pre-match forecast — 100 means it went as expected.",
  },
  skill_balance: {
    label: "How even",
    plain: "How evenly matched the two teams' ratings were — 100 is a perfectly even match-up.",
  },
  match_quality: {
    label: "Match quality",
    plain: "Overall watchability: a blend of how close, how expected and how even the match was.",
  },
  forecast_miss: {
    label: "Forecast miss",
    plain: "How far the forecast landed from the real finish, in places.",
  },
  evidence: {
    label: "Evidence",
    plain: "Weighted amount of history behind the forecast — more evidence means more confidence.",
  },
  newcomer: {
    label: "Newcomer",
    plain: "Playing their first tournament, or their first time in this role.",
  },
  why_score: {
    label: "Why this score",
    plain: "The player stats that pushed the impact score up or down the most.",
  },
  smurf: {
    label: "Possible smurf",
    plain: "Performing far above their division — may be an under-ranked account.",
  },
  throw: {
    label: "Possible throw",
    plain: "A sharp drop in performance partway through a series.",
  },
  troll: {
    label: "Possible griefing",
    plain: "Repeatedly underperforming their own nearby-division baseline.",
  },
  sandbag: {
    label: "Possible sandbag",
    plain: "A sudden one-tournament collapse versus the player's own track record.",
  },
};

/** Resolve an anomaly ``kind`` string to its glossary entry (smurf/throw/...). */
export function anomalyGlossary(kind: string): GlossaryEntry | undefined {
  return ANALYTICS_GLOSSARY[kind as GlossaryTerm];
}

import {
  AlgorithmAnalytics,
  PlayerAnalytics,
  TournamentAnalyticsSummary,
} from "@/types/analytics.types";

const RECOMMENDED_ALGORITHM_ORDER = [
  "Linear",
  "Points",
  "OpenSkill + ML",
] as const;

// The ML shift algorithm is preferred as the default *when it has data* for the
// tournament — it consumes Performance v2 and is the richest signal. Until a v2
// inference run populates it, the display/fallback order above still applies.
export const PREFERRED_ML_ALGORITHM_NAME = "OpenSkill + ML";

const algorithmPriority = new Map<string, number>(
  RECOMMENDED_ALGORITHM_ORDER.map((name, index) => [name, index]),
);

export function sortAnalyticsAlgorithms(
  algorithms: AlgorithmAnalytics[],
): AlgorithmAnalytics[] {
  return [...algorithms].sort((left, right) => {
    const leftPriority = algorithmPriority.get(left.name) ?? Number.MAX_SAFE_INTEGER;
    const rightPriority = algorithmPriority.get(right.name) ?? Number.MAX_SAFE_INTEGER;

    if (leftPriority !== rightPriority) {
      return leftPriority - rightPriority;
    }

    return left.name.localeCompare(right.name) || left.id - right.id;
  });
}

export function getPreferredAnalyticsAlgorithmId(
  algorithms: AlgorithmAnalytics[],
): number | null {
  // Prefer the ML shift algorithm when it has computed data for the tournament;
  // otherwise fall back to the recommended display order (Linear › Points › ML).
  const mlWithData = algorithms.find(
    (algorithm) => algorithm.name === PREFERRED_ML_ALGORITHM_NAME && algorithm.has_data === true,
  );
  if (mlWithData) {
    return mlWithData.id;
  }
  return sortAnalyticsAlgorithms(algorithms)[0]?.id ?? null;
}

export function canShowAnalyticsAdminToolbar(
  canUpdateAnalytics: boolean,
): boolean {
  return canUpdateAnalytics;
}

export function getAnalyticsRefreshKeys(
  workspaceId: number | null | undefined,
  tournamentId: number,
  algorithmId: number | null,
): Array<Array<string | number>> {
  const scope = workspaceId ?? "global";
  const keys: Array<Array<string | number>> = [["analytics", scope, tournamentId]];

  if (algorithmId != null) {
    keys.push(["analytics", scope, tournamentId, algorithmId]);
  }

  return keys;
}

export function clampConfidence(confidence: number): number {
  return Math.max(0, Math.min(1, confidence));
}

export type ConfidenceTone = "high" | "medium" | "low";

/**
 * Plain-language confidence so the read view never shows a bare 0–1 number.
 * Thresholds match {@link getConfidenceBadgeClass}.
 */
export function confidenceWord(confidence: number): { label: string; tone: ConfidenceTone } {
  const clamped = clampConfidence(confidence);
  if (clamped >= 0.75) return { label: "High", tone: "high" };
  if (clamped >= 0.45) return { label: "Medium", tone: "medium" };
  return { label: "Low", tone: "low" };
}

export function pluralize(count: number, singular: string, plural: string): string {
  return `${count} ${count === 1 ? singular : plural}`;
}

export interface AnalyticsVerdict {
  headline: string;
  clauses: string[];
}

type VerdictSummary = Pick<
  TournamentAnalyticsSummary,
  | "total_teams"
  | "total_players"
  | "anomaly_count"
  | "divergent_team_count"
  | "newcomer_count"
  | "avg_placement_delta"
>;

/**
 * Turn the raw summary counters into a one-glance briefing sentence: a headline
 * (teams/players) plus only the supporting clauses that actually apply, ending
 * with a calm forecast-accuracy note. Optional clauses are omitted when zero so
 * a quiet tournament reads as quiet.
 */
export function buildVerdictClauses(
  summary: VerdictSummary,
  predictedMoves: number,
): AnalyticsVerdict {
  const headline = `${pluralize(summary.total_teams, "team", "teams")} · ${pluralize(
    summary.total_players,
    "player",
    "players",
  )}`;

  const clauses: string[] = [];
  if (predictedMoves > 0) {
    clauses.push(pluralize(predictedMoves, "likely division change", "likely division changes"));
  }
  if (summary.anomaly_count > 0) {
    clauses.push(`${pluralize(summary.anomaly_count, "flag", "flags")} to review`);
  }
  if (summary.divergent_team_count > 0) {
    clauses.push(
      `${pluralize(summary.divergent_team_count, "team", "teams")} the forecast missed badly`,
    );
  }
  if (summary.newcomer_count > 0) {
    clauses.push(pluralize(summary.newcomer_count, "newcomer", "newcomers"));
  }
  clauses.push(
    `forecast off by ~${(summary.avg_placement_delta ?? 0).toFixed(1)} places on average`,
  );

  return { headline, clauses };
}

export function formatConfidencePercent(confidence: number): string {
  return `${Math.round(clampConfidence(confidence) * 100)}%`;
}

export function getConfidenceBadgeClass(confidence: number): string {
  const clamped = clampConfidence(confidence);

  if (clamped >= 0.75) {
    return "border-emerald-500/40 bg-emerald-500/12 text-emerald-200";
  }

  if (clamped >= 0.45) {
    return "border-amber-500/40 bg-amber-500/12 text-amber-100";
  }

  return "border-border/60 bg-muted/55 text-muted-foreground";
}

export function formatAnalyticsNumber(
  value: number | null | undefined,
  fractionDigits = 2,
): string {
  if (value == null || Number.isNaN(value)) {
    return "0";
  }

  const rounded = value.toFixed(fractionDigits).replace(/\.?0+$/, "");
  if (rounded === "-0") {
    return "0";
  }

  return rounded;
}

type ConfidenceBreakdownSource = Pick<
  PlayerAnalytics,
  | "confidence"
  | "effective_evidence"
  | "sample_tournaments"
  | "sample_matches"
  | "log_coverage"
>;

export function getConfidenceBreakdownLines(
  player: ConfidenceBreakdownSource,
): string[] {
  return [
    `Confidence: ${formatConfidencePercent(player.confidence)}`,
    `Evidence: ${formatAnalyticsNumber(player.effective_evidence)}`,
    `Tournaments: ${player.sample_tournaments}`,
    `Matches: ${player.sample_matches}`,
    `Log coverage: ${formatConfidencePercent(player.log_coverage)}`,
  ];
}

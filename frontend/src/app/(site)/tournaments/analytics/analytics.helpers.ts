import { AlgorithmAnalytics, PlayerAnalytics } from "@/types/analytics.types";

const RECOMMENDED_ALGORITHM_ORDER = [
  "Linear",
  "Points",
  "OpenSkill + ML",
] as const;

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

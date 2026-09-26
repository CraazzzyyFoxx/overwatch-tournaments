import type { KeyPart } from "@/lib/query-keys";

/**
 * Keys for the ML analytics page: per-algorithm performance, the match-quality
 * card and the admin job toolbar. `workspaceScope` is the current workspace id
 * or the literal `"global"` -- the page offers both audiences and they are
 * different answers, so the marker is part of the key.
 */
export const analyticsQueryKeys = {
  activeJob: (workspaceScope: KeyPart) => ["analytics-active-job", workspaceScope] as const,
  anomalyFeedback: (tournamentId: KeyPart) =>
    ["analytics-anomaly-feedback", tournamentId] as const,
  explanation: (playerId: KeyPart, tournamentId: KeyPart, algorithmId: KeyPart) =>
    ["analytics-explanation", playerId, tournamentId, algorithmId] as const,
  job: (jobId: KeyPart) => ["analytics-job", jobId] as const,
  matchQuality: (tournamentId: KeyPart) => ["analytics-match-quality", tournamentId] as const,
  standingsDistribution: (tournamentId: KeyPart) =>
    ["analytics-standings-distribution", tournamentId, undefined] as const,
  algorithms: (tournamentId: KeyPart) => ["analytics", "algorithms", tournamentId] as const,
  performanceV2: (tournamentId: KeyPart) =>
    ["analytics", "performance-v2", tournamentId] as const,
  performance: (workspaceScope: KeyPart, tournamentId: KeyPart, algorithmId: KeyPart) =>
    ["analytics", workspaceScope, tournamentId, algorithmId] as const,
  all: () => ["analytics"] as const,
  /** Every tournament's distribution, for the realtime job signal. */
  standingsDistributionAll: () => ["analytics-standings-distribution"] as const,
  /** Every tournament's quality card, for the realtime job signal. */
  matchQualityAll: () => ["analytics-match-quality"] as const,
};

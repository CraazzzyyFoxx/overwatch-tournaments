import { PaginatedResponse } from "@/types/pagination.types";
import { apiFetch } from "@/lib/api-fetch";
import {
  AlgorithmAnalytics,
  AnalyticsJob,
  AnalyticsJobCreate,
  AnalyticsRecalculateResponse,
  AnomalyFeedback,
  AnomalyFeedbackInput,
  Explanation,
  JobAcceptedResponse,
  MatchQuality,
  MLArtifact,
  MLModelKind,
  PerformanceV2,
  PlayerAnomaly,
  PlayerAnalytics,
  StandingsDistribution,
  TournamentAnalytics,
} from "@/types/analytics.types";

/**
 * Client for the analytics microservice (port 8006).
 *
 * All v1 reads (algorithms, tournament analytics, shift mutation, streaks) and
 * v1 writes (recalculate) live in analytics-service after the Phase 0
 * extraction. v2 ML endpoints live under `/v2/*`.
 */
export default class analyticsService {
  // ── v1 (legacy) ─────────────────────────────────────────────────────────

  static async getAnalytics(
    id: number,
    algorithm: number,
    workspaceId?: number | null,
  ): Promise<TournamentAnalytics> {
    return apiFetch("analytics", `analytics`, {
      query: {
        tournament_id: id,
        algorithm: algorithm,
        workspace_id: workspaceId,
      },
    }).then((response) => response.json());
  }

  static async patchPlayerShift(
    teamId: number,
    playerId: number,
    shift: number,
  ): Promise<PlayerAnalytics> {
    return apiFetch("analytics", `analytics/shift`, {
      method: "POST",
      body: {
        team_id: teamId,
        player_id: playerId,
        shift: shift,
      },
    }).then((response) => response.json());
  }

  static async getAlgorithms(
    tournamentId?: number | null,
  ): Promise<PaginatedResponse<AlgorithmAnalytics>> {
    return apiFetch("analytics", `analytics/algorithms`, {
      query: {
        page: 1,
        per_page: -1,
        sort: "id",
        order: "desc",
        ...(tournamentId != null ? { tournament_id: tournamentId } : {}),
      },
    }).then((response) => response.json());
  }

  static async recalculateAnalytics(
    tournamentId: number,
    algorithmIds?: number[],
    workspaceId?: number | null,
  ): Promise<AnalyticsRecalculateResponse> {
    return apiFetch("analytics", "analytics/recalculate", {
      query: { workspace_id: workspaceId },
      method: "POST",
      body: {
        tournament_id: tournamentId,
        ...(algorithmIds?.length ? { algorithm_ids: algorithmIds } : {}),
      },
    }).then((response) => response.json());
  }

  // ── v2 ML ───────────────────────────────────────────────────────────────

  static async getPerformanceV2(
    tournamentId: number,
    algorithmId?: number,
  ): Promise<PerformanceV2[]> {
    return apiFetch("analytics", "v2/performance", {
      query: { tournament_id: tournamentId, algorithm_id: algorithmId },
    }).then((response) => response.json());
  }

  static async getStandingsDistribution(
    tournamentId: number,
    algorithmId?: number,
  ): Promise<StandingsDistribution[]> {
    return apiFetch("analytics", "v2/standings/distribution", {
      query: { tournament_id: tournamentId, algorithm_id: algorithmId },
    }).then((response) => response.json());
  }

  static async getMatchQuality(
    tournamentId: number,
    algorithmId?: number,
  ): Promise<MatchQuality[]> {
    return apiFetch("analytics", "v2/match-quality", {
      query: { tournament_id: tournamentId, algorithm_id: algorithmId },
    }).then((response) => response.json());
  }

  static async getPlayerAnomalies(
    tournamentId: number,
    playerId?: number,
    kind?: string,
  ): Promise<PlayerAnomaly[]> {
    return apiFetch("analytics", "v2/player-anomalies", {
      query: {
        tournament_id: tournamentId,
        player_id: playerId,
        kind,
      },
    }).then((response) => response.json());
  }

  static async getAnomalyFeedback(
    tournamentId: number,
  ): Promise<AnomalyFeedback[]> {
    return apiFetch("analytics", "v2/player-anomalies/feedback", {
      query: { tournament_id: tournamentId },
    }).then((response) => response.json());
  }

  static async submitAnomalyFeedback(
    body: AnomalyFeedbackInput,
  ): Promise<AnomalyFeedback> {
    return apiFetch("analytics", "v2/player-anomalies/feedback", {
      method: "POST",
      body,
    }).then((response) => response.json());
  }

  static async getPlayerExplanation(
    playerId: number,
    tournamentId: number,
    algorithmId?: number,
  ): Promise<Explanation> {
    return apiFetch(
      "analytics",
      `v2/explain/player/${playerId}/tournament/${tournamentId}`,
      {
        query: { algorithm_id: algorithmId },
      },
    ).then((response) => response.json());
  }

  // ── v2 ML admin (dispatch + artifact registry) ──────────────────────────

  static async listArtifacts(
    modelKind?: MLModelKind,
    activeOnly = false,
  ): Promise<MLArtifact[]> {
    return apiFetch("analytics", "v2/artifacts", {
      query: { model_kind: modelKind, active_only: activeOnly || undefined },
    }).then((response) => response.json());
  }

  static async trainV2(
    cutoffTournamentId: number,
    modelKinds?: MLModelKind[],
    workspaceId?: number | null,
    workspaceIds?: number[] | null,
  ): Promise<JobAcceptedResponse> {
    return apiFetch("analytics", "v2/train", {
      method: "POST",
      body: {
        cutoff_tournament_id: cutoffTournamentId,
        ...(modelKinds?.length ? { model_kinds: modelKinds } : {}),
        ...(workspaceId != null ? { workspace_id: workspaceId } : {}),
        ...(workspaceIds !== undefined ? { workspace_ids: workspaceIds } : {}),
      },
    }).then((response) => response.json());
  }

  static async inferV2(
    tournamentId: number,
    modelKinds?: MLModelKind[],
    workspaceId?: number | null,
  ): Promise<JobAcceptedResponse> {
    return apiFetch("analytics", "v2/infer", {
      method: "POST",
      body: {
        tournament_id: tournamentId,
        ...(modelKinds?.length ? { model_kinds: modelKinds } : {}),
        ...(workspaceId != null ? { workspace_id: workspaceId } : {}),
      },
    }).then((response) => response.json());
  }

  // ── Unified analytics job pipeline ──────────────────────────────────────

  static async createJob(
    body: AnalyticsJobCreate,
    workspaceId?: number | null,
  ): Promise<AnalyticsJob> {
    return apiFetch("analytics", "v2/jobs", {
      method: "POST",
      query: { workspace_id: workspaceId },
      body,
    }).then((response) => response.json());
  }

  static async getActiveJob(
    workspaceId?: number | null,
  ): Promise<AnalyticsJob | null> {
    return apiFetch("analytics", "v2/jobs/active", {
      query: { workspace_id: workspaceId },
    }).then((response) => response.json());
  }

  static async getJob(jobId: number): Promise<AnalyticsJob> {
    return apiFetch("analytics", `v2/jobs/${jobId}`).then((response) => response.json());
  }

  static async listJobs(
    activeOnly = false,
    limit = 20,
    workspaceId?: number | null,
  ): Promise<AnalyticsJob[]> {
    return apiFetch("analytics", "v2/jobs", {
      query: {
        active_only: activeOnly || undefined,
        limit,
        workspace_id: workspaceId,
      },
    }).then((response) => response.json());
  }
}

import { PaginatedResponse } from "@/types/pagination.types";
import { apiFetch } from "@/lib/api/fetch";
import {
  AlgorithmAnalytics,
  AnalyticsJob,
  AnalyticsJobCreate,
  AnomalyFeedback,
  AnomalyFeedbackInput,
  Explanation,
  MatchQuality,
  MLArtifact,
  MLModelKind,
  PerformanceV2,
  PlayerAnomaly,
  PlayerShiftUpdate,
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
    { signal }: { signal?: AbortSignal } = {},
  ): Promise<TournamentAnalytics> {
    return apiFetch(`/api/v1/analytics`, {
      signal,
      query: {
        tournament_id: id,
        algorithm: algorithm,
        workspace_id: workspaceId,
      },
    }).then((response) => response.json());
  }

  static async patchPlayerShift(playerId: number, shift: number): Promise<PlayerShiftUpdate> {
    return apiFetch(`/api/v1/analytics/shift`, {
      method: "POST",
      body: {
        player_id: playerId,
        shift: shift,
      },
    }).then((response) => response.json());
  }

  static async getAlgorithms(
    tournamentId?: number | null,
    { signal }: { signal?: AbortSignal } = {},
  ): Promise<PaginatedResponse<AlgorithmAnalytics>> {
    return apiFetch(`/api/v1/analytics/algorithms`, {
      signal,
      query: {
        page: 1,
        per_page: -1,
        sort: "id",
        order: "desc",
        ...(tournamentId != null ? { tournament_id: tournamentId } : {}),
      },
    }).then((response) => response.json());
  }

  // Now enqueues an async compute job (202) instead of computing synchronously;
  // the returned AnalyticsJob can be tracked via the job-status endpoints/realtime.
  static async recalculateAnalytics(
    tournamentId: number,
    algorithmIds?: number[],
    workspaceId?: number | null,
  ): Promise<AnalyticsJob> {
    return apiFetch("/api/v1/analytics/recalculate", {
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
    { signal }: { signal?: AbortSignal } = {},
  ): Promise<PerformanceV2[]> {
    return apiFetch("/api/v1/analytics/performance", {
      signal,
      query: { tournament_id: tournamentId, algorithm_id: algorithmId },
    }).then((response) => response.json());
  }

  static async getStandingsDistribution(
    tournamentId: number,
    algorithmId?: number,
    { signal }: { signal?: AbortSignal } = {},
  ): Promise<StandingsDistribution[]> {
    return apiFetch("/api/v1/analytics/standings/distribution", {
      signal,
      query: { tournament_id: tournamentId, algorithm_id: algorithmId },
    }).then((response) => response.json());
  }

  static async getMatchQuality(
    tournamentId: number,
    algorithmId?: number,
  ): Promise<MatchQuality[]> {
    return apiFetch("/api/v1/analytics/match-quality", {
      query: { tournament_id: tournamentId, algorithm_id: algorithmId },
    }).then((response) => response.json());
  }

  static async getPlayerAnomalies(
    tournamentId: number,
    playerId?: number,
    kind?: string,
  ): Promise<PlayerAnomaly[]> {
    return apiFetch("/api/v1/analytics/player-anomalies", {
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
    return apiFetch("/api/v1/analytics/player-anomalies/feedback", {
      query: { tournament_id: tournamentId },
    }).then((response) => response.json());
  }

  static async submitAnomalyFeedback(
    body: AnomalyFeedbackInput,
  ): Promise<AnomalyFeedback> {
    return apiFetch("/api/v1/analytics/player-anomalies/feedback", {
      method: "POST",
      body,
    }).then((response) => response.json());
  }

  static async getPlayerExplanation(
    playerId: number,
    tournamentId: number,
    algorithmId?: number,
  ): Promise<Explanation> {
    return apiFetch(`/api/v1/analytics/explain/player/${playerId}/tournament/${tournamentId}`,
      {
        query: { algorithm_id: algorithmId },
      },
    ).then((response) => response.json());
  }

  // ── v2 ML artifact registry ─────────────────────────────────────────────

  static async listArtifacts(
    modelKind?: MLModelKind,
    activeOnly = false,
  ): Promise<MLArtifact[]> {
    return apiFetch("/api/v1/analytics/artifacts", {
      query: { model_kind: modelKind, active_only: activeOnly || undefined },
    }).then((response) => response.json());
  }

  // ── Unified analytics job pipeline ──────────────────────────────────────

  static async createJob(
    body: AnalyticsJobCreate,
    workspaceId?: number | null,
  ): Promise<AnalyticsJob> {
    return apiFetch("/api/v1/analytics/jobs", {
      method: "POST",
      query: { workspace_id: workspaceId },
      body,
    }).then((response) => response.json());
  }

  static async getActiveJob(
    workspaceId?: number | null,
  ): Promise<AnalyticsJob | null> {
    return apiFetch("/api/v1/analytics/jobs/active", {
      query: { workspace_id: workspaceId },
    }).then((response) => response.json());
  }

  static async getJob(jobId: number): Promise<AnalyticsJob> {
    return apiFetch(`/api/v1/analytics/jobs/${jobId}`).then((response) => response.json());
  }

  static async listJobs(
    activeOnly = false,
    limit = 20,
    workspaceId?: number | null,
  ): Promise<AnalyticsJob[]> {
    return apiFetch("/api/v1/analytics/jobs", {
      query: {
        active_only: activeOnly || undefined,
        limit,
        workspace_id: workspaceId,
      },
    }).then((response) => response.json());
  }
}
